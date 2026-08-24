"""
Toggl タイムエントリ CSV の読み書き

data/toggl/time_entries.csv（dailybuild-private への symlink）を対象に、
fetch 側のマージ保存と show 側の読み込みをまとめる。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from lib.utils import csv_utils
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'time_entries.csv')

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


def save_merged(df_new: pd.DataFrame) -> pd.DataFrame:
    """新規データを既存 CSV にマージして保存し、マージ後の DataFrame を返す"""
    df_merged = csv_utils.merge_csv_by_columns(
        df_new, CSV_FILE, key_columns=['id'], sort_by=['start'],
    )
    df_merged = cast_int_columns(df_merged)

    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(CSV_FILE, index=False)
    return df_merged


def load_entries() -> pd.DataFrame:
    """show 側の CSV 読み込み。project_name の欠損補完と日付列を付与する"""
    df = pd.read_csv(CSV_FILE, parse_dates=['start', 'stop'])
    df['project_name'] = df['project_name'].fillna(NO_PROJECT)
    # 日跨ぎエントリは開始日に全量を計上する（分割はしない）
    df['date'] = df['start'].dt.normalize()
    return df.sort_values('start')
