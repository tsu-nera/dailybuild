#!/usr/bin/env python
# coding: utf-8
"""
気象データ取得スクリプト（Open-Meteo）

外気温・湿度・気圧を日次1行のCSVに保存する。
Open-Meteo は過去に遡って取得できるため、睡眠データのある全期間を後から埋められる。

Usage:
    python scripts/fetch_weather.py --days 14
    python scripts/fetch_weather.py --start-date 2025-01-01 --end-date 2026-08-12
    python scripts/fetch_weather.py --backfill      # 睡眠データのある全期間を埋める
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import logging

import pandas as pd

from lib.analytics.hr_zones import load_personal_config
from lib.clients.openmeteo_client import fetch_hourly
from lib.utils.sun_times import load_location_config
from lib.utils.weather import (
    DEFAULT_NIGHT_END_HOUR,
    DEFAULT_NIGHT_START_HOUR,
    aggregate_daily,
)
from lib.utils.private_data import ensure_dir

BASE_DIR = Path(__file__).parent.parent
CSV_FILE = BASE_DIR / 'data' / 'weather.csv'
SLEEP_CSV = BASE_DIR / 'data' / 'fitbit' / 'sleep.csv'


def resolve_backfill_start() -> dt.date:
    """睡眠データの最初の日を返す（バックフィルの起点）"""
    if not SLEEP_CSV.exists():
        raise FileNotFoundError(f"睡眠データが見つかりません: {SLEEP_CSV}")
    df = pd.read_csv(SLEEP_CSV, usecols=['dateOfSleep'])
    return pd.to_datetime(df['dateOfSleep']).min().date()


def resolve_period(args) -> tuple[dt.date, dt.date]:
    """引数から取得期間を決定"""
    end = dt.date.today()
    if args.backfill:
        return resolve_backfill_start(), end
    if args.start_date and args.end_date:
        return (dt.datetime.strptime(args.start_date, '%Y-%m-%d').date(),
                dt.datetime.strptime(args.end_date, '%Y-%m-%d').date())
    return end - dt.timedelta(days=args.days - 1), end


def main():
    parser = argparse.ArgumentParser(description='気象データ取得（Open-Meteo）')
    parser.add_argument('--days', '-d', type=int, default=14, help='取得日数（今日から遡る）')
    parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    parser.add_argument('--backfill', action='store_true',
                        help='睡眠データのある全期間を取得')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s')

    start, end = resolve_period(args)
    location = load_location_config()
    weather_cfg = load_personal_config().get('weather') or {}

    print(f"気象データ取得: {start} ～ {end} ({location['name']})")

    # 気圧変化量の初日を埋めるため1日前から取得する
    df_hourly = fetch_hourly(start - dt.timedelta(days=1), end, location)
    df_new = aggregate_daily(
        df_hourly,
        night_start_hour=weather_cfg.get('night_start_hour', DEFAULT_NIGHT_START_HOUR),
        night_end_hour=weather_cfg.get('night_end_hour', DEFAULT_NIGHT_END_HOUR),
    ).loc[str(start):str(end)]

    if CSV_FILE.exists():
        df_old = pd.read_csv(CSV_FILE, parse_dates=['date'], index_col='date')
        df_combined = pd.concat([df_old, df_new])
        df_combined = df_combined[~df_combined.index.duplicated(keep='last')].sort_index()
    else:
        df_combined = df_new

    ensure_dir(CSV_FILE.parent)
    df_combined.to_csv(CSV_FILE)
    print(f"保存完了: {CSV_FILE} ({len(df_combined)}行)")


if __name__ == '__main__':
    main()
