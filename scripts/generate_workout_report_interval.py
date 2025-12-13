#!/usr/bin/env python
# coding: utf-8
"""
ワークアウト週次ボリュームレポート生成スクリプト

週ごとのTraining Volume（重量×回数）の推移を集計し、前週比を可視化。

Usage:
    python generate_workout_report_interval.py [--weeks <N>] [--output <PATH>]
"""

import sys
from pathlib import Path
import datetime
import pandas as pd

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib import hevy_csv
from lib.analytics import workout

BASE_DIR = project_root
DATA_CSV = BASE_DIR / 'data/workouts.csv'


def format_volume(value, is_bodyweight):
    """
    Volumeを適切な単位でフォーマット

    Parameters
    ----------
    value : float
        Volume値
    is_bodyweight : bool
        自重エクササイズかどうか

    Returns
    -------
    str
        フォーマット済み文字列（例: "3150 kg" or "45 reps"）
    """
    if pd.isna(value):
        return "-"
    if is_bodyweight:
        return f"{int(value)} reps"
    else:
        return f"{int(value)} kg"


def format_volume_simple(value):
    """
    Volumeを単位なしでフォーマット（週次サマリー用）

    Parameters
    ----------
    value : float
        Volume値

    Returns
    -------
    str
        フォーマット済み文字列（例: "3150" or "45"）
    """
    if pd.isna(value):
        return "-"
    return str(int(value))


def format_change(val, is_bodyweight):
    """
    変化量をフォーマット（前週比）

    Parameters
    ----------
    val : float
        変化量
    is_bodyweight : bool
        自重エクササイズかどうか

    Returns
    -------
    str
        フォーマット済み変化量（プラスの場合は太字）
    """
    if pd.isna(val):
        return "-"
    if val == 0:
        unit = " reps" if is_bodyweight else " kg"
        return f"±0{unit}"

    sign = '+' if val > 0 else ''
    unit = " reps" if is_bodyweight else " kg"
    formatted = f"{sign}{int(val)}{unit}"

    # プラスの変化は太字で強調
    if val > 0:
        return f"**{formatted}**"
    else:
        return formatted


def calc_week_start_date(iso_year, iso_week):
    """
    ISO週番号から週の開始日（月曜日）を計算

    Parameters
    ----------
    iso_year : int
        ISO年
    iso_week : int
        ISO週番号

    Returns
    -------
    str
        開始日の文字列（MM/DD形式）
    """
    try:
        # ISO週から日付への変換（Python 3.8+）
        d = f"{iso_year}-W{iso_week:02d}-1"
        start_date_obj = datetime.datetime.strptime(d, "%G-W%V-%u")
        return start_date_obj.strftime('%m/%d')
    except Exception:
        # フォールバック
        return f"W{iso_week}"


def generate_weekly_stats_table(weekly_stats, recent_weeks):
    """
    週次統計テーブルを生成（トレーニング全体のサマリー）

    行: 週（古い週→新しい週の順）
    列: 日数、トレーニング（reps）、ボリューム、セット数

    Parameters
    ----------
    weekly_stats : DataFrame
        週次統計結果
    recent_weeks : DataFrame
        対象週のリスト

    Returns
    -------
    list of str
        Markdown行のリスト
    """
    lines = []
    lines.append("## トレーニング統計")
    lines.append("")
    lines.append("| 週 | 日数 | トレーニング (reps) | ボリューム (kg) | セット数 |")
    lines.append("|---|---|---|---|---|")

    # 週ごとの行（古い週→新しい週）
    for (year, week) in recent_weeks.sort_values(['iso_year', 'iso_week']).values:
        week_label = f"{year}-W{week:02d}"

        # その週のデータを取得
        week_data = weekly_stats[
            (weekly_stats['iso_year'] == year) &
            (weekly_stats['iso_week'] == week)
        ]

        if len(week_data) > 0:
            row = week_data.iloc[0]
            days = int(row['training_days'])
            reps = int(row['total_reps'])
            volume = int(row['total_volume'])
            sets = int(row['total_sets'])

            lines.append(f"| {week_label} | {days} | {reps} | {volume} | {sets} |")
        else:
            lines.append(f"| {week_label} | - | - | - | - |")

    lines.append("")
    return lines


def generate_weekly_table(weekly_volume, recent_weeks):
    """
    週次テーブル形式（Weekly Table View）を生成

    行: 週（古い週→新しい週の順）
    列: エクササイズ（アルファベット順）
    セル: training volume（単位付き）

    Parameters
    ----------
    weekly_volume : DataFrame
        週次集計結果
    recent_weeks : DataFrame
        対象週のリスト

    Returns
    -------
    list of str
        Markdown行のリスト
    """
    lines = []
    lines.append("## 週次サマリー")
    lines.append("")

    # 全エクササイズを五十音順で取得
    all_exercises = sorted(weekly_volume['exercise_jp'].unique())

    # ヘッダー行
    header = "| 週 |" + " | ".join(all_exercises) + " |"
    separator = "|---|" + "|".join(["---"] * len(all_exercises)) + "|"
    lines.append(header)
    lines.append(separator)

    # 週ごとの行（古い週→新しい週）
    for (year, week) in recent_weeks.sort_values(['iso_year', 'iso_week']).values:
        week_label = f"{year}-W{week:02d}"

        # その週のデータを取得
        week_data = weekly_volume[
            (weekly_volume['iso_year'] == year) &
            (weekly_volume['iso_week'] == week)
        ]

        # 各エクササイズのvolumeを取得
        row_values = [week_label]
        for exercise in all_exercises:
            exercise_data = week_data[week_data['exercise_jp'] == exercise]
            if len(exercise_data) > 0:
                vol = exercise_data.iloc[0]['total_volume']
                row_values.append(format_volume_simple(vol))
            else:
                row_values.append("-")

        lines.append("| " + " | ".join(row_values) + " |")

    lines.append("")
    return lines


def generate_week_sections(weekly_volume, recent_weeks):
    """
    週ごとセクション形式（Week Section View）を生成

    週ごとにセクション分け（新しい週が上）
    エクササイズをアルファベット順でソート

    Parameters
    ----------
    weekly_volume : DataFrame
        週次集計結果
    recent_weeks : DataFrame
        対象週のリスト

    Returns
    -------
    list of str
        Markdown行のリスト
    """
    lines = []
    lines.append("## 週ごと詳細")
    lines.append("")

    # 週ごとにセクション生成（新しい週が上）
    for (year, week) in recent_weeks.sort_values(['iso_year', 'iso_week'], ascending=False).values:
        lines.append(f"### {year}-W{week:02d}")
        lines.append("")
        lines.append("| エクササイズ | Volume | 前週比 |")
        lines.append("|---|---|---|")

        # その週のデータを抽出（五十音順）
        week_data = weekly_volume[
            (weekly_volume['iso_year'] == year) &
            (weekly_volume['iso_week'] == week)
        ].sort_values('exercise_jp')

        for _, row in week_data.iterrows():
            exercise = row['exercise_jp']
            volume_str = format_volume(row['total_volume'], row['is_bodyweight'])
            change_str = format_change(row['week_over_week_diff'], row['is_bodyweight'])

            lines.append(f"| {exercise} | {volume_str} | {change_str} |")

        lines.append("")

    return lines


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

    # データ読み込み
    if not DATA_CSV.exists():
        print(f"Error: {DATA_CSV} not found")
        return 1

    # Hevy CSVを解析
    df = hevy_csv.parse_hevy_csv(DATA_CSV)

    # データ前処理
    df = workout.prepare_workout_df(df)

    # 週次集計
    weekly_volume = workout.calc_weekly_volume(df)
    weekly_stats = workout.calc_weekly_stats(df)

    # 直近N週間に絞る
    unique_weeks = weekly_volume[['iso_year', 'iso_week']].drop_duplicates()
    unique_weeks = unique_weeks.sort_values(['iso_year', 'iso_week'])
    recent_weeks = unique_weeks.tail(args.weeks)

    # フィルタリング
    weekly_volume = weekly_volume.merge(
        recent_weeks,
        on=['iso_year', 'iso_week'],
        how='inner'
    )
    weekly_stats = weekly_stats.merge(
        recent_weeks,
        on=['iso_year', 'iso_week'],
        how='inner'
    )

    # レポート生成
    report_lines = []
    report_lines.append("# チョコザップ週次レポート")
    report_lines.append("")
    report_lines.append("週ごとのTraining Volume（重量×回数）の推移。")
    report_lines.append("")
    report_lines.append("**注記:**")
    report_lines.append("- 重量エクササイズ: kg単位（重量×回数の合計）")
    report_lines.append("- 自重エクササイズ: reps単位（回数の合計）")
    report_lines.append("")

    # トレーニング統計
    report_lines.extend(generate_weekly_stats_table(weekly_stats, recent_weeks))
    report_lines.append("---")
    report_lines.append("")

    # 週次サマリー（マシンごと）
    report_lines.extend(generate_weekly_table(weekly_volume, recent_weeks))
    report_lines.append("---")
    report_lines.append("")

    # 週ごと詳細
    report_lines.extend(generate_week_sections(weekly_volume, recent_weeks))

    # 出力
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))

    print(f"Report generated: {output_path}")

    # プレビュー表示
    print("-" * 40)
    print('\n'.join(report_lines[:25]))
    print("...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
