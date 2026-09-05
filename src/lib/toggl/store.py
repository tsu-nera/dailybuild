"""
Toggl タイムエントリ CSV の読み書き

data/toggl/time_entries.csv（dailybuild-private への symlink）を対象に、
fetch 側のマージ保存と show 側の読み込みをまとめる。
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from lib.utils import csv_utils
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'time_entries.csv')

# 直近の fetch がどの期間を取りに行ったかの記録。CSV は過去分が積み上がるだけで
# 「いつの期間を実際に取得したか」を持たないため、push の削除検出がこれを要る
# （詳細は push.select_pending）
FETCH_STATE_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'fetch_state.json')

# CSV は常に JST naive で持つ（表示・突合の都合）。取得窓の tz（push.load_timezone、
# 既定 Asia/Tokyo）とは別に固定で定義してあり、personal.yaml で timezone を変えても
# ここは追従しない。両者がズレると「取得した窓」と「CSV上の時刻」が食い違うので、
# 変える場合は client.fetch_time_entries に渡す tz とセットで検討すること（Issue #127）
JST = dt.timezone(dt.timedelta(hours=9))

NO_PROJECT = '(no project)'

CSV_COLUMNS = [
    'id', 'start', 'stop', 'duration_sec', 'description',
    'project_id', 'project_name', 'workspace_id', 'tags',
]

# project_id は未設定エントリがあると float 化して 1234.0 と出力されるため
# nullable な整数型に揃える
INT_COLUMNS = ['id', 'duration_sec', 'project_id', 'workspace_id']


def cast_int_columns(df: pd.DataFrame) -> pd.DataFrame:
    """整数列を nullable Int64 に揃える(CSV に .0 を残さない)"""
    for col in INT_COLUMNS:
        df[col] = df[col].astype('Int64')
    return df


def to_jst_naive_str(iso_str: str | None) -> str | None:
    """UTC ISO8601 文字列を JST の tz-naive 文字列に変換"""
    if iso_str is None:
        return None
    ts = pd.Timestamp(iso_str)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    ts_jst = ts.tz_convert(JST).tz_localize(None)
    return ts_jst.strftime('%Y-%m-%d %H:%M:%S')


def build_dataframe(entries: list[dict], projects: dict[int, str]) -> pd.DataFrame:
    """取得したタイムエントリを CSV 用 DataFrame に変換

    計測中のエントリ（duration が負値、または stop が None）は除外する。
    """
    rows = []
    for entry in entries:
        duration = entry.get('duration')
        stop = entry.get('stop')
        if stop is None or (duration is not None and duration < 0):
            continue

        project_id = entry.get('project_id')
        project_name = projects.get(project_id, '') if project_id is not None else ''
        tags = entry.get('tags') or []

        rows.append({
            'id': entry.get('id'),
            'start': to_jst_naive_str(entry.get('start')),
            'stop': to_jst_naive_str(stop),
            'duration_sec': duration,
            'description': entry.get('description') or '',
            'project_id': project_id,
            'project_name': project_name,
            'workspace_id': entry.get('workspace_id'),
            'tags': ','.join(tags),
        })

    return pd.DataFrame(rows, columns=CSV_COLUMNS)


def last_recorded_date() -> dt.date | None:
    """CSV に記録済みの最終エントリの開始日。CSV が無い・空なら None"""
    if not CSV_FILE.exists():
        return None
    df = pd.read_csv(CSV_FILE, usecols=['start'], parse_dates=['start'])
    if df.empty:
        return None
    return df['start'].max().date()


def drop_stale_rows_in_window(df_new: pd.DataFrame, window: tuple[dt.date, dt.date]) -> int:
    """fetch窓の中で、API レスポンスに無くなった行を CSV から削除する

    fetch した窓については CSV を正本にする（Issue #130）。push --since の
    過去日一括投入は fetch 窓に入らず恒久的に欠測扱いになっていた問題への対応で、
    削除検出（push.select_pending）が「CSV に無い＝手動削除された」を正しく
    再び意味を持つようにするための前段。

    安全弁（外すと欠測を捏造する）:
    - df_new が空なら何もしない（通信不調と「本当に0件」を区別できないため）
    - 削除対象は既存行の start が窓の内側にあるものだけ
      （JST の暦日 [start, end] 両端含む → start <= row.start < end+1日）。
      窓の外の行には一切触れない

    Returns
    -------
    int
        削除した行数
    """
    if df_new.empty:
        return 0
    if not CSV_FILE.exists():
        return 0

    df_old = pd.read_csv(CSV_FILE)
    if df_old.empty:
        return 0

    start, end = window
    lower = pd.Timestamp(start)
    upper = pd.Timestamp(end) + pd.Timedelta(days=1)
    old_start = pd.to_datetime(df_old['start'])
    in_window = (old_start >= lower) & (old_start < upper)

    new_ids = set(df_new['id'].astype(str))
    old_ids = df_old['id'].astype(str)
    stale = in_window & ~old_ids.isin(new_ids)

    removed = int(stale.sum())
    if removed:
        df_old = df_old[~stale]
        CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
        df_old.to_csv(CSV_FILE, index=False)
    return removed


def save_merged(df_new: pd.DataFrame, window: tuple[dt.date, dt.date] | None = None) -> pd.DataFrame:
    """新規データを既存 CSV にマージして保存し、マージ後の DataFrame を返す

    window を渡すと、その窓の中で df_new に無くなった既存行を先に削除してから
    マージする（drop_stale_rows_in_window 参照）。
    """
    if window is not None:
        removed = drop_stale_rows_in_window(df_new, window)
        if removed:
            print(f'Toggl 側で削除された {removed}件を CSV から除去', file=sys.stderr)

    df_merged = csv_utils.merge_csv_by_columns(
        df_new, CSV_FILE, key_columns=['id'], sort_by=['start'],
    )
    df_merged = cast_int_columns(df_merged)

    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(CSV_FILE, index=False)
    return df_merged


def save_fetch_window(start: dt.date, end: dt.date) -> None:
    """直近 fetch の対象期間を記録する（両端を含む日付）"""
    FETCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    FETCH_STATE_FILE.write_text(json.dumps({
        'start': start.isoformat(),
        'end': end.isoformat(),
        'fetched_at': dt.datetime.now(JST).isoformat(),
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_fetch_window() -> tuple[dt.date, dt.date] | None:
    """直近 fetch の対象期間。記録が無い/壊れていれば None"""
    if not FETCH_STATE_FILE.exists():
        return None
    try:
        state = json.loads(FETCH_STATE_FILE.read_text(encoding='utf-8'))
        return dt.date.fromisoformat(state['start']), dt.date.fromisoformat(state['end'])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def load_fetched_at() -> dt.datetime | None:
    """直近 fetch を実行した時刻。記録が無い/壊れていれば None

    push の削除検出で使う。この時刻より後に投入したエントリは、まだ一度も
    fetch していないので CSV に居なくて当たり前（削除された訳ではない）。
    """
    if not FETCH_STATE_FILE.exists():
        return None
    try:
        state = json.loads(FETCH_STATE_FILE.read_text(encoding='utf-8'))
        return dt.datetime.fromisoformat(state['fetched_at'])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def load_entries() -> pd.DataFrame:
    """show 側の CSV 読み込み。project_name の欠損補完と日付列を付与する"""
    df = pd.read_csv(CSV_FILE, parse_dates=['start', 'stop'])
    df['project_name'] = df['project_name'].fillna(NO_PROJECT)
    # 日跨ぎエントリは開始日に全量を計上する（分割はしない）
    df['date'] = df['start'].dt.normalize()
    return df.sort_values('start')
