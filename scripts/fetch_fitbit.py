#!/usr/bin/env python
# coding: utf-8
"""
Fitbit データ統一取得スクリプト

Usage:
    python scripts/fetch_fitbit.py --endpoint sleep --days 14
    python scripts/fetch_fitbit.py --endpoint hrv
    python scripts/fetch_fitbit.py --all
    python scripts/fetch_fitbit.py --all --overwrite
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse

from lib.clients import fitbit_api
from lib import fitbit_fetcher

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/fitbit_creds.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token.json'


def main():
    available_endpoints = fitbit_fetcher.list_endpoints()

    parser = argparse.ArgumentParser(
        description='Fitbitデータ取得',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"利用可能なエンドポイント: {', '.join(available_endpoints)}"
    )
    parser.add_argument(
        '--endpoint', '-e',
        choices=available_endpoints,
        help='取得するエンドポイント'
    )
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='全エンドポイントを取得'
    )
    parser.add_argument(
        '--days', '-d',
        type=int,
        default=14,
        help='取得日数（デフォルト: 14）'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='既存データを上書き（デフォルトは追記マージ）'
    )
    parser.add_argument(
        '--list',
        action='store_true',
        help='利用可能なエンドポイント一覧を表示'
    )
    args = parser.parse_args()

    if args.list:
        print("利用可能なエンドポイント:")
        for ep in available_endpoints:
            info = fitbit_fetcher.get_endpoint_info(ep)
            max_days = info.get('max_days')
            limit_str = f"最大{max_days}日" if max_days else "無制限"
            print(f"  {ep}: {info['description']} ({limit_str})")
        return

    if not args.endpoint and not args.all:
        parser.error("--endpoint または --all を指定してください")

    print("Fitbitクライアントを作成中...")
    client = fitbit_api.create_client(str(CREDS_FILE), str(TOKEN_FILE))

    if args.all:
        results = fitbit_fetcher.fetch_all(client, args.days, args.overwrite)
        print("\n=== 完了 ===")
        total = sum(r['records'] for r in results.values())
        print(f"総レコード数: {total}")
    else:
        result = fitbit_fetcher.fetch_endpoint(
            client, args.endpoint, args.days, args.overwrite
        )
        print(f"\n完了: {result['records']}件")


if __name__ == '__main__':
    main()
