"""
Google Health睡眠等をToggl 2.0（Focus）のタイムエントリとして書き込む push の共通ロジック

ソース側（sources.py）は Interval のリストを返すだけで、Toggl への書き込み・
冪等性判定・レート制御はここに集約する（将来 googlehealth_activity 等を足しても
この層は変えなくてよい）。

冪等性は次の2つだけで取る:
1. 台帳（data/toggl/focus_pushed.csv）に (source, source_id) があれば投入済み
2. focus_entries.csv に、同じプロジェクト名で start の差が60秒以内のエントリがあれば投入済み
   （2026-10-27 の migrate でコピーされた分や、手で入れた分を二重にしない）

Track 時代にあった「台帳にあるが CSV に居ないものを手動削除とみなして再投入する」
経路は持たない（二重投入の事故が2回あった経路で、Focus には fetch 窓の記録も無い）。
push が作ったエントリはその場で focus_entries.csv にも書くので、次の fetch を待たずに
2 が効く。CUTOVER_DATE より前の Interval は 2.0 へ migrate 済みなので投入しない。
"""

import dataclasses
import datetime as dt
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from lib.toggl import focus
from lib.toggl import store as toggl_store
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

PUSH_CONFIG_FILE = BASE_DIR / 'config' / 'toggl_push.yaml'
PERSONAL_CONFIG_FILE = BASE_DIR / 'config' / 'personal.yaml'

# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
LEDGER_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'focus_pushed.csv')

LEDGER_COLUMNS = ['source', 'source_id', 'toggl_entry_id', 'start', 'pushed_at']

DEFAULT_TIMEZONE = 'Asia/Tokyo'
DEFAULT_MAX_WRITES = 10

# 照合で「同じエントリ」とみなす start の差（秒）
MATCH_TOLERANCE_SEC = 60


@dataclasses.dataclass(frozen=True)
class Interval:
    source: str        # 例: "googlehealth_sleep"
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

    ensure_dir(LEDGER_FILE.parent)
    df_merged.to_csv(LEDGER_FILE, index=False)


def load_focus_entries_for_match(csv_path=None) -> pd.DataFrame | None:
    """照合用に focus_entries.csv の project_name / start を読む。無ければ None"""
    csv_path = csv_path or focus.CSV_FILE
    if not csv_path.exists():
        return None
    return pd.read_csv(csv_path, usecols=['project_name', 'start'], parse_dates=['start'])


def drop_before_cutover(intervals: list[Interval]) -> tuple[list[Interval], int]:
    """CUTOVER_DATE（JST の暦日）より前に start がある Interval を外す。(残り, 外した件数)"""
    kept = [i for i in intervals
            if i.start.astimezone(toggl_store.JST).date() >= toggl_store.CUTOVER_DATE]
    return kept, len(intervals) - len(kept)


def _matches_existing(interval: Interval, starts_by_project: dict[str, list[pd.Timestamp]]) -> bool:
    start = pd.Timestamp(interval.start.astimezone(toggl_store.JST).replace(tzinfo=None))
    return any(abs((start - s).total_seconds()) <= MATCH_TOLERANCE_SEC
               for s in starts_by_project.get(interval.project, ()))


def select_pending(
    intervals: list[Interval],
    ledger_df: pd.DataFrame,
    focus_df: pd.DataFrame | None,
) -> tuple[list[Interval], int]:
    """投入対象の Interval と skip 件数を返す

    台帳にある、または focus_entries.csv に同じプロジェクト・60秒以内の start が
    あるものは skip。focus_df が None（CSV 無し）のときは台帳だけで判定する。
    """
    ledger_keys = set(zip(ledger_df['source'], ledger_df['source_id'].astype(str))) \
        if not ledger_df.empty else set()

    starts_by_project: dict[str, list[pd.Timestamp]] = {}
    if focus_df is not None and not focus_df.empty:
        for name, start in zip(focus_df['project_name'], focus_df['start']):
            starts_by_project.setdefault(name, []).append(start)

    pending = []
    skipped = 0
    for interval in intervals:
        if (interval.source, interval.source_id) in ledger_keys \
                or _matches_existing(interval, starts_by_project):
            skipped += 1
        else:
            pending.append(interval)
    return pending, skipped


def build_payload(interval: Interval, project_map: dict[str, int],
                  tag_map: dict[str, int]) -> dict:
    """POST /time-entries のペイロードを組み立てる

    type: "activity" は必須（無いと 400）。タグは tag_ids でしか付かない。
    start は UTC の RFC3339 で秒未満を落とす（Health Connect 由来はミリ秒付きで届く）。
    """
    start = interval.start.replace(microsecond=0)
    stop = interval.stop.replace(microsecond=0)
    payload = {
        'type': 'activity',
        'description': interval.description,
        'start': focus.to_utc_str(start),
        'duration': int((stop - start).total_seconds()),
        'project_id': project_map[interval.project],
    }
    tag_ids = [tag_map[t] for t in interval.tags]
    if tag_ids:
        payload['tag_ids'] = tag_ids
    return payload


def _unresolved(interval: Interval, project_map: dict[str, int] | None,
                tag_map: dict[str, int]) -> list[str]:
    """引けないプロジェクト・タグの説明。空なら投入できる"""
    problems = []
    if project_map is not None and interval.project not in project_map:
        problems.append(f'プロジェクト {interval.project}')
    problems.extend(f'タグ {t}' for t in interval.tags if t not in tag_map)
    return problems


def _created_for_csv(created: dict, payload: dict, interval: Interval,
                     tag_map: dict[str, int]) -> dict:
    """作成応答を focus.build_dataframe に通せる形にする

    応答に project / tags / duration が含まれる保証が無いので、欠けていれば送った内容で補う。
    """
    entry = dict(created)
    entry.setdefault('start', payload['start'])
    if entry.get('duration') is None:
        entry['duration'] = payload['duration']
    entry.setdefault('description', payload['description'])
    entry.setdefault('type', 'activity')
    if not entry.get('project'):
        entry['project'] = {'id': payload['project_id'], 'name': interval.project}
    if not entry.get('tags'):
        entry['tags'] = [{'id': tag_map[t], 'name': t} for t in interval.tags]
    return entry


def push_intervals(
    intervals: list[Interval],
    ledger_df: pd.DataFrame,
    focus_df: pd.DataFrame | None,
    max_writes: int,
    dry_run: bool,
    workspace: focus.Workspace | None,
    out: IO[str],
    tag_map: dict[str, int] | None = None,
) -> dict:
    """投入対象を選び、上限内で書き込む

    途中で例外が起きても、それまでに投入した分は台帳と focus_entries.csv に必ず書く
    （1件ごとに積み、finally で書く。例外はそのまま外へ投げる）。
    プロジェクト・タグを引けない Interval は投入せず台帳にも入れない
    （引けないまま「投入済み」にすると後から直せないため）。dry_run では API を叩かない
    ので、プロジェクトの解決だけは行わない。

    Returns
    -------
    dict
        {'pending', 'skipped', 'pushed', 'carried_over', 'unresolved', 'before_cutover'}
    """
    tag_map = focus.load_tags() if tag_map is None else tag_map

    intervals, before_cutover = drop_before_cutover(intervals)
    if before_cutover:
        print(f'⚠️ {toggl_store.CUTOVER_DATE} より前の {before_cutover} 件は 2.0 へ migrate 済みなので投入しない',
              file=out)

    pending, skipped = select_pending(intervals, ledger_df, focus_df)

    project_map = None
    if not dry_run and pending:
        project_map = {name: pid for pid, name in focus.fetch_projects(workspace).items()}

    # 引けないものは上限の枠を取らせない（先頭に居座って後ろを塞がないように）
    unresolved = {}
    resolvable = []
    for interval in pending:
        problems = _unresolved(interval, project_map, tag_map)
        if problems:
            unresolved[(interval.source, interval.source_id)] = problems
        else:
            resolvable.append(interval)
    if unresolved:
        names = sorted({p for problems in unresolved.values() for p in problems})
        print(f"⚠️ 引けないため投入を見送る（{len(unresolved)}件）: {', '.join(names)}", file=out)

    pending = sorted(resolvable, key=lambda i: i.start)
    to_push = pending[:max_writes]
    carried_over = pending[max_writes:]
    result = {'pending': pending, 'skipped': skipped, 'pushed': 0, 'carried_over': carried_over,
              'unresolved': unresolved, 'before_cutover': before_cutover}

    if dry_run:
        result['to_push'] = to_push
        return result
    if not to_push:
        return result

    ledger_rows = []
    created_entries = []
    now_str = dt.datetime.now(load_timezone()).isoformat()

    try:
        for interval in to_push:
            payload = build_payload(interval, project_map, tag_map)
            created = focus.create_time_entry(workspace, payload)
            created_entries.append(_created_for_csv(created, payload, interval, tag_map))
            ledger_rows.append({
                'source': interval.source,
                'source_id': interval.source_id,
                'toggl_entry_id': str(created['id']),
                'start': interval.start.isoformat(),
                'pushed_at': now_str,
            })
            result['pushed'] += 1
    finally:
        # focus_entries.csv にも書く。ここを飛ばすと次の fetch-focus までの間、
        # 照合が効かず再投入しうる
        append_ledger(ledger_rows)
        if created_entries:
            df_created = focus.build_dataframe(created_entries,
                                               workspace_id=int(workspace.workspace_id))
            if not df_created.empty:
                focus.save_merged(df_created)

    return result
