#!/usr/bin/env python
# coding: utf-8
"""
Fitbit Intraday APIへのアクセステスト

Personal用途ではIntraday APIは自動的に利用可能だが、
実際にアクセスできるか確認する。
"""

import datetime as dt
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.lib.clients import fitbit_api


def test_intraday_access():
    """Intraday APIへのアクセステスト"""

    # クライアント作成
    config_dir = Path(__file__).parent.parent / 'config'
    creds_file = config_dir / 'fitbit_creds_dev.json'
    token_file = config_dir / 'fitbit_token_dev.json'

    if not creds_file.exists() or not token_file.exists():
        print("❌ 認証情報が見つかりません")
        print(f"  {creds_file} と {token_file} が必要です")
        return False

    print("=== Fitbit Intraday API アクセステスト ===\n")

    try:
        client = fitbit_api.create_client(str(creds_file), str(token_file))
        print("✅ Fitbitクライアント作成成功\n")
    except Exception as e:
        print(f"❌ クライアント作成失敗: {e}")
        return False

    # テスト日付（昨日）
    test_date = dt.date.today() - dt.timedelta(days=1)
    print(f"テスト日付: {test_date}\n")

    # 1. Heart Rate Intraday API テスト
    print("=" * 60)
    print("1. Heart Rate Intraday API テスト")
    print("=" * 60)

    try:
        print(f"取得中: /1/user/-/activities/heart/date/{test_date}/1d/1min.json")
        hr_data = fitbit_api.get_heart_rate_intraday(client, test_date, '1min')

        # データ確認
        intraday_data = hr_data.get('activities-heart-intraday', {})
        dataset = intraday_data.get('dataset', [])

        print(f"✅ Heart Rate Intraday API: アクセス可能")
        print(f"   データポイント数: {len(dataset)}")

        if dataset:
            print(f"   最初のデータ: {dataset[0]}")
            print(f"   最後のデータ: {dataset[-1]}")

            # Confidence値と加速度係数が含まれるか確認
            first_entry = dataset[0]
            has_confidence = 'confidence' in first_entry
            has_acceleration = 'acceleration' in first_entry or 'level' in first_entry

            print(f"\n   【重要】論文で必要なフィールド:")
            print(f"   - Confidence値: {'✅ あり' if has_confidence else '❌ なし'}")
            print(f"   - 加速度係数: {'✅ あり' if has_acceleration else '❌ なし'}")

            if not has_confidence and not has_acceleration:
                print(f"\n   ⚠️  基本的な心拍数データのみ取得可能")
                print(f"       論文で使用されているフィルタリング（Confidence=3、加速度≤4）は適用できません")
        else:
            print("   ⚠️  データがありません（デバイスを装着していなかった可能性）")

        print()

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Heart Rate Intraday API: アクセス不可")

        # エラーの詳細を分析
        if '403' in error_msg or 'Forbidden' in error_msg:
            print("   理由: HTTP 403 Forbidden")
            print("   対処: Personal用途でない、またはデバイスが対応していない可能性")
        elif '401' in error_msg or 'Unauthorized' in error_msg:
            print("   理由: HTTP 401 Unauthorized")
            print("   対処: 認証トークンの再取得が必要")
        elif '429' in error_msg or 'rate limit' in error_msg.lower():
            print("   理由: HTTP 429 Too Many Requests")
            print("   対処: レート制限に達しました。しばらく待ってから再試行")
        else:
            print(f"   エラー詳細: {error_msg}")

        print()
        return False

    # 2. Steps Intraday API テスト
    print("=" * 60)
    print("2. Steps Intraday API テスト")
    print("=" * 60)

    try:
        print(f"取得中: /1/user/-/activities/steps/date/{test_date}/1d/1min.json")
        steps_data = fitbit_api.get_steps_intraday(client, test_date, '1min')

        # データ確認
        intraday_data = steps_data.get('activities-steps-intraday', {})
        dataset = intraday_data.get('dataset', [])

        print(f"✅ Steps Intraday API: アクセス可能")
        print(f"   データポイント数: {len(dataset)}")

        if dataset:
            print(f"   最初のデータ: {dataset[0]}")
            print(f"   最後のデータ: {dataset[-1]}")
        else:
            print("   ⚠️  データがありません（デバイスを装着していなかった可能性）")

        print()

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Steps Intraday API: アクセス不可")
        print(f"   エラー詳細: {error_msg}")
        print()
        return False

    # 3. サマリー
    print("=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    print("✅ Intraday APIへのアクセス: 成功")
    print("✅ Heart Rate Intraday: 利用可能")
    print("✅ Steps Intraday: 利用可能")
    print()
    print("【次のステップ】")
    print("1. 30日分のデータを取得する")
    print("2. データ品質を確認する（欠損、外れ値など）")
    print("3. 論文の分析手法を実装する")
    print()

    return True


if __name__ == '__main__':
    success = test_intraday_access()
    sys.exit(0 if success else 1)
