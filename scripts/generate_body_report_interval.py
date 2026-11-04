#!/usr/bin/env python
# coding: utf-8
"""
週次隔（Interval）集計レポート生成スクリプト
7日間ごとの平均値を算出し、前週比の変化を可視化する。

Usage:
    python generate_body_report_interval.py [--weeks <N>]
"""

import sys
import datetime
from pathlib import Path
import pandas as pd
import numpy as np

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.analytics import body

BASE_DIR = project_root
DATA_CSV = BASE_DIR / 'data/healthplanet_innerscan.csv'

# 目標と到達予測はレポートに出さない。体の目標・計画の正本は
# ~/repo/gtd/goals/strength.md で、ここは実測の推移だけを出す


def prepare_interval_report_data(weekly):
    """
    週次隔レポート用のコンテキストデータを準備

    Parameters
    ----------
    weekly : DataFrame
        週次集計データ（index: (iso_year, iso_week)）

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    from lib.templates.filters import format_change
    import datetime

    # 週次データを降順でソート（最新が上）
    weekly_desc = weekly.sort_index(ascending=False)

    # 週次データリストを構築
    weekly_data = []
    for (year, week), row in weekly_desc.iterrows():
        # 週の開始日（月曜）を計算
        try:
            d = str(year) + '-W' + str(week) + '-1'
            start_date_obj = datetime.datetime.strptime(d, "%G-W%V-%u")
            week_label = f"{year}-W{week:02d}"
        except:
            week_label = f"{year}-W{week:02d}"

        weekly_data.append({
            'week_label': week_label,
            'weight': f"{row['weight']:.2f}",
            # 増量期なので体重の増加を良い変化として扱う（方針の正本は gtd）
            'weight_diff': format_change(row['weight_diff'], ''),
            'muscle': f"{row['muscle_mass']:.2f}",
            'muscle_diff': format_change(row['muscle_diff'], ''),
            'fat_rate': f"{row['body_fat_rate']:.1f}%",
            'fat_diff': format_change(row['fat_rate_diff'], '%', positive_is_good=False),
            'ffmi': f"{row['ffmi']:.1f}",
            'ffmi_diff': format_change(row['ffmi_diff'], '')
        })

    context = {
        'report_title': '💪 筋トレ週次レポート',
        'description': '7日間平均値の推移。前週比でトレンドを確認。',
        'progress': {
            'progress_image': 'img/progress.png'
        },
        'weekly_data': weekly_data
    }

    return context


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Body Composition Interval Report')
    parser.add_argument('--weeks', type=int, default=8, help='Number of weeks to show')
    parser.add_argument('--output', type=Path, default=BASE_DIR / 'reports/body/interval/REPORT.md')
    args = parser.parse_args()

    # Load data
    if not DATA_CSV.exists():
        print(f"Error: {DATA_CSV} not found")
        return 1

    df = pd.read_csv(DATA_CSV, index_col='date', parse_dates=True)

    # 計算カラムを追加（LBM, FFMI）
    df = body.prepare_body_df(df)

    # ISO週番号でグルーピング（月曜始まり〜日曜終わり）
    # isocalendar() returns (year, week, day)
    df['iso_year'] = df.index.isocalendar().year
    df['iso_week'] = df.index.isocalendar().week
    
    # 週ごとの集計
    # 平均値をとるが、データ日数が少ない週（開始直後など）もそのまま平均する
    agg_funcs = {
        'weight': 'mean',
        'muscle_mass': 'mean',
        'body_fat_rate': 'mean',
        'lbm': 'mean',
        'ffmi': 'mean',
        'visceral_fat_level': 'mean',
        'iso_year': 'count' # 日数カウント用
    }

    weekly = df.groupby(['iso_year', 'iso_week']).agg(agg_funcs)
    weekly = weekly.rename(columns={'iso_year': 'days_count'})

    # 指標ごとの前週差分（Delta）を計算
    weekly['weight_diff'] = weekly['weight'].diff()
    weekly['muscle_diff'] = weekly['muscle_mass'].diff()
    weekly['fat_rate_diff'] = weekly['body_fat_rate'].diff()
    weekly['lbm_diff'] = weekly['lbm'].diff()
    weekly['ffmi_diff'] = weekly['ffmi'].diff()
    
    # 直近N週間に絞る
    weekly = weekly.tail(args.weeks)

    # 進捗グラフ生成
    img_dir = args.output.parent / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

    body.plot_progress_chart(weekly, save_path=img_dir / 'progress.png')

    # コンテキストデータ準備
    context = prepare_interval_report_data(weekly=weekly)

    # テンプレートレンダリング
    from lib.templates.renderer import BodyReportRenderer
    renderer = BodyReportRenderer()
    report_content = renderer.render_interval_report(context)

    # レポート出力
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f"Report generated: {output_path}")

if __name__ == "__main__":
    main()
