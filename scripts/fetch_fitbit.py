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
import json
import os

from lib.clients import fitbit_api
from lib import fitbit_fetcher

BASE_DIR = Path(__file__).parent.parent
# 開発用（ローカル実行時）
CREDS_FILE = BASE_DIR / 'config/fitbit_creds_dev.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token_dev.json'


def output_github_actions_token(updated_token):
    """GitHub Actions用にトークンを出力"""
    if updated_token['value'] and os.environ.get('GITHUB_OUTPUT'):
        token_json = json.dumps(updated_token['value'])
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"fitbit_token={token_json}\n")
        print("Fitbitトークンが更新されました（GitHub Actionsに出力）")


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
        default=2,
        help='取得日数（デフォルト: 2）'
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
    client, updated_token = fitbit_api.create_client_with_env(
        creds_file=str(CREDS_FILE) if CREDS_FILE.exists() else None,
        token_file=str(TOKEN_FILE) if TOKEN_FILE.exists() else None
    )

    # 環境変数またはファイルの判定メッセージ
    if os.environ.get('FITBIT_CREDS'):
        print("環境変数から認証情報を取得")
    else:
        print("ファイルから認証情報を取得")

    try:
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
    finally:
        # エラーが発生してもトークンが更新されていればGitHub Actionsに出力
        output_github_actions_token(updated_token)


if __name__ == '__main__':
    main()
