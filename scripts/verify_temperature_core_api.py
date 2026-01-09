#!/usr/bin/env python
# coding: utf-8
"""
Core Temperature API バージョン検証スクリプト

API version 1.0 と 1.2 の両方を試して、どちらでデータが取得できるか確認する。

Usage:
    python scripts/verify_temperature_core_api.py --days 7
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


def test_api_version(client, start_date, end_date, api_version):
    """
    指定されたAPIバージョンでcore temperatureを取得してテスト

    Args:
        client: Fitbitクライアント
        start_date: 開始日
        end_date: 終了日
        api_version: APIバージョン（'1' または '1.2'）

    Returns:
        dict: テスト結果
    """
    print(f"\n{'='*60}")
    print(f"API Version {api_version} でテスト")
    print(f"{'='*60}")
    print(f"期間: {start_date} ~ {end_date}")

    try:
        response = fitbit_api.get_temperature_core_by_date_range(
            client, start_date, end_date, api_version=api_version
        )

        # レスポンスの構造を確認
        print(f"\n✓ API呼び出し成功")
        print(f"レスポンスキー: {list(response.keys())}")

        # データの有無を確認
        temp_core = response.get('tempCore', [])
        if temp_core:
            print(f"✓ データ取得成功: {len(temp_core)}件")
            print(f"\n最初のレコード:")
            print(json.dumps(temp_core[0], indent=2, ensure_ascii=False))

            # パース関数でも確認
            parsed = fitbit_api.parse_temperature_core(response)
            print(f"\nパース後: {len(parsed)}件")
            if parsed:
                print("最初のパース済みレコード:")
                print(json.dumps(parsed[0], indent=2, ensure_ascii=False, default=str))

            return {
                'version': api_version,
                'success': True,
                'count': len(temp_core),
                'sample': temp_core[0] if temp_core else None
            }
        else:
            print(f"⚠️  データなし（空の配列）")
            print(f"レスポンス全体:")
            print(json.dumps(response, indent=2, ensure_ascii=False))

            return {
                'version': api_version,
                'success': True,
                'count': 0,
                'sample': None
            }

    except Exception as e:
        print(f"✗ エラー発生")
        print(f"エラータイプ: {type(e).__name__}")
        print(f"エラーメッセージ: {str(e)}")

        # HTTPエラーの場合は詳細を表示
        if hasattr(e, 'status'):
            print(f"HTTPステータス: {e.status}")
        if hasattr(e, 'error_data'):
            print(f"エラー詳細:")
            print(json.dumps(e.error_data, indent=2, ensure_ascii=False))

        return {
            'version': api_version,
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }


def main():
    parser = argparse.ArgumentParser(
        description='Core Temperature API バージョン検証'
    )
    parser.add_argument(
        '--days', '-d',
        type=int,
        default=7,
        help='取得日数（デフォルト: 7）'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='開始日（YYYY-MM-DD形式）'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='終了日（YYYY-MM-DD形式）'
    )
    args = parser.parse_args()

    # 日付範囲の決定
    if args.start_date:
        start_date = dt.datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = dt.datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else dt.date.today()
    else:
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=args.days - 1)

    print("Core Temperature API バージョン検証")
    print("="*60)

    # Fitbitクライアント作成
    print("\nFitbitクライアントを作成中...")
    client, _ = fitbit_api.create_client_with_env(
        creds_file=str(CREDS_FILE) if CREDS_FILE.exists() else None,
        token_file=str(TOKEN_FILE) if TOKEN_FILE.exists() else None
    )

    # 両方のAPIバージョンでテスト
    results = []

    # API version 1.0
    result_v1 = test_api_version(client, start_date, end_date, '1')
    results.append(result_v1)

    # API version 1.2
    result_v12 = test_api_version(client, start_date, end_date, '1.2')
    results.append(result_v12)

    # 結果サマリー
    print(f"\n{'='*60}")
    print("検証結果サマリー")
    print(f"{'='*60}")

    for result in results:
        version = result['version']
        if result['success']:
            count = result.get('count', 0)
            status = f"✓ 成功 ({count}件)" if count > 0 else "⚠️  成功（データなし）"
        else:
            status = f"✗ 失敗 ({result.get('error_type', 'Unknown')})"

        print(f"API version {version}: {status}")

    # 推奨事項
    print(f"\n{'='*60}")
    print("推奨事項")
    print(f"{'='*60}")

    success_versions = [r for r in results if r['success'] and r.get('count', 0) > 0]

    if success_versions:
        best = success_versions[0]
        print(f"✓ API version {best['version']} でデータ取得可能です")
        print(f"  取得件数: {best['count']}件")
    else:
        print("⚠️  どちらのAPIバージョンでもデータが取得できませんでした")
        print("\n考えられる原因:")
        print("  1. デバイスがcore temperature記録に対応していない")
        print("  2. 手動で体温を記録していない（core temperatureは手動記録のみ）")
        print("  3. 期間内にデータが存在しない")
        print("\nヒント:")
        print("  - Fitbitアプリで体温を手動記録してから再度試してください")
        print("  - skin temperature（皮膚温）は自動記録されます")


if __name__ == '__main__':
    main()
