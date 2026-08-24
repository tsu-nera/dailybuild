#!/usr/bin/env python
# coding: utf-8
"""
気分記録（Google Form）取得スクリプト
config/emotion_def.yaml で定義した回答シートを読み、イベント単位でCSVに保存
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import yaml
import pandas as pd
from lib.clients import gsheets_client
from lib.utils import csv_utils

from lib.utils.private_data import require_private_path
from lib.utils.private_data import ensure_dir

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/emotion_def.yaml'
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
OUT_FILE = require_private_path(BASE_DIR / 'data/emotion.csv')

TIMESTAMP_FORMAT = '%Y/%m/%d %H:%M:%S'


def load_def():
    with open(DEF_FILE) as f:
        return yaml.safe_load(f)


def fetch_sheet(conf):
    gc = gsheets_client.create_client()
    ss = gc.open_by_key(conf['spreadsheet_id'])
    ws = ss.worksheet(conf['sheet_name'])
    return pd.DataFrame(ws.get_all_records())


def split_emotions(value, known_labels):
    """複数選択の回答（カンマ区切り）を ; 区切りへ正規化"""
    if not value:
        return pd.NA

    labels = [s.strip() for s in str(value).split(',') if s.strip()]
    unknown = [s for s in labels if s not in known_labels]
    if unknown:
        print(f"警告: 定義にない選択肢 {unknown}（config/emotion_def.yaml の vocabulary と不一致）")

    return ';'.join(labels)


def normalize(df_raw, conf):
    missing = [c for c in conf['columns'] if c not in df_raw.columns]
    if missing:
        raise ValueError(
            f"回答シートに列がありません: {missing} / 実際の列: {list(df_raw.columns)}"
        )

    df = df_raw.rename(columns=conf['columns'])[list(conf['columns'].values())]

    df['timestamp'] = pd.to_datetime(df['timestamp'], format=TIMESTAMP_FORMAT)

    known_labels = {v['label'] for v in conf['vocabulary']}
    df['emotions'] = df['emotions'].apply(lambda v: split_emotions(v, known_labels))
    df['note'] = df['note'].replace('', pd.NA)

    # 日境界の補正はしない（深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.date

    df = df.dropna(subset=['timestamp'])
    return df[['timestamp', 'date', 'emotions', 'note']]


def main():
    conf = load_def()

    print(f"回答シート取得中: {conf['sheet_name']}")
    df_raw = fetch_sheet(conf)
    print(f"取得: {len(df_raw)}行")

    df = normalize(df_raw, conf)

    ensure_dir(OUT_FILE.parent)
    df = csv_utils.merge_csv_by_columns(
        df, OUT_FILE,
        key_columns=['timestamp'],
        parse_dates=['timestamp'],
        sort_by=['timestamp'],
    )
    df.to_csv(OUT_FILE, index=False)
    print(f"保存完了: {OUT_FILE} ({len(df)}件)")
    print(df.tail())


if __name__ == '__main__':
    main()
