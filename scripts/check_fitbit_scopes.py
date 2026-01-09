#!/usr/bin/env python
# coding: utf-8
"""
Fitbit 認証スコープ確認スクリプト

現在のアクセストークンが持っているスコープを確認する。

Usage:
    python scripts/check_fitbit_scopes.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import json
from lib.clients import fitbit_api

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/fitbit_creds_dev.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token_dev.json'


def check_scopes():
    """現在のトークンのスコープを確認"""
    print("Fitbit 認証スコープ確認")
    print("="*60)

    # トークン情報を読み込み
    if not TOKEN_FILE.exists():
        print(f"✗ トークンファイルが見つかりません: {TOKEN_FILE}")
        return

    with open(TOKEN_FILE, 'r') as f:
        token_data = json.load(f)

    print("\nトークン情報:")
    print("-"*60)

    # スコープ情報
    if 'scope' in token_data:
        scopes = token_data['scope']
        if isinstance(scopes, str):
            scope_list = scopes.split()
        else:
            scope_list = scopes

        print(f"✓ 認証スコープ ({len(scope_list)}個):")
        for scope in sorted(scope_list):
            print(f"  - {scope}")

        # Temperature スコープのチェック
        print("\n必要なスコープのチェック:")
        print("-"*60)

        required_scopes = {
            'temperature': 'Temperature (Core/Skin) データ',
            'sleep': '睡眠データ',
            'heartrate': '心拍数・HRVデータ',
            'activity': 'アクティビティデータ',
            'nutrition': '栄養データ',
        }

        for scope, description in required_scopes.items():
            if scope in scope_list:
                print(f"  ✓ {scope}: {description}")
            else:
                print(f"  ✗ {scope}: {description} (未認証)")

        # Temperature スコープの詳細チェック
        if 'temperature' in scope_list:
            print("\n✓ Temperature スコープは認証済みです")
            print("  Core Temperature API の利用が可能です")
        else:
            print("\n✗ Temperature スコープが認証されていません")
            print("  Core/Skin Temperature API は利用できません")
            print("\n対処方法:")
            print("  1. Fitbit開発者ポータルでアプリのスコープ設定を確認")
            print("  2. 再認証して temperature スコープを追加")

    else:
        print("✗ スコープ情報がトークンに含まれていません")

    # その他のトークン情報
    print("\nその他のトークン情報:")
    print("-"*60)

    if 'user_id' in token_data:
        print(f"  User ID: {token_data['user_id']}")

    if 'expires_in' in token_data:
        print(f"  有効期限: {token_data['expires_in']}秒")

    if 'token_type' in token_data:
        print(f"  トークンタイプ: {token_data['token_type']}")


def test_temperature_access():
    """Temperature API へのアクセスをテスト"""
    print("\n" + "="*60)
    print("Temperature API アクセステスト")
    print("="*60)

    try:
        client, _ = fitbit_api.create_client_with_env(
            creds_file=str(CREDS_FILE) if CREDS_FILE.exists() else None,
            token_file=str(TOKEN_FILE) if TOKEN_FILE.exists() else None
        )

        import datetime as dt
        today = dt.date.today()
        yesterday = today - dt.timedelta(days=1)

        print(f"\nCore Temperature の取得テスト ({yesterday})...")
        try:
            response = fitbit_api.get_temperature_core_by_date_range(
                client, yesterday, today, api_version='1'
            )
            temp_core = response.get('tempCore', [])
            print(f"✓ API呼び出し成功: {len(temp_core)}件のデータ")

            if not temp_core:
                print("  ⚠️  データは空です（手動記録されていない可能性）")
        except Exception as e:
            error_msg = str(e)
            if 'insufficient_scope' in error_msg.lower() or '403' in error_msg:
                print(f"✗ スコープエラー: {error_msg}")
                print("  → temperature スコープが不足しています")
            else:
                print(f"✗ エラー: {error_msg}")

        print(f"\nSkin Temperature の取得テスト ({yesterday})...")
        try:
            response = fitbit_api.get_temperature_skin_by_date_range(
                client, yesterday, today
            )
            temp_skin = response.get('tempSkin', [])
            print(f"✓ API呼び出し成功: {len(temp_skin)}件のデータ")

            if not temp_skin:
                print("  ⚠️  データは空です（デバイスが対応していない可能性）")
        except Exception as e:
            error_msg = str(e)
            if 'insufficient_scope' in error_msg.lower() or '403' in error_msg:
                print(f"✗ スコープエラー: {error_msg}")
                print("  → temperature スコープが不足しています")
            else:
                print(f"✗ エラー: {error_msg}")

    except Exception as e:
        print(f"✗ クライアント作成エラー: {e}")


if __name__ == '__main__':
    check_scopes()
    test_temperature_access()
