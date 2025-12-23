#!/usr/bin/env python3
"""Hevy トレーニングログ集計スクリプト

Usage:
    python aggregate_workout.py --daily          # 日次集計のみ
    python aggregate_workout.py --weekly         # 週次集計のみ（日次CSVが必要）
    python aggregate_workout.py --all            # 日次→週次を順次実行（デフォルト）
"""

import sys
import argparse
from pathlib import Path
import pandas as pd

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

from lib.hevy_csv import parse_hevy_csv
from lib.analytics.workout import calc_daily_stats, calc_weekly_stats_from_daily

# ファイルパス
INPUT_CSV = project_root / "data" / "hevy" / "workouts.csv"
DAILY_OUTPUT_CSV = project_root / "data" / "hevy" / "workouts_daily.csv"
WEEKLY_OUTPUT_CSV = project_root / "data" / "hevy" / "workouts_weekly.csv"


def aggregate_daily():
    """日次集計を実行"""
    print(f"入力ファイル: {INPUT_CSV}")
    print(f"出力ファイル: {DAILY_OUTPUT_CSV}")

    # Hevy CSVをパース
    df = parse_hevy_csv(INPUT_CSV)

    # 日次集計
    daily_df = calc_daily_stats(df)

    # CSV出力
    daily_df.to_csv(DAILY_OUTPUT_CSV, index=False)

    print(f"日次集計完了: {len(daily_df)}日分のデータを出力しました\n")
    return True


def aggregate_weekly():
    """週次集計を実行"""
    if not DAILY_OUTPUT_CSV.exists():
        print(f"エラー: {DAILY_OUTPUT_CSV} が存在しません")
        print("先に --daily または --all を実行してください")
        return False

    print(f"入力ファイル: {DAILY_OUTPUT_CSV}")
    print(f"出力ファイル: {WEEKLY_OUTPUT_CSV}")

    # 日次CSVを読み込み
    daily_df = pd.read_csv(DAILY_OUTPUT_CSV)

    # 週次集計
    weekly_df = calc_weekly_stats_from_daily(daily_df)

    # CSV出力
    weekly_df.to_csv(WEEKLY_OUTPUT_CSV, index=False)

    print(f"週次集計完了: {len(weekly_df)}週分のデータを出力しました\n")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Hevy トレーニングログ集計スクリプト',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --daily   # 日次集計のみ
  %(prog)s --weekly  # 週次集計のみ
  %(prog)s --all     # 日次→週次を順次実行（デフォルト）
        """
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--daily', action='store_true', help='日次集計のみ実行')
    group.add_argument('--weekly', action='store_true', help='週次集計のみ実行')
    group.add_argument('--all', action='store_true', help='日次→週次を順次実行（デフォルト）')

    args = parser.parse_args()

    # デフォルトは --all
    if not (args.daily or args.weekly or args.all):
        args.all = True

    # 実行
    if args.daily:
        return 0 if aggregate_daily() else 1
    elif args.weekly:
        return 0 if aggregate_weekly() else 1
    elif args.all:
        if not aggregate_daily():
            return 1
        if not aggregate_weekly():
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main())
