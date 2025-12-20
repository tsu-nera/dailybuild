#!/usr/bin/env python3
"""Hevy トレーニングログを日次で集計してCSV出力するスクリプト"""

import sys
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.lib.hevy_csv import parse_hevy_csv
from src.lib.analytics.workout import calc_daily_stats


def main():
    input_csv = project_root / "data" / "hevy" / "workouts.csv"
    output_csv = project_root / "data" / "hevy" / "workouts_daily.csv"

    print(f"入力ファイル: {input_csv}")
    print(f"出力ファイル: {output_csv}")

    # Hevy CSVをパース
    df = parse_hevy_csv(input_csv)

    # 日次集計
    daily_df = calc_daily_stats(df)

    # CSV出力
    daily_df.to_csv(output_csv, index=False)

    print(f"日次集計完了: {len(daily_df)}日分のデータを出力しました")


if __name__ == "__main__":
    main()
