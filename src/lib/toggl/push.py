"""
Fitbit睡眠等をTogglタイムエントリとして書き込む push の共通ロジック

ソース側（sources.py）は Interval のリストを返すだけで、Toggl への書き込み・
冪等性判定・レート制御はここに集約する（将来 fitbit_activity 等を足しても
この層は変えなくてよい）。

冪等性は台帳（data/toggl/pushed.csv）を主に、直前 fetch の time_entries.csv を
補助に使う二段構え:
1. 台帳に (source, source_id) が無ければ投入対象
2. 台帳にはあるが toggl_entry_id が time_entries.csv に見当たらない
   （＝Toggl側で手動削除された）場合は再投入対象。ただし判定は
   **直近 fetch が実際に取りに行った期間**（store.load_fetch_window）内に
   start を持つ行に限る。期間外は「取得していないだけ」と区別できないため、
   無限に再投入してしまう安全弁として対象外にする
3. 台帳にあり CSV にも居れば skip

削除判定の窓に CSV の start の min/max を使ってはいけない。CSV は過去分が
積み上がるだけなので min は何ヶ月も前になり、「一度も fetch していない日」まで
カバー済みと誤認する。睡眠エントリの start は dateOfSleep の前日夜にあるため、
fetch と push を同じ --days N で回すと投入したエントリが翌日以降どの fetch 窓にも
入らず、毎回「削除された」と誤判定されて重複投入される。
"""

import dataclasses
import datetime as dt
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

PUSH_CONFIG_FILE = BASE_DIR / 'config' / 'toggl_push.yaml'
PERSONAL_CONFIG_FILE = BASE_DIR / 'config' / 'personal.yaml'

# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
LEDGER_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'pushed.csv')

LEDGER_COLUMNS = ['source', 'source_id', 'toggl_entry_id', 'start', 'pushed_at']

DEFAULT_TIMEZONE = 'Asia/Tokyo'
DEFAULT_MAX_WRITES = 10


@dataclasses.dataclass(frozen=True)
class Interval:
    source: str        # 例: "fitbit_sleep"
    source_id: str     # ソース内で一意なID（Fitbitならlog Id）
    start: dt.datetime  # tz-aware
    stop: dt.datetime   # tz-aware
    description: str
    project: str        # プロジェクト名。IDへの解決はpush側で行う
    tags: tuple[str, ...]


def load_push_config() -> dict:
    """config/toggl_push.yaml を読む"""
    with open(PUSH_CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_timezone() -> ZoneInfo:
    """config/personal.yaml の timezone。未設定ならAsia/Tokyo"""
    if not PERSONAL_CONFIG_FILE.exists():
        return ZoneInfo(DEFAULT_TIMEZONE)
    with open(PERSONAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}
    return ZoneInfo(config.get('timezone') or DEFAULT_TIMEZONE)


def load_ledger() -> pd.DataFrame:
    """台帳を読む。無ければ空DataFrame"""
    if not LEDGER_FILE.exists():
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    return pd.read_csv(LEDGER_FILE, dtype={'source_id': str, 'toggl_entry_id': str})


def append_ledger(rows: list[dict]) -> None:
    """台帳に追記する。既存の (source, source_id) は新しい行で上書きする"""
    if not rows:
        return
    df_new = pd.DataFrame(rows, columns=LEDGER_COLUMNS)
    df_new['source_id'] = df_new['source_id'].astype(str)
    df_new['toggl_entry_id'] = df_new['toggl_entry_id'].astype(str)

    df_old = load_ledger()
    df_merged = pd.concat([df_old, df_new])
    df_merged = df_merged.drop_duplicates(subset=['source', 'source_id'], keep='last')
    df_merged = df_merged.sort_values('start')

    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(LEDGER_FILE, index=False)


def fetch_window_bounds(fetch_window: tuple[dt.date, dt.date] | None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """fetch 期間（両端を含む日付）を start 比較用の tz-naive JST 区間に変換"""
    if fetch_window is None:
        return None
    start, end = fetch_window
    return pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)


def _pushed_before_fetch(pushed_at, fetched_at: dt.datetime | None) -> bool:
    """その投入は直近 fetch より前か（＝CSV に居ないなら削除されたと言えるか）

    fetched_at が無い、または pushed_at が読めない場合は False を返す。
    「削除されたか分からない」を「再投入する」に倒すと重複が増えるため、
    判断できないときは再投入しない側へ寄せる。
    """
    if fetched_at is None:
        return False
    try:
        pushed = pd.Timestamp(pushed_at)
    except (ValueError, TypeError):
        return False
    if pushed is pd.NaT or pd.isna(pushed):
        return False
    if pushed.tzinfo is None:
        pushed = pushed.tz_localize(fetched_at.tzinfo)
    return pushed < pd.Timestamp(fetched_at)


def select_pending(
    intervals: list[Interval],
    ledger_df: pd.DataFrame,
    entries_df: pd.DataFrame | None,
    check_deleted: bool = True,
    fetch_window: tuple[dt.date, dt.date] | None = None,
    fetched_at: dt.datetime | None = None,
) -> tuple[list[Interval], int]:
    """投入対象の Interval と skip 件数を返す

    Parameters
    ----------
    intervals : list[Interval]
        投入候補
    ledger_df : pd.DataFrame
        台帳（load_ledger() の戻り値相当）
    entries_df : pd.DataFrame | None
        直前 fetch の time_entries.csv 相当（id, start 列を持つ）。
        None は CSV が読めない/古いことを示し、削除検出を行わない
    check_deleted : bool
        False の場合、台帳にある interval は無条件で skip する
        （time_entries.csv が古い/存在しないときに呼び出し側が指定する）
    fetch_window : tuple[date, date] | None
        直近 fetch が取りに行った期間（両端を含む）。None なら削除検出を行わない。
        CSV の start の min/max で代用してはいけない（モジュール docstring 参照）
    fetched_at : datetime | None
        直近 fetch を実行した時刻。これより後に投入したエントリは削除判定から外す

    Returns
    -------
    (pending, skipped_count)
    """
    ledger_keys = set(zip(ledger_df['source'], ledger_df['source_id'].astype(str))) \
        if not ledger_df.empty else set()

    csv_ids = set(entries_df['id'].astype(str)) if entries_df is not None and not entries_df.empty else set()
    coverage = fetch_window_bounds(fetch_window) if check_deleted else None

    ledger_by_key = {}
    if not ledger_df.empty:
        for _, row in ledger_df.iterrows():
            ledger_by_key[(row['source'], str(row['source_id']))] = row

    pending = []
    skipped = 0
    for interval in intervals:
        key = (interval.source, interval.source_id)
        if key not in ledger_keys:
            pending.append(interval)
            continue

        if not check_deleted or coverage is None:
            skipped += 1
            continue

        row = ledger_by_key[key]
        toggl_entry_id = str(row['toggl_entry_id'])
        if toggl_entry_id in csv_ids:
            skipped += 1
            continue

        # 直近 fetch より後に投入したものは、まだ一度も取りに行っていないので
        # CSV に居なくて当たり前。ここを見ないと、fetch を挟まずに push を
        # 2回叩いただけで「削除された」と誤読して重複投入する。
        # pushed_at が読めないものも、疑わしきは再投入しない側に倒す
        if not _pushed_before_fetch(row.get('pushed_at'), fetched_at):
            skipped += 1
            continue

        # fetch 窓の外は「未取得」と「削除済み」が区別できないためskip。
        # time_entries.csv の start は tz-naive JST なので、台帳側(tz-aware)も
        # tzinfoを落として比較する（どちらも同じJSTの壁時計時刻）
        row_start = pd.Timestamp(row['start'])
        if row_start.tzinfo is not None:
            row_start = row_start.tz_localize(None)
        if not (coverage[0] <= row_start < coverage[1]):
            skipped += 1
            continue

        pending.append(interval)

    return pending, skipped


def is_entries_csv_stale(entries_df: pd.DataFrame | None, today: dt.date) -> bool:
    """time_entries.csv が古い（前日より前で止まっている）か、存在しないか"""
    if entries_df is None or entries_df.empty:
        return True
    latest = pd.to_datetime(entries_df['start']).max().date()
    return latest < today - dt.timedelta(days=1)


def resolve_project_id(project_name: str, project_map: dict[str, int]) -> int | None:
    return project_map.get(project_name)


def build_payload(interval: Interval, workspace_id: int, project_map: dict[str, int]) -> dict:
    """Toggl API へのPOSTペイロードを組み立てる"""
    # Toggl は秒未満を含む RFC3339 を 400 で弾く。Health Connect 由来の
    # セッションはミリ秒付きで届くので、秒に丸めてから渡す
    start = interval.start.replace(microsecond=0)
    stop = interval.stop.replace(microsecond=0)
    payload = {
        'created_with': 'dailybuild',
        'workspace_id': workspace_id,
        'description': interval.description,
        'start': start.isoformat(),
        'stop': stop.isoformat(),
        'duration': int((stop - start).total_seconds()),
        'tags': list(interval.tags),
        'billable': False,
    }
    project_id = resolve_project_id(interval.project, project_map)
    if project_id is not None:
        payload['project_id'] = project_id
    return payload


def push_intervals(
    intervals: list[Interval],
    ledger_df: pd.DataFrame,
    entries_df: pd.DataFrame | None,
    max_writes: int,
    dry_run: bool,
    api_token: str | None,
    out: IO[str],
    check_deleted: bool = True,
    fetch_window: tuple[dt.date, dt.date] | None = None,
    fetched_at: dt.datetime | None = None,
) -> dict:
    """投入対象を選び、上限内で書き込む

    途中で例外が起きても、それまでに投入した分は台帳に必ず書く
    （呼び出し側でtry/finally相当の保証をするため、ここでは1件ごとに
    ledger_rowsへ積み、最後にappend_ledgerを呼ぶ形にしている。例外は
    そのまま外へ投げるが、その前にappend_ledgerを実行する）。

    Returns
    -------
    dict
        {'pending': int, 'skipped': int, 'pushed': int, 'carried_over': int}
    """
    pending, skipped = select_pending(intervals, ledger_df, entries_df,
                                     check_deleted=check_deleted, fetch_window=fetch_window,
                                     fetched_at=fetched_at)
    pending = sorted(pending, key=lambda i: i.start)

    to_push = pending[:max_writes]
    carried_over = pending[max_writes:]

    if not to_push:
        return {
            'pending': pending, 'skipped': skipped, 'pushed': 0,
            'carried_over': carried_over,
        }

    if dry_run:
        return {
            'pending': pending, 'skipped': skipped, 'pushed': 0,
            'carried_over': carried_over, 'to_push': to_push,
        }

    from lib.toggl import client as toggl_client

    me = toggl_client.fetch_me(api_token)
    workspace_id = me.get('default_workspace_id')
    # me['projects'] は private プロジェクトを落とすので使わない（client.fetch_projects 参照）
    project_map = {name: pid
                   for pid, name in toggl_client.fetch_projects(api_token, workspace_id).items()}

    # プロジェクトが Toggl 側に無いまま投入すると、project 無しのエントリが
    # 台帳に「投入済み」として残り、後からプロジェクトを作っても直せない。
    # 投入せず次回に回す（Toggl 側でプロジェクトを作れば自然に流れる）
    missing = sorted({i.project for i in to_push if i.project not in project_map})
    if missing:
        print(f"⚠️ プロジェクトが Toggl 側に無いため投入を見送る: {', '.join(missing)}", file=out)
        to_push = [i for i in to_push if i.project in project_map]

    ledger_rows = []
    pushed = 0
    now_str = dt.datetime.now(load_timezone()).isoformat()

    try:
        for interval in to_push:
            payload = build_payload(interval, workspace_id, project_map)
            created = toggl_client.create_time_entry(api_token, workspace_id, payload)

            ledger_rows.append({
                'source': interval.source,
                'source_id': interval.source_id,
                'toggl_entry_id': str(created['id']),
                'start': interval.start.isoformat(),
                'pushed_at': now_str,
            })
            pushed += 1
    finally:
        append_ledger(ledger_rows)

    return {
        'pending': pending, 'skipped': skipped, 'pushed': pushed,
        'carried_over': carried_over,
    }
