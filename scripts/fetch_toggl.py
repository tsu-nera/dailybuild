#!/usr/bin/env python
# coding: utf-8
"""
Toggl Track タイムエントリ取得スクリプト

Toggl Track API v9 からタイムエントリを取得し、JSTに変換してCSVに蓄積する。
計測中のエントリ（stop が None、または duration が負値）は除外する。

Usage:
    python scripts/fetch_toggl.py --days 7
    python scripts/fetch_toggl.py --start-date 2026-08-01 --end-date 2026-08-18
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import json

import pandas as pd

from lib.clients import toggl_client
from lib.utils import csv_utils

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config' / 'toggl_creds.json'
CSV_FILE = BASE_DIR / 'data' / 'toggl' / 'time_entries.csv'

JST = dt.timezone(dt.timedelta(hours=9))

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


def load_creds() -> dict:
    if not CREDS_FILE.exists():
        print(f"⚠️ 認証情報ファイルが見つかりません: {CREDS_FILE}")
        print("以下の形式で作成してください:")
        print('  { "api_token": "..." }')
        sys.exit(1)
    with open(CREDS_FILE, 'r') as f:
        return json.load(f)


def resolve_period(args) -> tuple[dt.date, dt.date]:
    """引数から取得期間を決定"""
    end = dt.date.today()
    if args.start_date and args.end_date:
        return (dt.datetime.strptime(args.start_date, '%Y-%m-%d').date(),
                dt.datetime.strptime(args.end_date, '%Y-%m-%d').date())
    return end - dt.timedelta(days=args.days - 1), end


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


def main():
    parser = argparse.ArgumentParser(description='Toggl Trackタイムエントリ取得')
    parser.add_argument('--days', type=int, default=7, help='取得日数（今日から遡る）')
    parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    args = parser.parse_args()

    creds = load_creds()

    start, end = resolve_period(args)
    print(f"Togglタイムエントリ取得: {start} ～ {end}")

    entries = toggl_client.fetch_time_entries(creds['api_token'], start, end)
    projects = toggl_client.fetch_projects(creds['api_token'])

    df_new = build_dataframe(entries, projects)

    if df_new.empty:
        print(f"⚠️ 期間 {start}〜{end} のタイムエントリが0件。"
              "Toggl側に記録が無いか、取得が壊れている可能性がある")
        return

    df_merged = csv_utils.merge_csv_by_columns(
        df_new, CSV_FILE, key_columns=['id'], sort_by=['start'],
    )

    df_merged = cast_int_columns(df_merged)

    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(CSV_FILE, index=False)

    period_min = df_merged['start'].min()
    period_max = df_merged['start'].max()
    print(f"取得件数: {len(df_new)}件")
    print(f"保存完了: {CSV_FILE} (総行数 {len(df_merged)}行)")
    print(f"CSVの期間: {period_min} ～ {period_max}")


if __name__ == '__main__':
    main()
