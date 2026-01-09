#!/usr/bin/env python
# coding: utf-8
"""
全温度関連データのデバッグスクリプト

Core/Skin Temperature の両方を確認し、生のAPIレスポンスを表示する。

Usage:
    python scripts/debug_all_temperature_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import datetime as dt
import json

from lib.clients import fitbit_api

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/fitbit_creds_dev.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token_dev.json'


def get_temperature_core_by_date(client, date):
    """単一日付で体温データを取得"""
    date_str = date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/temp/core/date/{date_str}.json"
    return client.make_request(url)


def debug_temperature_data():
    """全温度データをデバッグ表示"""
    print("="*60)
    print("Fitbit 温度データ デバッグ")
    print("="*60)

    # クライアント作成
    client, _ = fitbit_api.create_client_with_env(
        creds_file=str(CREDS_FILE) if CREDS_FILE.exists() else None,
        token_file=str(TOKEN_FILE) if TOKEN_FILE.exists() else None
    )

    today = dt.date.today()
    week_ago = today - dt.timedelta(days=7)

    # 1. Core Temperature - 単一日付（今日）
    print(f"\n{'='*60}")
    print(f"1. Core Temperature - 単一日付（今日: {today}）")
    print(f"{'='*60}")
    print(f"Endpoint: /1/user/-/temp/core/date/{today}.json")

    try:
        response = get_temperature_core_by_date(client, today)
        print(f"\n生レスポンス:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"✗ エラー: {e}")

    # 2. Core Temperature - 日付範囲（過去7日間）
    print(f"\n{'='*60}")
    print(f"2. Core Temperature - 日付範囲（{week_ago} ~ {today}）")
    print(f"{'='*60}")
    print(f"Endpoint: /1/user/-/temp/core/date/{week_ago}/{today}.json")

    try:
        response = fitbit_api.get_temperature_core_by_date_range(
            client, week_ago, today, api_version='1'
        )
        print(f"\n生レスポンス:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"✗ エラー: {e}")

    # 3. Skin Temperature - 日付範囲（過去7日間）
    print(f"\n{'='*60}")
    print(f"3. Skin Temperature - 日付範囲（{week_ago} ~ {today}）")
    print(f"{'='*60}")
    print(f"Endpoint: /1/user/-/temp/skin/date/{week_ago}/{today}.json")

    try:
        response = fitbit_api.get_temperature_skin_by_date_range(
            client, week_ago, today
        )
        print(f"\n生レスポンス:")
        print(json.dumps(response, indent=2, ensure_ascii=False))

        # 参考: パース後のデータ
        parsed = fitbit_api.parse_temperature_skin(response)
        if parsed:
            print(f"\nパース後のデータ（{len(parsed)}件）:")
            for entry in parsed:
                print(f"  {entry}")
    except Exception as e:
        print(f"✗ エラー: {e}")

    # 4. 過去30日間の Core Temperature（念のため）
    month_ago = today - dt.timedelta(days=30)
    print(f"\n{'='*60}")
    print(f"4. Core Temperature - 30日間（{month_ago} ~ {today}）")
    print(f"{'='*60}")

    try:
        response = fitbit_api.get_temperature_core_by_date_range(
            client, month_ago, today, api_version='1'
        )
        temp_core = response.get('tempCore', [])
        print(f"\nデータ件数: {len(temp_core)}")

        if temp_core:
            print(f"\n全データ:")
            print(json.dumps(temp_core, indent=2, ensure_ascii=False))
        else:
            print("データなし")
    except Exception as e:
        print(f"✗ エラー: {e}")

    # まとめ
    print(f"\n{'='*60}")
    print("診断")
    print(f"{'='*60}")
    print("\nCore Temperature（体温）が取得できない場合:")
    print("1. Fitbit Webダッシュボード (https://www.fitbit.com/) で")
    print("   体温データが表示されるか確認してください")
    print("2. アプリで記録した項目が「体温」であることを確認してください")
    print("   （「皮膚温」ではなく）")
    print("3. 記録後、デバイスと同期していることを確認してください")
    print("\nSkin Temperature（皮膚温）について:")
    print("- デバイスが自動測定（手動記録不要）")
    print("- 睡眠中のデータのみ")
    print("- 基準値からの相対値で表示（±0.5°Cなど）")


if __name__ == '__main__':
    debug_temperature_data()
