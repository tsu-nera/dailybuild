#!/usr/bin/env python
# coding: utf-8
"""
ワークアウト週次ボリュームレポート生成スクリプト

週ごとのTraining Volume（重量×回数）の推移を集計し、前週比を可視化。

実行時に自動的に日次・週次統計CSVを生成してからレポートを作成します。

Usage:
    python generate_workout_report_interval.py [--weeks <N>] [--output <PATH>]
"""

import sys
from pathlib import Path
import pandas as pd

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib import hevy_csv
from lib.analytics import workout
from lib.templates.renderer import WorkoutReportRenderer
from lib.utils.private_data import ensure_dir

BASE_DIR = project_root
DATA_CSV = BASE_DIR / 'data/hevy/workouts.csv'


def prepare_workout_interval_report_data(weekly_stats, weekly_volume):
    """
    ワークアウト週次隔レポート用のコンテキストデータを準備

    Parameters
    ----------
    weekly_stats : DataFrame
        週次統計CSV（iso_year, iso_week, training_days, duration_minutes,
                      total_reps, total_sets, total_volume_kg）
    weekly_volume : DataFrame
        週次ボリューム（iso_year, iso_week, exercise_jp, total_volume,
                       total_reps, total_sets, min_weight, max_weight,
                       is_bodyweight, week_over_week_diff）

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    from lib.templates.filters import (
        format_volume, format_volume_change, format_weights
    )

    # 1. トレーニング統計（古い週→新しい週）
    training_stats = []
    for _, row in weekly_stats.sort_values(['iso_year', 'iso_week']).iterrows():
        week_label = f"{row['iso_year']}-W{row['iso_week']:02d}"
        training_stats.append({
            'week_label': week_label,
            'count': int(row['training_days']),
            'time': int(row['duration_minutes']),
            'reps': int(row['total_reps']),
            'sets': int(row['total_sets']),
            'volumes': int(row['total_volume_kg'])
        })

    # 2. 週次ボリューム表
    # 全エクササイズをアルファベット順で取得
    exercises = sorted(weekly_volume['exercise_jp'].unique())

    # 対象週のリストを取得
    recent_weeks = weekly_stats[['iso_year', 'iso_week']].sort_values(
        ['iso_year', 'iso_week']
    )

    weekly_volume_data = []
    for _, (year, week) in recent_weeks.iterrows():
        week_label = f"{year}-W{week:02d}"

        # その週のデータを取得
        week_data = weekly_volume[
            (weekly_volume['iso_year'] == year) &
            (weekly_volume['iso_week'] == week)
        ]

        # 各エクササイズのvolumeを取得
        volumes = []
        for exercise in exercises:
            exercise_data = week_data[week_data['exercise_jp'] == exercise]
            if len(exercise_data) > 0:
                vol = exercise_data.iloc[0]['total_volume']
                volumes.append(str(int(vol)) if pd.notna(vol) else "-")
            else:
                volumes.append("-")

        weekly_volume_data.append({
            'week_label': week_label,
            'volumes': volumes
        })

    # 3. エクササイズ別詳細
    exercise_details = []
    for exercise in exercises:
        # そのエクササイズのデータを抽出（古い週→新しい週）
        exercise_data = weekly_volume[
            weekly_volume['exercise_jp'] == exercise
        ].sort_values(['iso_year', 'iso_week'])

        weekly_data = []
        for _, row in exercise_data.iterrows():
            week_label = f"{row['iso_year']}-W{row['iso_week']:02d}"
            is_bw = row['is_bodyweight']

            weekly_data.append({
                'week_label': week_label,
                'reps': str(int(row['total_reps'])) if pd.notna(row['total_reps']) else "-",
                'sets': str(int(row['total_sets'])) if pd.notna(row['total_sets']) else "-",
                'weights': format_weights(row['min_weight'], row['max_weight'], is_bw),
                'volume': format_volume(row['total_volume'], is_bw),
                'volume_change': format_volume_change(row['week_over_week_diff'], is_bw)
            })

        exercise_details.append({
            'name': exercise,
            'weekly_data': weekly_data
        })

    # コンテキスト構築
    context = {
        'report_title': '💪 チョコザップ週次レポート',
        'description': '週ごとのTraining Volume（重量×回数）の推移。',
        'notes': (
            '**注記:**\n'
            '- 重量エクササイズ: kg単位（重量×回数の合計）\n'
            '- 自重エクササイズ: reps単位（回数の合計）'
        ),
        'training_stats': training_stats,
        'exercises': exercises,
        'weekly_volume': weekly_volume_data,
        'exercise_details': exercise_details
    }

    return context


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Workout Weekly Volume Interval Report'
    )
    parser.add_argument(
        '--weeks',
        type=int,
        default=8,
        help='Number of weeks to show (default: 8)'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=BASE_DIR / 'reports/workout/INTERVAL.md',
        help='Output file path'
    )
    args = parser.parse_args()

    # 生データから日次・週次統計を自動生成
    print("日次・週次統計を生成中...")
    if not DATA_CSV.exists():
        print(f"Error: {DATA_CSV} not found")
        return 1

    # Hevy CSVをパース
    df_raw = hevy_csv.parse_hevy_csv(DATA_CSV)

    # 日次統計を計算
    daily_stats = workout.calc_daily_stats(df_raw)

    # 日次統計CSVを保存
    daily_csv = BASE_DIR / 'data/hevy/workouts_daily.csv'
    daily_stats.to_csv(daily_csv, index=False)
    print(f"日次統計: {len(daily_stats)}日分を生成")

    # 週次統計を計算
    weekly_stats = workout.calc_weekly_stats_from_daily(daily_stats)

    # 週次統計CSVを保存
    weekly_stats_csv = BASE_DIR / 'data/hevy/workouts_weekly.csv'
    weekly_stats.to_csv(weekly_stats_csv, index=False)
    print(f"週次統計: {len(weekly_stats)}週分を生成\n")

    # 直近N週間に絞る
    weekly_stats = weekly_stats.sort_values(['iso_year', 'iso_week']).tail(args.weeks)

    # 週次ボリューム（種目別詳細）を計算するため、生データを前処理
    df = workout.prepare_workout_df(df_raw)

    # 週次ボリューム（種目別）を計算
    weekly_volume = workout.calc_weekly_volume(df)

    # 直近N週間でフィルタリング
    recent_weeks = weekly_stats[['iso_year', 'iso_week']].drop_duplicates()
    weekly_volume = weekly_volume.merge(
        recent_weeks,
        on=['iso_year', 'iso_week'],
        how='inner'
    )

    # コンテキストデータ準備
    context = prepare_workout_interval_report_data(
        weekly_stats=weekly_stats,
        weekly_volume=weekly_volume
    )

    # テンプレートレンダリング
    renderer = WorkoutReportRenderer()
    report_content = renderer.render_interval_report(context)

    # 出力
    output_path = args.output
    ensure_dir(output_path.parent)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"Report generated: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
