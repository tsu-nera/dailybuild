#!/usr/bin/env python
# coding: utf-8
"""
Core Temperature 単一日付エンドポイントテスト

手動記録したデータが取得できるか確認する。

Usage:
    python scripts/test_temperature_core_single_date.py
    python scripts/test_temperature_core_single_date.py --date 2026-01-05
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import json

from lib.clients import fitbit_api

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/fitbit_creds_dev.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token_dev.json'


def get_temperature_core_by_date(client, date):
    """
    単一日付で体温データを取得（公式ドキュメント通り）

    Endpoint: /1/user/-/temp/core/date/{date}.json
    https://dev.fitbit.com/build/reference/web-api/temperature/get-temperature-core-summary-by-date
    """
    date_str = date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/temp/core/date/{date_str}.json"
    return client.make_request(url)


def test_single_date(client, test_date):
    """単一日付エンドポイントでテスト"""
    print(f"\n{'='*60}")
    print(f"単一日付エンドポイント: {test_date}")
    print(f"{'='*60}")

    try:
        response = get_temperature_core_by_date(client, test_date)

        print(f"✓ API呼び出し成功")
        print(f"\nレスポンス全体:")
        print(json.dumps(response, indent=2, ensure_ascii=False))

        temp_core = response.get('tempCore', [])
        if temp_core:
            print(f"\n✓ データ取得成功: {len(temp_core)}件")
            for i, entry in enumerate(temp_core, 1):
                print(f"\n記録 {i}:")
                print(f"  日時: {entry.get('dateTime')}")
                print(f"  体温: {entry.get('value')}°C")
            return True
        else:
            print(f"\n⚠️  データなし")
            return False

    except Exception as e:
        print(f"✗ エラー: {type(e).__name__}: {e}")
        if hasattr(e, 'error_data'):
            print(f"\n詳細:")
            print(json.dumps(e.error_data, indent=2, ensure_ascii=False))
        return False


def test_date_range(client, start_date, end_date):
    """日付範囲エンドポイントでテスト（現在の実装）"""
    print(f"\n{'='*60}")
    print(f"日付範囲エンドポイント: {start_date} ~ {end_date}")
    print(f"{'='*60}")

    try:
        response = fitbit_api.get_temperature_core_by_date_range(
            client, start_date, end_date, api_version='1'
        )

        print(f"✓ API呼び出し成功")
        print(f"\nレスポンス全体:")
        print(json.dumps(response, indent=2, ensure_ascii=False))

        temp_core = response.get('tempCore', [])
        if temp_core:
            print(f"\n✓ データ取得成功: {len(temp_core)}件")
            for i, entry in enumerate(temp_core, 1):
                print(f"\n記録 {i}:")
                print(f"  日時: {entry.get('dateTime')}")
                print(f"  体温: {entry.get('value')}°C")
            return True
        else:
            print(f"\n⚠️  データなし")
            return False

    except Exception as e:
        print(f"✗ エラー: {type(e).__name__}: {e}")
        if hasattr(e, 'error_data'):
            print(f"\n詳細:")
            print(json.dumps(e.error_data, indent=2, ensure_ascii=False))
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Core Temperature 単一日付エンドポイントテスト'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='テスト日付（YYYY-MM-DD形式、指定しない場合は今日と過去7日間）'
    )
    args = parser.parse_args()

    print("Core Temperature 取得テスト")
    print("="*60)
    print("\n手順:")
    print("1. Fitbitアプリで体温を手動記録してください")
    print("2. 数分待ってから、このスクリプトを実行してください")
    print("="*60)

    # Fitbitクライアント作成
    print("\nFitbitクライアントを作成中...")
    client, _ = fitbit_api.create_client_with_env(
        creds_file=str(CREDS_FILE) if CREDS_FILE.exists() else None,
        token_file=str(TOKEN_FILE) if TOKEN_FILE.exists() else None
    )

    if args.date:
        test_date = dt.datetime.strptime(args.date, '%Y-%m-%d').date()
        dates = [test_date]
    else:
        # 今日から過去7日間をテスト
        today = dt.date.today()
        dates = [today - dt.timedelta(days=i) for i in range(8)]

    print(f"\nテスト対象日付: {len(dates)}日間")

    found_data = False

    # 各日付で単一日付エンドポイントをテスト
    for test_date in dates:
        if test_single_date(client, test_date):
            found_data = True

    # 範囲エンドポイントでもテスト
    if dates:
        start_date = dates[-1]
        end_date = dates[0]
        print(f"\n{'='*60}")
        print("比較: 日付範囲エンドポイント")
        print(f"{'='*60}")
        test_date_range(client, start_date, end_date)

    # まとめ
    print(f"\n{'='*60}")
    print("まとめ")
    print(f"{'='*60}")

    if found_data:
        print("✓ データが取得できました")
    else:
        print("⚠️  データが取得できませんでした")
        print("\n考えられる原因:")
        print("1. 体温を手動記録していない")
        print("2. 記録後、Fitbitサーバーとの同期が完了していない")
        print("3. Fitbitアプリでデバイスと同期してください")
        print("4. 数分待ってから再度実行してください")
        print("\n手動記録の方法:")
        print("1. Fitbitアプリを開く")
        print("2. 「今日」タブ → 体温タイル（またはプロフィール → 体温）")
        print("3. 「+」ボタンで体温を記録")
        print("4. デバイスと同期")


if __name__ == '__main__':
    main()
