#!/usr/bin/env python
# coding: utf-8
"""
日出・日入データ取得スクリプト

Usage:
    python scripts/fetch_sun_times.py --days 14
    python scripts/fetch_sun_times.py --start-date 2026-01-01 --end-date 2026-01-31
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import pandas as pd

from lib.utils.sun_times import get_sun_times

BASE_DIR = Path(__file__).parent.parent
CSV_FILE = BASE_DIR / 'data' / 'sun_times.csv'


def fetch_sun_times(start_date: dt.date, end_date: dt.date) -> pd.DataFrame:
    """日出・日入データを取得"""
    data = []
    current = start_date
    while current <= end_date:
        sun = get_sun_times(current)
        data.append({
            'date': current.strftime('%Y-%m-%d'),
            'sunrise': sun['sunrise'],
            'sunset': sun['sunset'],
        })
        current += dt.timedelta(days=1)
    return pd.DataFrame(data)


def main():
    parser = argparse.ArgumentParser(description='日出・日入データ取得')
    parser.add_argument('--days', '-d', type=int, default=14, help='取得日数（今日から遡る）')
    parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    args = parser.parse_args()

    # 日付範囲を決定
    if args.start_date and args.end_date:
        start = dt.datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end = dt.datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        end = dt.date.today()
        start = end - dt.timedelta(days=args.days - 1)

    print(f"日出・日入データ取得: {start} ～ {end}")

    # 新規データ取得
    df_new = fetch_sun_times(start, end)

    # 既存データとマージ
    if CSV_FILE.exists():
        df_existing = pd.read_csv(CSV_FILE)
        df_combined = pd.concat([df_existing, df_new]).drop_duplicates(subset='date', keep='last')
        df_combined = df_combined.sort_values('date')
    else:
        df_combined = df_new

    # 保存
    CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_combined.to_csv(CSV_FILE, index=False)
    print(f"保存完了: {CSV_FILE} ({len(df_combined)}行)")


if __name__ == '__main__':
    main()
