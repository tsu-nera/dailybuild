#!/usr/bin/env python
# coding: utf-8
"""
週次隔（Interval）集計レポート生成スクリプト
7日間ごとの平均値を算出し、前週比の変化を可視化する。

Usage:
    python generate_body_report_interval.py [--weeks <N>]
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.analytics import body

BASE_DIR = project_root
DATA_CSV = BASE_DIR / 'data/healthplanet_innerscan.csv'

def format_change(val, unit='', inverse=False):
    """変化量をフォーマット。inverse=Trueなら減少が良いこと（脂肪など）"""
    if pd.isna(val):
        return "-"
    if val == 0:
        return f"±0{unit}"
    
    sign = '+' if val > 0 else ''
    formatted = f"{sign}{val:.2f}{unit}"
    
    # 良い変化かどうかの判定（簡易的）
    # 通常: プラスが良い（筋肉など）
    # inverse: マイナスが良い（脂肪など）
    is_good = (val > 0 and not inverse) or (val < 0 and inverse)
    
    if is_good:
        return f"**{formatted}**" # Bold for good
    else:
        return formatted

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Body Composition Interval Report')
    parser.add_argument('--weeks', type=int, default=8, help='Number of weeks to show')
    parser.add_argument('--output', type=Path, default=BASE_DIR / 'reports/body/INTERVAL.md')
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
    
    # レポート生成
    report_lines = []
    report_lines.append(f"# 週次推移レポート（直近{len(weekly)}週間）")
    report_lines.append("")
    report_lines.append("7日間平均値の推移。前週比でトレンドを確認。")
    report_lines.append("")
    report_lines.append("| 週 (No.) | 日数 | 平均体重 (前週差) | 平均筋肉量 (前週差) | 平均体脂肪率 (前週差) | 平均LBM (前週差) | 平均FFMI (前週差) | 内臓脂肪 |")
    report_lines.append("|---|---|---|---|---|---|---|---|")
    
    # Sort descending for display? No, keep chronological usually, 
    # but for "latest first" logs, descending is better. Let's do descending (newest top).
    weekly_desc = weekly.sort_index(ascending=False)
    
    for (year, week), row in weekly_desc.iterrows():
        # 週の開始日（月曜）を計算して表示用にする
        # ISO週から日付への変換
        # 1-st day (Monday) of the iso_year and iso_week
        try:
            d = str(year) + '-W' + str(week) + '-1'
            start_date_obj = datetime.datetime.strptime(d, "%G-W%V-%u")
            week_label = start_date_obj.strftime('%m/%d~')
        except:
            # フォールバック
            import datetime
            # Python < 3.8 or specific formatting issues
            week_label = f"W{week}"

        
        weight_str = f"{row['weight']:.2f} ({format_change(row['weight_diff'], '', inverse=True)})"
        muscle_str = f"{row['muscle_mass']:.2f} ({format_change(row['muscle_diff'], '')})"
        fat_str = f"{row['body_fat_rate']:.1f}% ({format_change(row['fat_rate_diff'], '%', inverse=True)})"
        lbm_str = f"{row['lbm']:.2f} ({format_change(row['lbm_diff'], '')})"
        ffmi_str = f"{row['ffmi']:.1f} ({format_change(row['ffmi_diff'], '')})"

        report_lines.append(
            f"| **{year}-W{week:02d}** | {row['days_count']}日 | "
            f"{weight_str} | {muscle_str} | {fat_str} | "
            f"{lbm_str} | {ffmi_str} | {row['visceral_fat_level']:.1f} |"
        )

    output_path = args.output
    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report_lines))
        
    print(f"Report generated: {output_path}")
    
    # プレビューのため標準出力にも一部表示
    print("-" * 20)
    print('\n'.join(report_lines[:15])) # header + first few rows
    print("...")

if __name__ == "__main__":
    main()
