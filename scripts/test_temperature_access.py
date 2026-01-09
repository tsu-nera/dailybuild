#!/usr/bin/env python
# coding: utf-8
"""
Temperature API アクセステスト

skin temperatureとcore temperatureの両方をテストして、
どちらが取得できるか確認する。
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


def main():
    print("Temperature API アクセステスト")
    print("=" * 60)

    # 過去7日間のデータを取得
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=7)
    print(f"期間: {start_date} ~ {end_date}\n")

    # Fitbitクライアント作成
    print("Fitbitクライアントを作成中...")
    client, _ = fitbit_api.create_client_with_env(
        creds_file=str(CREDS_FILE) if CREDS_FILE.exists() else None,
        token_file=str(TOKEN_FILE) if TOKEN_FILE.exists() else None
    )

    # 1. Skin Temperature（自動記録）をテスト
    print("\n" + "=" * 60)
    print("1. Skin Temperature（自動記録）のテスト")
    print("=" * 60)

    try:
        skin_response = fitbit_api.get_temperature_skin_by_date_range(
            client, start_date, end_date
        )
        skin_data = fitbit_api.parse_temperature_skin(skin_response)

        print(f"✓ API呼び出し成功")
        print(f"取得件数: {len(skin_data)}件")

        if skin_data:
            print(f"\n最新のデータ:")
            print(json.dumps(skin_data[-1], indent=2, ensure_ascii=False))
        else:
            print("⚠️  データなし（デバイスが皮膚温測定に対応していない可能性）")

    except Exception as e:
        print(f"✗ エラー発生: {type(e).__name__}")
        print(f"メッセージ: {str(e)}")

    # 2. Core Temperature（手動記録）をテスト - API v1.0
    print("\n" + "=" * 60)
    print("2. Core Temperature（手動記録）のテスト - API v1.0")
    print("=" * 60)

    try:
        core_response = fitbit_api.get_temperature_core_by_date_range(
            client, start_date, end_date, api_version='1'
        )
        core_data = fitbit_api.parse_temperature_core(core_response)

        print(f"✓ API呼び出し成功")
        print(f"取得件数: {len(core_data)}件")

        if core_data:
            print(f"\n最新のデータ:")
            print(json.dumps(core_data[-1], indent=2, ensure_ascii=False, default=str))
        else:
            print("⚠️  データなし（手動で体温を記録していない可能性）")

    except Exception as e:
        print(f"✗ エラー発生: {type(e).__name__}")
        print(f"メッセージ: {str(e)}")

    # まとめ
    print("\n" + "=" * 60)
    print("まとめ")
    print("=" * 60)
    print("\nCore Temperatureは**手動記録のみ**です。")
    print("Fitbitアプリで以下の手順で体温を記録してください：")
    print("  1. Fitbitアプリを開く")
    print("  2. 「健康指標」タブを選択")
    print("  3. 「体温」を選択")
    print("  4. 「+」ボタンをタップして手動で体温を記録")
    print("\nSkin Temperatureは自動記録されます（対応デバイスのみ）。")


if __name__ == '__main__':
    main()
