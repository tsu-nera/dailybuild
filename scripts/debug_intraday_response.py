#!/usr/bin/env python
# coding: utf-8
"""
Intraday APIレスポンス確認スクリプト
"""

import sys
import datetime as dt
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.lib.clients import fitbit_api

# クライアント作成
config_dir = Path(__file__).parent.parent / 'config'
creds_file = config_dir / 'fitbit_creds_dev.json'
token_file = config_dir / 'fitbit_token_dev.json'

client = fitbit_api.create_client(str(creds_file), str(token_file))

# テスト日付（1/3と1/6の両方）
test_dates = [
    dt.date(2026, 1, 3),
    dt.date(2026, 1, 6),
]

for test_date in test_dates:
    print("=" * 70)
    print(f"日付: {test_date}")
    print("=" * 70)

    try:
        response = fitbit_api.get_heart_rate_intraday(client, test_date, '1min')
        print(f"\nレスポンスキー: {list(response.keys())}")

        # Intradayデータ
        intraday_data = response.get('activities-heart-intraday', {})
        print(f"Intradayキー: {list(intraday_data.keys())}")

        dataset = intraday_data.get('dataset', [])
        print(f"データポイント数: {len(dataset)}")

        if dataset:
            print(f"最初のデータ: {dataset[0]}")
            print(f"最後のデータ: {dataset[-1]}")
        else:
            print("データセットが空です")
            print(f"レスポンス全体:\n{json.dumps(response, indent=2, ensure_ascii=False)}")

    except Exception as e:
        print(f"エラー: {e}")
        import traceback
        traceback.print_exc()

    print()
