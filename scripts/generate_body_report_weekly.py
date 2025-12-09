#!/usr/bin/env python
# coding: utf-8
"""
週次体組成レポート生成スクリプト

Usage:
    python generate_body_report_weekly.py [--days <N>] [--week <N>]
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib import sleep

BASE_DIR = project_root
DATA_CSV = BASE_DIR / 'data/healthplanet_innerscan.csv'
SLEEP_MASTER_CSV = BASE_DIR / 'data/sleep_master.csv'


def calc_stats(df):
    """主要指標の統計を計算"""
    df = df.copy()
    df['lbm'] = df['weight'] - df['body_fat_mass']

    stats = {}
    for col in ['weight', 'muscle_mass', 'body_fat_rate', 'lbm']:
        if col in df.columns:
            vals = df[col].dropna()
            if len(vals) >= 1:
                stats[col] = {
                    'first': vals.iloc[0],
                    'last': vals.iloc[-1],
                    'change': vals.iloc[-1] - vals.iloc[0] if len(vals) > 1 else 0,
                    'mean': vals.mean(),
                }
    return stats


def plot_main_chart(df, save_path):
    """体重・筋肉量・体脂肪率の統合グラフ"""
    df = df.copy()
    dates = [str(d)[-5:] for d in df['date']]

    fig, ax1 = plt.subplots(figsize=(10, 5))

    # Weight & Muscle (left axis, kg)
    ax1.plot(range(len(df)), df['weight'], 'o-', color='#3498DB',
             label='Weight', linewidth=2, markersize=6)
    ax1.plot(range(len(df)), df['muscle_mass'], 's-', color='#E74C3C',
             label='Muscle', linewidth=2, markersize=6)
    ax1.set_ylabel('kg')
    ax1.set_ylim(df[['weight', 'muscle_mass']].min().min() - 1,
                 df['weight'].max() + 1)

    # Body Fat % (right axis)
    ax2 = ax1.twinx()
    ax2.bar(range(len(df)), df['body_fat_rate'], alpha=0.3,
            color='#F39C12', label='Body Fat %', width=0.6)
    ax2.set_ylabel('Body Fat %')
    ax2.set_ylim(0, df['body_fat_rate'].max() + 5)

    ax1.set_xticks(range(len(df)))
    ax1.set_xticklabels(dates, rotation=45)
    ax1.set_title('Body Composition Trend')
    ax1.grid(axis='y', alpha=0.3)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def calc_sleep_stats_for_period(start_date, end_date):
    """
    指定期間の睡眠統計を計算

    Parameters
    ----------
    start_date : str
        開始日（YYYY-MM-DD）
    end_date : str
        終了日（YYYY-MM-DD）

    Returns
    -------
    dict or None
        睡眠統計。データがない場合はNone
    """
    if not SLEEP_MASTER_CSV.exists():
        return None

    df_sleep = pd.read_csv(SLEEP_MASTER_CSV)
    df_sleep['dateOfSleep'] = pd.to_datetime(df_sleep['dateOfSleep'])

    # 期間でフィルタ
    mask = (df_sleep['dateOfSleep'] >= start_date) & (df_sleep['dateOfSleep'] <= end_date)
    df_period = df_sleep[mask]

    if len(df_period) == 0:
        return None

    # ライブラリの関数を使用して回復スコアを計算
    return sleep.calc_recovery_score(df_period)


def format_change(val, unit='', positive_is_good=True):
    """変化量をフォーマット（良い/悪いの色付きマーク）"""
    if val == 0:
        return f"±0{unit}"
    sign = '+' if val > 0 else ''
    return f"{sign}{val:.2f}{unit}"


def generate_report(output_dir, df, stats, sleep_stats=None):
    """マークダウンレポートを生成"""
    report_path = output_dir / 'REPORT.md'

    # 日付範囲
    dates = pd.to_datetime(df['date'])
    start = dates.min().strftime('%Y-%m-%d')
    end = dates.max().strftime('%Y-%m-%d')

    # 日別テーブル
    daily_rows = []
    for _, row in df.iterrows():
        date_str = pd.to_datetime(row['date']).strftime('%m-%d')
        lbm = row['weight'] - row['body_fat_mass']
        daily_rows.append(
            f"| {date_str} | {row['weight']:.1f} | {row['muscle_mass']:.1f} | "
            f"{row['body_fat_rate']:.1f} | {row['body_fat_mass']:.2f} | {lbm:.1f} | "
            f"{row['visceral_fat_level']:.1f} | {row['basal_metabolic_rate']:.0f} | "
            f"{row['bone_mass']:.1f} | {row['body_age']:.0f} | "
            f"{row['body_water_rate']:.1f} | {row['muscle_quality_score']:.0f} |"
        )
    daily_table = '\n'.join(daily_rows)

    # 睡眠セクション
    sleep_section = ""
    if sleep_stats:
        # 回復スコアの評価
        score = sleep_stats['recovery_score']
        if score >= 90:
            score_eval = "優秀"
        elif score >= 75:
            score_eval = "良好"
        elif score >= 60:
            score_eval = "普通"
        else:
            score_eval = "要改善"

        sleep_section = f"""
---

## 睡眠と回復

> 筋肉の回復には質の良い睡眠が不可欠。深い睡眠中に成長ホルモンが分泌される。

### 回復スコア: **{score:.0f}/100** ({score_eval})

| 指標 | 値 | 推奨 |
|------|-----|------|
| 平均睡眠時間 | {sleep_stats['avg_sleep_hours']:.1f}時間 | 7-9時間 |
| 平均効率 | {sleep_stats['avg_efficiency']:.0f}% | 85%以上 |
| 深い睡眠 | {sleep_stats['avg_deep_minutes']:.0f}分 ({sleep_stats.get('deep_pct', 0):.0f}%) | 13-23% |
| レム睡眠 | {sleep_stats['avg_rem_minutes']:.0f}分 ({sleep_stats.get('rem_pct', 0):.0f}%) | 20-25% |

> 回復スコア = 深い睡眠(40%) + 効率(30%) + 時間(30%)
"""

    report = f"""# 週次体組成レポート

**期間**: {start} 〜 {end}（{len(df)}日間）

---

## サマリー

| 指標 | 開始 | 終了 | 変化 |
|------|------|------|------|
| 体重 | {stats['weight']['first']:.2f}kg | {stats['weight']['last']:.2f}kg | **{format_change(stats['weight']['change'], 'kg')}** |
| 筋肉量 | {stats['muscle_mass']['first']:.2f}kg | {stats['muscle_mass']['last']:.2f}kg | **{format_change(stats['muscle_mass']['change'], 'kg')}** |
| 体脂肪率 | {stats['body_fat_rate']['first']:.1f}% | {stats['body_fat_rate']['last']:.1f}% | **{format_change(stats['body_fat_rate']['change'], '%')}** |
| 除脂肪体重 | {stats['lbm']['first']:.2f}kg | {stats['lbm']['last']:.2f}kg | **{format_change(stats['lbm']['change'], 'kg')}** |

> 除脂肪体重 = 体重 − 体脂肪量
{sleep_section}
---

## 推移

![Body Composition](img/trend.png)

---

## 日別データ

| 日付 | 体重 | 筋肉量 | 体脂肪率 | 体脂肪量 | 除脂肪 | 内臓脂肪 | 基礎代謝 | 骨量 | 体内年齢 | 体水分率 | 筋質点数 |
|------|------|--------|----------|----------|--------|----------|----------|------|----------|----------|----------|
{daily_table}
"""

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f'Report: {report_path}')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Body Composition Report')
    parser.add_argument('--output', type=Path, default=BASE_DIR / 'tmp/body_report')
    parser.add_argument('--days', type=int, default=None)
    parser.add_argument('--week', type=str, default=None)
    parser.add_argument('--year', type=int, default=None)
    args = parser.parse_args()

    # Load data
    df = pd.read_csv(DATA_CSV, index_col='date', parse_dates=True)

    # Filter by week or days
    week = None
    year = args.year
    if args.week:
        if args.week.lower() == 'current':
            iso = datetime.now().isocalendar()
            week, year = iso[1], iso[0]
        else:
            week = int(args.week)
            year = year or datetime.now().year

        df['iso_week'] = df.index.isocalendar().week
        df['iso_year'] = df.index.isocalendar().year
        df = df[(df['iso_week'] == week) & (df['iso_year'] == year)]
        df = df.drop(columns=['iso_week', 'iso_year'])
    elif args.days:
        df = df.tail(args.days)

    if len(df) == 0:
        print("No data")
        return 1

    df = df.reset_index()
    print(f'Data: {len(df)} days')

    # Output directory
    if week:
        output_dir = BASE_DIR / f'reports/body/weekly/{year}-W{week:02d}'
    else:
        output_dir = args.output

    img_dir = output_dir / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

    # Calculate stats
    stats = calc_stats(df)

    # Calculate sleep stats for the same period
    dates = pd.to_datetime(df['date'])
    start_date = dates.min().strftime('%Y-%m-%d')
    end_date = dates.max().strftime('%Y-%m-%d')
    sleep_stats = calc_sleep_stats_for_period(start_date, end_date)
    if sleep_stats:
        print(f'Sleep data: {sleep_stats["days"]} days')

    # Generate chart
    plot_main_chart(df, img_dir / 'trend.png')

    # Generate report
    generate_report(output_dir, df, stats, sleep_stats)

    return 0


if __name__ == '__main__':
    exit(main())
