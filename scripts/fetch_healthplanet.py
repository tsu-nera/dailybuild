#!/usr/bin/env python
# coding: utf-8
"""
HealthPlanet 体組成計・血圧計データ取得スクリプト
非公式APIを使用して全データを取得
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import json
import pandas as pd
from lib.clients import healthplanet_unofficial as hp
from lib.utils import csv_utils

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/healthplanet_creds.json'
OUT_FILE = BASE_DIR / 'data/healthplanet_innerscan.csv'
BP_OUT_FILE = BASE_DIR / 'data/healthplanet_bp.csv'


def load_creds():
    with open(CREDS_FILE, 'r') as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description='HealthPlanet体組成計データ取得')
    parser.add_argument('--overwrite', action='store_true', help='既存データを上書き（デフォルトは追記）')
    parser.add_argument('--days', type=int, default=60,
                        help='取得日数（90と365は粒度が変わるため使用不可）')
    args = parser.parse_args()

    creds = load_creds()

    print("HealthPlanetにログイン中...")
    session = hp.create_login_session(creds['login_id'], creds['password'])

    print("体組成計データを取得中...")
    save_records(hp.get_innerscan_data(session, days=args.days),
                 OUT_FILE, args.overwrite)

    print("血圧計データを取得中...")
    save_records(hp.get_blood_pressure_data(session, days=args.days),
                 BP_OUT_FILE, args.overwrite)


def save_records(records, out_file, overwrite):
    """{日付: {列: 値}} をCSVに保存（デフォルトは既存データへ追記）"""
    if not records:
        print("  データがありません")
        return

    df = pd.DataFrame.from_dict(records, orient='index')
    df.index = pd.to_datetime(df.index)
    df.index.name = 'date'
    df.sort_index(inplace=True)

    if not overwrite:
        df = csv_utils.merge_csv(df, out_file, 'date')

    df.to_csv(out_file)
    print(f"  保存しました: {out_file} ({len(df)}件)")
    print(df.tail(3))


if __name__ == '__main__':
    main()
