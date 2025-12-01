#!/usr/bin/env python
# coding: utf-8
"""
HealthPlanet 体組成計データ取得スクリプト
非公式APIを使用して全データを取得
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import json
import pandas as pd
from lib import healthplanet_unofficial as hp

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/healthplanet_creds.json'
OUT_FILE = BASE_DIR / 'data/healthplanet_innerscan.csv'


def load_creds():
    with open(CREDS_FILE, 'r') as f:
        return json.load(f)


def main():
    creds = load_creds()

    print("HealthPlanetにログイン中...")
    session = hp.create_login_session(creds['login_id'], creds['password'])

    print("体組成計データを取得中...")
    records = hp.get_innerscan_data(session, days=90)

    if not records:
        print("データがありません")
        return

    df = pd.DataFrame.from_dict(records, orient='index')
    df.index = pd.to_datetime(df.index)
    df.index.name = 'date'
    df.sort_index(inplace=True)

    df.to_csv(OUT_FILE)
    print(f"データを保存しました: {OUT_FILE}")
    print(f"取得件数: {len(df)}")
    print(df.tail())


if __name__ == '__main__':
    main()
