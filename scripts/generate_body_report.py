#!/usr/bin/env python
# coding: utf-8
"""
体組成レポート生成スクリプト（日次・週次・月次）

Usage:
    python generate_body_report.py [--days <N>] [--week <N>] [--month <N>]
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

from lib.analytics import sleep, hrv, body, nutrition, activity

BASE_DIR = project_root
DATA_CSV = BASE_DIR / 'data/healthplanet_innerscan.csv'
SLEEP_MASTER_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
ACTIVITY_MASTER_CSV = BASE_DIR / 'data/fitbit/activity.csv'
ACTIVITY_LOGS_CSV = BASE_DIR / 'data/fitbit/activity_logs.csv'
HRV_MASTER_CSV = BASE_DIR / 'data/fitbit/hrv.csv'
HEART_RATE_MASTER_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'
NUTRITION_MASTER_CSV = BASE_DIR / 'data/fitbit/nutrition.csv'
ACTIVE_ZONE_CSV = BASE_DIR / 'data/fitbit/active_zone_minutes.csv'
CARDIO_SCORE_CSV = BASE_DIR / 'data/fitbit/cardio_score.csv'


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


def calc_activity_stats_for_period(start_date, end_date):
    """
    指定期間のアクティビティ統計を計算

    Parameters
    ----------
    start_date : str
        開始日（YYYY-MM-DD）
    end_date : str
        終了日（YYYY-MM-DD）

    Returns
    -------
    dict or None
        アクティビティ統計。データがない場合はNone
    """
    if not ACTIVITY_MASTER_CSV.exists():
        return None

    df_activity = pd.read_csv(ACTIVITY_MASTER_CSV)
    df_activity['date'] = pd.to_datetime(df_activity['date'])

    # 期間でフィルタ
    mask = (df_activity['date'] >= start_date) & (df_activity['date'] <= end_date)
    df_period = df_activity[mask]

    if len(df_period) == 0:
        return None

    # 統計を計算
    return {
        'days': len(df_period),
        'avg_calories_out': df_period['caloriesOut'].mean(),
        'total_calories_out': df_period['caloriesOut'].sum(),
        'avg_activity_calories': df_period['activityCalories'].mean(),
        'avg_steps': df_period['steps'].mean(),
        'total_steps': df_period['steps'].sum(),
        # 日別データ（歩数のみ）
        'daily': df_period[['date', 'caloriesOut', 'activityCalories', 'steps']].to_dict('records'),
    }


def calc_hrv_stats_for_period(start_date, end_date):
    """
    指定期間のHRV統計を計算（心拍数データも統合）

    Parameters
    ----------
    start_date : str
        開始日（YYYY-MM-DD）
    end_date : str
        終了日（YYYY-MM-DD）

    Returns
    -------
    dict or None
        HRV統計。データがない場合はNone
    """
    if not HRV_MASTER_CSV.exists():
        return None

    df_hrv = pd.read_csv(HRV_MASTER_CSV)
    df_hrv['date'] = pd.to_datetime(df_hrv['date'])
    df_hrv.set_index('date', inplace=True)

    # 期間でフィルタ
    mask = (df_hrv.index >= start_date) & (df_hrv.index <= end_date)
    df_hrv_period = df_hrv[mask]

    if len(df_hrv_period) == 0:
        return None

    # 心拍数データも読み込み（あれば）
    df_rhr_period = None
    if HEART_RATE_MASTER_CSV.exists():
        df_rhr = pd.read_csv(HEART_RATE_MASTER_CSV)
        df_rhr['date'] = pd.to_datetime(df_rhr['date'])
        df_rhr.set_index('date', inplace=True)

        mask = (df_rhr.index >= start_date) & (df_rhr.index <= end_date)
        df_rhr_period = df_rhr[mask]

    # ライブラリの関数を使用してHRV統計を計算
    return hrv.calc_hrv_stats_for_period(df_hrv_period, df_rhr_period)


def calc_nutrition_stats_for_period(start_date, end_date):
    """
    指定期間の栄養統計を計算

    Parameters
    ----------
    start_date : str
        開始日（YYYY-MM-DD）
    end_date : str
        終了日（YYYY-MM-DD）

    Returns
    -------
    dict or None
        栄養統計。データがない場合はNone
    """
    if not NUTRITION_MASTER_CSV.exists():
        return None

    df_nutrition = pd.read_csv(NUTRITION_MASTER_CSV)
    df_nutrition['date'] = pd.to_datetime(df_nutrition['date'])

    # 期間でフィルタ
    mask = (df_nutrition['date'] >= start_date) & (df_nutrition['date'] <= end_date)
    df_period = df_nutrition[mask]

    if len(df_period) == 0:
        return None

    # ライブラリの関数を使用して栄養統計を計算
    return nutrition.calc_nutrition_stats_for_period(df_period)


def calc_eat_stats_for_period(start_date, end_date):
    """
    指定期間のEAT（運動活動熱産生）統計を計算

    Parameters
    ----------
    start_date : str
        開始日（YYYY-MM-DD）
    end_date : str
        終了日（YYYY-MM-DD）

    Returns
    -------
    dict or None
        EAT統計。データがない場合はNone
    """
    if not ACTIVITY_LOGS_CSV.exists():
        return None

    df_activity_logs = pd.read_csv(ACTIVITY_LOGS_CSV)
    df_activity_logs['startTime'] = pd.to_datetime(df_activity_logs['startTime'], format='ISO8601')

    # 期間でフィルタ
    mask = (df_activity_logs['startTime'] >= start_date) & (df_activity_logs['startTime'] <= end_date)
    df_period = df_activity_logs[mask]

    if len(df_period) == 0:
        return None

    # ライブラリの関数を使用してEAT統計を計算
    return activity.calc_eat_stats_for_period(df_period)


def generate_report(output_dir, df, stats, sleep_stats=None, activity_stats=None, hrv_stats=None, nutrition_stats=None, eat_stats=None):
    """マークダウンレポートを生成"""
    report_path = output_dir / 'REPORT.md'

    # 日付範囲
    dates = pd.to_datetime(df['date'])
    start = dates.min().strftime('%Y-%m-%d')
    end = dates.max().strftime('%Y-%m-%d')
    start_date = dates.min()
    end_date = dates.max()

    # 睡眠DataFrameを読み込んで期間でフィルタ
    df_sleep_filtered = None
    if SLEEP_MASTER_CSV.exists():
        df_sleep_all = pd.read_csv(SLEEP_MASTER_CSV)
        df_sleep_all['dateOfSleep'] = pd.to_datetime(df_sleep_all['dateOfSleep'])
        mask = (df_sleep_all['dateOfSleep'] >= start_date) & (df_sleep_all['dateOfSleep'] <= end_date)
        df_sleep_filtered = df_sleep_all[mask]

    # 日別データに栄養・アクティビティ・睡眠データをマージ
    df_daily = body.merge_daily_data(df, nutrition_stats, activity_stats, df_sleep_filtered)

    # EATデータをマージ
    if eat_stats:
        df_daily = activity.merge_eat_to_daily(df_daily, eat_stats)

    # NEATを計算（activity_calories - EAT）
    df_daily = activity.calc_neat(df_daily)

    # TEFを計算（摂取カロリー × 0.1）
    df_daily = activity.calc_tef(df_daily)

    # 日別テーブル（body.format_daily_table()で生成）
    daily_table = body.format_daily_table(df_daily)

    # 回復セクション（睡眠・HRV・心拍数の日別テーブル）
    recovery_section = ""
    if df_sleep_filtered is not None or HRV_MASTER_CSV.exists():
        # HRVと心拍数データを事前に読み込み
        df_hrv_all = None
        if HRV_MASTER_CSV.exists():
            df_hrv_all = pd.read_csv(HRV_MASTER_CSV)
            df_hrv_all['date'] = pd.to_datetime(df_hrv_all['date'])

        df_hr_all = None
        if HEART_RATE_MASTER_CSV.exists():
            df_hr_all = pd.read_csv(HEART_RATE_MASTER_CSV)
            df_hr_all['date'] = pd.to_datetime(df_hr_all['date'])

        # 日別データの準備
        recovery_data = []

        # 期間の全日付を取得
        all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

        for date in all_dates:
            row = {'date': date.strftime('%m-%d')}

            # 睡眠データ
            if df_sleep_filtered is not None:
                sleep_day = df_sleep_filtered[df_sleep_filtered['dateOfSleep'] == date]
                if len(sleep_day) > 0:
                    row['sleep_hours'] = sleep_day['minutesAsleep'].iloc[0] / 60
                    row['deep_minutes'] = sleep_day['deepMinutes'].iloc[0] if 'deepMinutes' in sleep_day.columns else None
                    row['rem_minutes'] = sleep_day['remMinutes'].iloc[0] if 'remMinutes' in sleep_day.columns else None
                    row['efficiency'] = sleep_day['efficiency'].iloc[0] if 'efficiency' in sleep_day.columns else None
                else:
                    row['sleep_hours'] = None
                    row['deep_minutes'] = None
                    row['rem_minutes'] = None
                    row['efficiency'] = None
            else:
                row['sleep_hours'] = None
                row['deep_minutes'] = None
                row['rem_minutes'] = None
                row['efficiency'] = None

            # HRVデータ
            if df_hrv_all is not None:
                hrv_day = df_hrv_all[df_hrv_all['date'] == date]
                if len(hrv_day) > 0:
                    row['hrv'] = hrv_day['daily_rmssd'].iloc[0]
                else:
                    row['hrv'] = None
            else:
                row['hrv'] = None

            # 心拍数データ
            if df_hr_all is not None:
                hr_day = df_hr_all[df_hr_all['date'] == date]
                if len(hr_day) > 0:
                    row['hr'] = hr_day['resting_heart_rate'].iloc[0]
                else:
                    row['hr'] = None
            else:
                row['hr'] = None

            recovery_data.append(row)

        # テーブル生成
        recovery_rows = []
        for row in recovery_data:
            sleep_str = f"{row['sleep_hours']:.1f}" if row['sleep_hours'] is not None else "-"
            deep_str = f"{row['deep_minutes']:.0f}" if row['deep_minutes'] is not None else "-"
            hrv_str = f"{row['hrv']:.0f}" if row['hrv'] is not None else "-"
            hr_str = f"{row['hr']:.0f}" if row['hr'] is not None else "-"

            recovery_rows.append(
                f"| {row['date']} | {sleep_str} | {deep_str} | {hrv_str} | {hr_str} |"
            )

        recovery_table = '\n'.join(recovery_rows)

        recovery_section = f"""
---

## 🛌 回復

> 睡眠とHRVで回復状態を評価。HRV上昇 & HR低下 = 回復良好

| 日付 | 睡眠(h) | 深い(m) | HRV(ms) | HR(bpm) |
|------|---------|---------|---------|---------|
{recovery_table}
"""

    # 有酸素運動セクション
    aerobic_section = ""
    if activity_stats:
        # Active ZoneとVO2 Maxデータを事前に読み込み
        df_active_zone = None
        if ACTIVE_ZONE_CSV.exists():
            df_active_zone = pd.read_csv(ACTIVE_ZONE_CSV)
            df_active_zone['date'] = pd.to_datetime(df_active_zone['date'])

        df_vo2max = None
        if CARDIO_SCORE_CSV.exists():
            df_vo2max = pd.read_csv(CARDIO_SCORE_CSV)
            df_vo2max['date'] = pd.to_datetime(df_vo2max['date'])

        # 日別データの準備
        aerobic_data = []
        all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

        for date in all_dates:
            row = {'date': date.strftime('%m-%d')}

            # アクティビティデータ（歩数のみ）
            activity_day = [d for d in activity_stats['daily'] if pd.to_datetime(d['date']) == date]
            if activity_day:
                row['steps'] = activity_day[0]['steps']
            else:
                row['steps'] = None

            # Active Zoneデータ
            if df_active_zone is not None:
                zone_day = df_active_zone[df_active_zone['date'] == date]
                if len(zone_day) > 0:
                    row['active_zone'] = zone_day['activeZoneMinutes'].iloc[0]
                    row['fat_burn'] = zone_day['fatBurnActiveZoneMinutes'].iloc[0] if pd.notna(zone_day['fatBurnActiveZoneMinutes'].iloc[0]) else None
                    row['cardio'] = zone_day['cardioActiveZoneMinutes'].iloc[0] if pd.notna(zone_day['cardioActiveZoneMinutes'].iloc[0]) else None
                    row['peak'] = zone_day['peakActiveZoneMinutes'].iloc[0] if pd.notna(zone_day['peakActiveZoneMinutes'].iloc[0]) else None
                else:
                    row['active_zone'] = None
                    row['fat_burn'] = None
                    row['cardio'] = None
                    row['peak'] = None
            else:
                row['active_zone'] = None
                row['fat_burn'] = None
                row['cardio'] = None
                row['peak'] = None

            # VO2 Maxデータ
            if df_vo2max is not None:
                vo2max_day = df_vo2max[df_vo2max['date'] == date]
                if len(vo2max_day) > 0:
                    row['vo2max'] = vo2max_day['vo2_max'].iloc[0]
                else:
                    row['vo2max'] = None
            else:
                row['vo2max'] = None

            aerobic_data.append(row)

        # テーブル生成
        aerobic_rows = []
        for row in aerobic_data:
            steps_str = f"{row['steps']:,.0f}" if row['steps'] is not None else "-"
            zone_str = f"{row['active_zone']:.0f}" if row['active_zone'] is not None else "-"
            fat_burn_str = f"{row['fat_burn']:.0f}" if row['fat_burn'] is not None else "-"
            cardio_str = f"{row['cardio']:.0f}" if row['cardio'] is not None else "-"
            peak_str = f"{row['peak']:.0f}" if row['peak'] is not None else "-"
            vo2max_str = f"{row['vo2max']:.0f}" if row['vo2max'] is not None else "-"

            aerobic_rows.append(
                f"| {row['date']} | {steps_str} | {zone_str} | {fat_burn_str} | {cardio_str} | {peak_str} | {vo2max_str} |"
            )

        aerobic_table = '\n'.join(aerobic_rows)

        aerobic_section = f"""
#### 🏃 有酸素運動

> 歩数と活動強度の記録。Active Zoneは心拍数ベースの運動強度（週150分推奨）。
> Zone内訳: 脂肪燃焼（中程度）、有酸素（激しい）、ピーク（最高強度）

| 日付 | 歩数 | Zone合計 | 脂肪燃焼 | 有酸素 | ピーク | VO2 Max |
|------|------|----------|----------|--------|--------|---------|
{aerobic_table}
"""

    # 筋トレセクション
    strength_section = """
#### 💪 筋トレ

> トレーニングログは [Hevy](https://hevy.com/profile) を参照
"""

    # トレーニングセクション
    training_section = ""
    if aerobic_section:
        training_section = f"""
---

## 🏋️ トレーニング

{aerobic_section}{strength_section}
"""

    # 栄養セクション
    nutrition_section = ""
    if nutrition_stats:
        # 日別テーブル
        nutrition_rows = []
        for row in nutrition_stats['daily']:
            date_str = pd.to_datetime(row['date']).strftime('%m-%d')
            # カロリーが0の場合は「-」表示
            if row['p_pct'] is None:
                nutrition_rows.append(f"| {date_str} | - | - | - | - | - | - | - | - |")
            else:
                nutrition_rows.append(
                    f"| {date_str} | {row['calories']:,.0f} | {row['protein']:.1f} | "
                    f"{row['fat']:.1f} | {row['carbs']:.1f} | {row['fiber']:.1f} | "
                    f"{row['p_pct']:.0f} | {row['f_pct']:.0f} | {row['c_pct']:.0f} |"
                )
        nutrition_table = '\n'.join(nutrition_rows)

        nutrition_section = f"""
---

## 🍽️ 栄養

> PFCバランスとマクロ栄養素の記録。

| 日付 | カロリー | タンパク質 | 脂質 | 炭水化物 | 食物繊維 | P | F | C |
|------|----------|------------|------|----------|----------|---|---|---|
{nutrition_table}
"""

    # カロリー分析セクション
    calorie_analysis_section = ""
    if nutrition_stats or activity_stats or eat_stats:
        calorie_table = body.format_daily_table(df_daily, body.DAILY_CALORIE_ANALYSIS_COLUMNS)
        calorie_analysis_section = f"""
---

## 🔥 カロリー分析

> **TDEE（総消費エネルギー量）の内訳**: Out ≈ BMR + NEAT + TEF + EAT
>
> - **Balance**: カロリー収支（In - Out）
> - **In**: 摂取カロリー
> - **Out**: 消費カロリー（TDEE）
> - **BMR**: 基礎代謝
> - **NEAT**: 非運動性活動熱産生（日常活動による消費）
> - **TEF**: 食事誘発性熱産生（消化による消費、摂取カロリーの約10%）
> - **EAT**: 運動活動熱産生（意図的な運動による消費）

{calorie_table}
"""

    # 体組成セクション（パターンA + B）
    body_composition_section = body.format_body_composition_section(df)

    # 詳細データセクションの総合テーブル（水分率削除）
    detail_table = body.format_daily_table(
        df_daily, body.DAILY_BODY_COLUMNS,
        custom_labels={'calorie_balance': 'カロリー収支'}
    )

    report = f"""# 💪 筋トレデイリーレポート

**期間**: {start} 〜 {end}（{len(df)}日間）

---

## 📊 サマリー

| 指標 | 開始 | 終了 | 変化 |
|------|------|------|------|
| 体重 | {stats['weight']['first']:.2f}kg | {stats['weight']['last']:.2f}kg | **{body.format_change(stats['weight']['change'], 'kg')}** |
| 筋肉量 | {stats['muscle_mass']['first']:.2f}kg | {stats['muscle_mass']['last']:.2f}kg | **{body.format_change(stats['muscle_mass']['change'], 'kg')}** |
| 体脂肪率 | {stats['body_fat_rate']['first']:.1f}% | {stats['body_fat_rate']['last']:.1f}% | **{body.format_change(stats['body_fat_rate']['change'], '%')}** |
| FFMI | {stats['ffmi']['first']:.1f} | {stats['ffmi']['last']:.1f} | **{body.format_change(stats['ffmi']['change'], '')}** |

---

{body_composition_section}{training_section}{nutrition_section}{calorie_analysis_section}{recovery_section}
---

## 📈 詳細データ

### 📉 推移

![Body Composition](img/trend.png)

### 📋 日別総合データ

{detail_table}
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
    parser.add_argument('--month', type=str, default=None)
    parser.add_argument('--year', type=int, default=None)
    args = parser.parse_args()

    # Load data
    df = pd.read_csv(DATA_CSV, index_col='date', parse_dates=True)

    # Filter by week, month or days
    week = None
    month = None
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

    elif args.month:
        if args.month.lower() == 'current':
            now = datetime.now()
            month = now.month
            year = year or now.year
        else:
            month = int(args.month)
            year = year or datetime.now().year
        
        df = df[(df.index.month == month) & (df.index.year == year)]

    elif args.days:
        df = df.tail(args.days)

    if len(df) == 0:
        print("No data")
        return 1

    df = df.reset_index()
    print(f'Data: {len(df)} days')

    # 計算カラムを追加（LBM, FFMI）
    df = body.prepare_body_df(df)

    # Output directory
    if week:
        output_dir = BASE_DIR / f'reports/body/weekly/{year}-W{week:02d}'
    elif month:
        output_dir = BASE_DIR / f'reports/body/monthly/{year}-{month:02d}'
    else:
        output_dir = args.output

    img_dir = output_dir / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

    # Calculate stats
    stats = body.calc_body_stats(df)

    # Calculate sleep stats for the same period
    dates = pd.to_datetime(df['date'])
    start_date = dates.min().strftime('%Y-%m-%d')
    end_date = dates.max().strftime('%Y-%m-%d')
    sleep_stats = calc_sleep_stats_for_period(start_date, end_date)
    if sleep_stats:
        print(f'Sleep data: {sleep_stats["days"]} days')

    # Calculate activity stats for the same period
    activity_stats = calc_activity_stats_for_period(start_date, end_date)
    if activity_stats:
        print(f'Activity data: {activity_stats["days"]} days')

    # Calculate HRV stats for the same period
    hrv_stats = calc_hrv_stats_for_period(start_date, end_date)
    if hrv_stats:
        print(f'HRV data: {hrv_stats["days"]} days')

    # Calculate nutrition stats for the same period
    nutrition_stats = calc_nutrition_stats_for_period(start_date, end_date)
    if nutrition_stats:
        print(f'Nutrition data: {nutrition_stats["recorded_days"]}/{nutrition_stats["days"]} days')

    # Calculate EAT stats for the same period
    eat_stats = calc_eat_stats_for_period(start_date, end_date)
    if eat_stats:
        print(f'EAT data: {eat_stats["days"]} days, avg {eat_stats["avg_eat"]:.0f} kcal/day')

    # Generate chart
    plot_main_chart(df, img_dir / 'trend.png')

    # Generate report
    generate_report(output_dir, df, stats, sleep_stats, activity_stats, hrv_stats, nutrition_stats, eat_stats)

    return 0


if __name__ == '__main__':
    exit(main())
