#!/usr/bin/env python
# coding: utf-8
"""
Fitbit Intraday データ取得スクリプト

心拍数と歩数のIntraday（1分間隔）データを取得する。
サーカディアンリズム分析用。

Usage:
    # 30日分を取得（デフォルト）
    python scripts/fetch_intraday.py

    # 7日分を取得
    python scripts/fetch_intraday.py --days 7

    # 90日分を取得（レート制限に注意）
    python scripts/fetch_intraday.py --days 90

    # 特定期間を指定
    python scripts/fetch_intraday.py --start-date 2025-12-01 --end-date 2025-12-31

    # 心拍数のみ取得
    python scripts/fetch_intraday.py --heart-rate-only

    # 歩数のみ取得
    python scripts/fetch_intraday.py --steps-only
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.lib import fitbit_fetcher
from src.lib.clients import fitbit_api


def main():
    parser = argparse.ArgumentParser(description='Fitbit Intradayデータ取得')

    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='取得日数（デフォルト: 30日）'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='開始日（YYYY-MM-DD形式、指定時は--daysを無視）'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='終了日（YYYY-MM-DD形式、未指定時は今日）'
    )
    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='既存データを上書き（デフォルト: マージ）'
    )
    parser.add_argument(
        '--heart-rate-only',
        action='store_true',
        help='心拍数Intradayのみ取得'
    )
    parser.add_argument(
        '--steps-only',
        action='store_true',
        help='歩数Intradayのみ取得'
    )

    args = parser.parse_args()

    # 日付範囲の決定
    start_date = None
    end_date = None

    if args.start_date:
        start_date = dt.datetime.strptime(args.start_date, '%Y-%m-%d').date()
        if args.end_date:
            end_date = dt.datetime.strptime(args.end_date, '%Y-%m-%d').date()
        else:
            end_date = dt.date.today()

        days = (end_date - start_date).days + 1
    else:
        days = args.days
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=days - 1)

    print("=" * 70)
    print("Fitbit Intraday データ取得")
    print("=" * 70)
    print(f"期間: {start_date} ~ {end_date} ({days}日)")
    print(f"モード: {'上書き' if args.overwrite else 'マージ'}")
    print()

    # レート制限の警告
    if days > 30:
        print("⚠️  注意: レート制限（150リクエスト/時間）")
        print(f"   {days}日分 = {days * 2}リクエスト（心拍数+歩数）")
        if days > 75:
            print("   2時間以上かかる可能性があります")
        print()

    # クライアント作成
    config_dir = Path(__file__).parent.parent / 'config'
    creds_file = config_dir / 'fitbit_creds_dev.json'
    token_file = config_dir / 'fitbit_token_dev.json'

    client = fitbit_api.create_client(str(creds_file), str(token_file))

    # エンドポイントの選択
    endpoints = []
    if not args.steps_only:
        endpoints.append('heart_rate_intraday')
    if not args.heart_rate_only:
        endpoints.append('steps_intraday')

    # データ取得
    results = {}
    errors = []

    for endpoint in endpoints:
        config = fitbit_fetcher.get_endpoint_info(endpoint)
        print(f"\n=== {config['description']} ===")

        result = fitbit_fetcher.fetch_endpoint(
            client, endpoint,
            days=None,  # start_date/end_dateを優先
            overwrite=args.overwrite,
            start_date=start_date,
            end_date=end_date
        )
        results[endpoint] = result

        if result.get('error'):
            errors.append(f"{endpoint}: {result['error']}")

    # 結果サマリー
    print("\n" + "=" * 70)
    print("取得結果サマリー")
    print("=" * 70)

    for endpoint, result in results.items():
        config = fitbit_fetcher.get_endpoint_info(endpoint)
        if result.get('error'):
            print(f"❌ {config['description']}: {result['error']}")
        elif result['records'] > 0:
            print(f"✅ {config['description']}: {result['records']:,}件")
            print(f"   {result['path']}")
        else:
            print(f"⚠️  {config['description']}: データなし")

    if errors:
        print(f"\n⚠️  {len(errors)}件のエラーが発生しました")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("\n✅ 完了")
    return 0


if __name__ == '__main__':
    sys.exit(main())
