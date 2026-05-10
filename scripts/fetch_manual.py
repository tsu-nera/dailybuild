#!/usr/bin/env python
# coding: utf-8
"""
Google Sheets手動記録データ取得スクリプト
config/metrics_def.yaml の active=true なメトリクスのみ取得してCSVに保存
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import yaml
import pandas as pd
from lib.clients import gsheets_client
from lib.utils import csv_utils

BASE_DIR = Path(__file__).parent.parent
METRICS_DEF_FILE = BASE_DIR / 'config/metrics_def.yaml'
SPREADSHEET_ID = '1S0SwyRbM2cAATv_IOpkOspor-_Ov49rTygyTFr2gkwA'
SHEET_NAME = 'manual'
OUT_FILE = BASE_DIR / 'data/manual.csv'


def load_active_metrics():
    with open(METRICS_DEF_FILE) as f:
        defs = yaml.safe_load(f)
    return [d['metric'] for d in defs if d.get('active', False)]


def fetch_sheet():
    gc = gsheets_client.create_client()
    ss = gc.open_by_key(SPREADSHEET_ID)
    ws = ss.worksheet(SHEET_NAME)
    return pd.DataFrame(ws.get_all_records())


def normalize(df, active_metrics):
    df['date'] = pd.to_datetime(df['date'], format='%Y/%m/%d')
    df = df.replace('', pd.NA)

    cols = ['date'] + [m for m in active_metrics if m in df.columns]
    df = df[cols].dropna(subset=['date'])
    df = df.set_index('date').sort_index()
    return df


def main():
    print("メトリクス定義を読み込み中...")
    active_metrics = load_active_metrics()
    print(f"取り込み対象: {active_metrics}")

    print("Google Sheetsからデータ取得中...")
    df_raw = fetch_sheet()
    print(f"取得: {len(df_raw)}行")

    df = normalize(df_raw, active_metrics)

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df = csv_utils.merge_csv(df, OUT_FILE, 'date')
    df.to_csv(OUT_FILE)
    print(f"保存完了: {OUT_FILE} ({len(df)}件)")
    print(df.tail())


if __name__ == '__main__':
    main()
