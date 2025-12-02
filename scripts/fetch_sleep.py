#!/usr/bin/env python
# coding: utf-8
"""
Fitbit 睡眠データ取得スクリプト
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import datetime as dt
import pandas as pd
from lib import fitbit_api

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/fitbit_creds.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token.json'
OUT_FILE = BASE_DIR / 'data/sleep_master.csv'
OUT_LEVELS_FILE = BASE_DIR / 'data/sleep_levels.csv'


def main():
    print("Fitbitクライアントを作成中...")
    client = fitbit_api.create_client(str(CREDS_FILE), str(TOKEN_FILE))

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=14)

    print(f"睡眠データを取得中... ({start_date} ~ {end_date})")

    response = fitbit_api.get_sleep_log_by_date_range(client, start_date, end_date)
    sleep_data = fitbit_api.parse_sleep(response)

    if not sleep_data:
        print("データがありません")
        return

    df = pd.DataFrame(sleep_data)
    df['dateOfSleep'] = pd.to_datetime(df['dateOfSleep'])
    df.set_index('dateOfSleep', inplace=True)
    df.sort_index(inplace=True)

    df.to_csv(OUT_FILE)
    print(f"サマリーデータを保存しました: {OUT_FILE}")
    print(f"取得件数: {len(df)}")

    # 詳細な睡眠ステージデータを保存
    levels_data = fitbit_api.parse_sleep_levels(response)
    if levels_data:
        df_levels = pd.DataFrame(levels_data)
        df_levels['dateTime'] = pd.to_datetime(df_levels['dateTime'])
        df_levels.sort_values(['dateOfSleep', 'dateTime'], inplace=True)
        df_levels.to_csv(OUT_LEVELS_FILE, index=False)
        print(f"詳細データを保存しました: {OUT_LEVELS_FILE}")
        print(f"詳細レコード数: {len(df_levels)}")


if __name__ == '__main__':
    main()
