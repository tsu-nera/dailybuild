#!/usr/bin/env python3
"""Hevy トレーニングログを週次で集計してCSV出力するスクリプト"""

import sys
from pathlib import Path
import pandas as pd

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.lib.analytics.workout import calc_weekly_stats_from_daily


def main():
    input_csv = project_root / "data" / "hevy" / "workouts_daily.csv"
    output_csv = project_root / "data" / "hevy" / "workouts_weekly.csv"

    print(f"入力ファイル: {input_csv}")
    print(f"出力ファイル: {output_csv}")

    # 日次CSVを読み込み
    daily_df = pd.read_csv(input_csv)

    # 週次集計
    weekly_df = calc_weekly_stats_from_daily(daily_df)

    # CSV出力
    weekly_df.to_csv(output_csv, index=False)

    print(f"週次集計完了: {len(weekly_df)}週分のデータを出力しました")


if __name__ == "__main__":
    main()
