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


def main():
    print("Fitbitクライアントを作成中...")
    client = fitbit_api.create_client(str(CREDS_FILE), str(TOKEN_FILE))

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=14)

    print(f"睡眠データを取得中... ({start_date} ~ {end_date})")
    sleep_data = []
    current_date = start_date

    while current_date <= end_date:
        sleep_log = client.sleep(date=current_date)
        row = fitbit_api.parse_sleep_log(sleep_log)
        if row:
            sleep_data.append(row)
        current_date += dt.timedelta(days=1)

    if not sleep_data:
        print("データがありません")
        return

    df = pd.DataFrame(sleep_data)
    df['dateOfSleep'] = pd.to_datetime(df['dateOfSleep'])
    df.set_index('dateOfSleep', inplace=True)

    df.to_csv(OUT_FILE)
    print(f"データを保存しました: {OUT_FILE}")
    print(f"取得件数: {len(df)}")
    print(df.tail())


if __name__ == '__main__':
    main()
