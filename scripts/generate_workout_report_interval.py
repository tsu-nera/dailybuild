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
DATA_CSV = BASE_DIR / 'data/hevy/workouts.csv'


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


def format_value(value):
    """
    整数値をフォーマット（Reps/Sets用）

    Parameters
    ----------
    value : float
        値

    Returns
    -------
    str
        フォーマット済み文字列
    """
    if pd.isna(value):
        return "-"
    return str(int(value))


def format_diff(val):
    """
    整数の差分をフォーマット（Reps/Sets前週比用）

    Parameters
    ----------
    val : float
        変化量

    Returns
    -------
    str
        フォーマット済み変化量（プラスの場合は太字）
    """
    if pd.isna(val):
        return "-"
    if val == 0:
        return "±0"

    sign = '+' if val > 0 else ''
    formatted = f"{sign}{int(val)}"

    # プラスの変化は太字で強調
    if val > 0:
        return f"**{formatted}**"
    else:
        return formatted


def format_weights(min_weight, max_weight, is_bodyweight):
    """
    重量範囲をmin/max形式でフォーマット

    Parameters
    ----------
    min_weight : float
        最小重量
    max_weight : float
        最大重量
    is_bodyweight : bool
        自重エクササイズかどうか

    Returns
    -------
    str
        フォーマット済み文字列（例: "50/60 kg" or "-"）
    """
    if is_bodyweight or pd.isna(min_weight) or pd.isna(max_weight):
        return "-"

    # min == maxの場合は単一値表示
    if min_weight == max_weight:
        return f"{int(min_weight)} kg"
    else:
        return f"{int(min_weight)}/{int(max_weight)} kg"


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


def generate_weekly_stats_table(weekly_stats):
    """
    週次統計テーブルを生成（トレーニング全体のサマリー）

    行: 週（古い週→新しい週の順）
    列: count, time, reps, sets, volumes

    Parameters
    ----------
    weekly_stats : DataFrame
        週次統計CSV（iso_year, iso_week, training_days, duration_minutes, total_reps, total_sets, total_volume_kg）

    Returns
    -------
    list of str
        Markdown行のリスト
    """
    lines = []
    lines.append("## 📊 トレーニング統計")
    lines.append("")
    lines.append("| Week | Count | Time | Reps | Sets | Volumes |")
    lines.append("|---|---|---|---|---|---|")

    # 週ごとの行（古い週→新しい週）
    for _, row in weekly_stats.sort_values(['iso_year', 'iso_week']).iterrows():
        week_label = f"{row['iso_year']}-W{row['iso_week']:02d}"
        count = int(row['training_days'])
        time = int(row['duration_minutes'])
        reps = int(row['total_reps'])
        sets = int(row['total_sets'])
        volumes = int(row['total_volume_kg'])

        lines.append(f"| {week_label} | {count} | {time} | {reps} | {sets} | {volumes} |")

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
    lines.append("## 📈 トレーニングボリューム")
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


def generate_exercise_sections(weekly_volume, recent_weeks):
    """
    エクササイズごとセクション形式（Exercise Section View）を生成

    エクササイズごとにセクション分け（五十音順）
    各エクササイズの週次推移を表示（古い週→新しい週）

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
    lines.append("## 🏋️ エクササイズ別詳細")
    lines.append("")

    # 全エクササイズを五十音順で取得
    all_exercises = sorted(weekly_volume['exercise_jp'].unique())

    # エクササイズごとにセクション生成
    for exercise in all_exercises:
        lines.append(f"### {exercise}")
        lines.append("")
        lines.append("| 週 | Reps | Sets | Weights | Volume | 前週比 |")
        lines.append("|---|---|---|---|---|---|")

        # そのエクササイズのデータを抽出（古い週→新しい週）
        exercise_data = weekly_volume[
            weekly_volume['exercise_jp'] == exercise
        ].sort_values(['iso_year', 'iso_week'])

        for _, row in exercise_data.iterrows():
            week_label = f"{row['iso_year']}-W{row['iso_week']:02d}"
            reps_str = format_value(row['total_reps'])
            sets_str = format_value(row['total_sets'])
            weights_str = format_weights(row['min_weight'], row['max_weight'], row['is_bodyweight'])
            volume_str = format_volume(row['total_volume'], row['is_bodyweight'])
            volume_change = format_change(row['week_over_week_diff'], row['is_bodyweight'])

            lines.append(f"| {week_label} | {reps_str} | {sets_str} | {weights_str} | {volume_str} | {volume_change} |")

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

    # 週次統計CSVを読み込み
    weekly_stats_csv = BASE_DIR / 'data/hevy/workouts_weekly.csv'
    if not weekly_stats_csv.exists():
        print(f"Error: {weekly_stats_csv} not found")
        print("Run 'python scripts/generate_workout_report_weekly.py' first")
        return 1

    weekly_stats = pd.read_csv(weekly_stats_csv)

    # 直近N週間に絞る
    weekly_stats = weekly_stats.sort_values(['iso_year', 'iso_week']).tail(args.weeks)

    # 週次ボリューム（種目別詳細）を生成するため、生データも読み込む
    if not DATA_CSV.exists():
        print(f"Error: {DATA_CSV} not found")
        return 1

    # Hevy CSVを解析
    df = hevy_csv.parse_hevy_csv(DATA_CSV)

    # データ前処理
    df = workout.prepare_workout_df(df)

    # 週次ボリューム（種目別）を計算
    weekly_volume = workout.calc_weekly_volume(df)

    # 直近N週間でフィルタリング
    recent_weeks = weekly_stats[['iso_year', 'iso_week']].drop_duplicates()
    weekly_volume = weekly_volume.merge(
        recent_weeks,
        on=['iso_year', 'iso_week'],
        how='inner'
    )

    # レポート生成
    report_lines = []
    report_lines.append("# 💪 チョコザップ週次レポート")
    report_lines.append("")
    report_lines.append("週ごとのTraining Volume（重量×回数）の推移。")
    report_lines.append("")
    report_lines.append("**注記:**")
    report_lines.append("- 重量エクササイズ: kg単位（重量×回数の合計）")
    report_lines.append("- 自重エクササイズ: reps単位（回数の合計）")
    report_lines.append("")

    # トレーニング統計
    report_lines.extend(generate_weekly_stats_table(weekly_stats))
    report_lines.append("---")
    report_lines.append("")

    # 週次サマリー（マシンごと）
    report_lines.extend(generate_weekly_table(weekly_volume, recent_weeks))
    report_lines.append("---")
    report_lines.append("")

    # エクササイズ別詳細
    report_lines.extend(generate_exercise_sections(weekly_volume, recent_weeks))

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
