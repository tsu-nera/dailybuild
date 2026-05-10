#!/usr/bin/env python
# coding: utf-8
"""
体組成レポート生成スクリプト（日次・週次・月次）

Usage:
    python generate_body_report_daily.py [--days <N>] [--week <N>] [--month <N>]
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

from lib.analytics import sleep, hrv, body, nutrition, activity, training
from lib.utils.report_args import add_common_report_args, parse_period_args, determine_output_dir, filter_dataframe_by_period

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


def _load_activity_logs_for_period(start_date, end_date):
    """activity_logs.csv を読み込み、期間でスライス"""
    if not ACTIVITY_LOGS_CSV.exists():
        return None
    df = pd.read_csv(ACTIVITY_LOGS_CSV)
    df['startTime'] = pd.to_datetime(df['startTime'], format='ISO8601', utc=True).dt.tz_convert('Asia/Tokyo').dt.tz_localize(None)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    mask = (df['startTime'] >= start) & (df['startTime'] < end)
    df_period = df[mask]
    return df_period if len(df_period) > 0 else None


def calc_cycling_stats_for_period(start_date, end_date):
    """指定期間のサイクリング統計を計算"""
    df_period = _load_activity_logs_for_period(start_date, end_date)
    if df_period is None:
        return None
    return activity.calc_cycling_stats_for_period(df_period)


def calc_strength_stats_for_period(start_date, end_date):
    """指定期間の筋トレ統計を計算"""
    df_period = _load_activity_logs_for_period(start_date, end_date)
    if df_period is None:
        return None
    return activity.calc_strength_stats_for_period(df_period)


def prepare_report_data(df, stats, sleep_stats=None, activity_stats=None,
                        hrv_stats=None, nutrition_stats=None, eat_stats=None):
    """
    テンプレートに渡すレポートコンテキストを準備

    Parameters
    ----------
    df : DataFrame
        体組成データ
    stats : dict
        体組成統計
    sleep_stats : dict, optional
        睡眠統計
    activity_stats : dict, optional
        アクティビティ統計
    hrv_stats : dict, optional
        HRV統計
    nutrition_stats : dict, optional
        栄養統計
    eat_stats : dict, optional
        EAT統計

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    dates = pd.to_datetime(df['date'])
    start_date = dates.min()
    end_date = dates.max()

    # 睡眠DataFrameを読み込んで期間でフィルタ
    df_sleep_filtered = None
    if SLEEP_MASTER_CSV.exists():
        df_sleep_all = pd.read_csv(SLEEP_MASTER_CSV)
        df_sleep_all['dateOfSleep'] = pd.to_datetime(df_sleep_all['dateOfSleep'])
        mask = (df_sleep_all['dateOfSleep'] >= start_date) & (df_sleep_all['dateOfSleep'] <= end_date)
        df_sleep_filtered = df_sleep_all[mask]

    # 日別データマージ
    df_daily = body.merge_daily_data(df, nutrition_stats, activity_stats, df_sleep_filtered)

    # EATデータをマージ
    if eat_stats:
        df_daily = activity.merge_eat_to_daily(df_daily, eat_stats)

    # NEATを計算
    df_daily = activity.calc_neat(df_daily)

    # TEFを計算
    df_daily = activity.calc_tef(df_daily)

    # サマリーメトリクスの準備
    summary_metrics = [
        {
            'label': '体重',
            'first': f"{stats['weight']['first']:.2f}kg",
            'last': f"{stats['weight']['last']:.2f}kg",
            'change': body.format_change(stats['weight']['change'], 'kg')
        },
        {
            'label': '筋肉量',
            'first': f"{stats['muscle_mass']['first']:.2f}kg",
            'last': f"{stats['muscle_mass']['last']:.2f}kg",
            'change': body.format_change(stats['muscle_mass']['change'], 'kg')
        },
        {
            'label': '体脂肪率',
            'first': f"{stats['body_fat_rate']['first']:.1f}%",
            'last': f"{stats['body_fat_rate']['last']:.1f}%",
            'change': body.format_change(stats['body_fat_rate']['change'], '%')
        },
        {
            'label': 'FFMI',
            'first': f"{stats['ffmi']['first']:.1f}",
            'last': f"{stats['ffmi']['last']:.1f}",
            'change': body.format_change(stats['ffmi']['change'], '')
        }
    ]

    # トレーニングセクションのデータ準備
    training_data = None
    aerobic_data = None
    cycling_data = None
    strength_data = None
    if activity_stats:
        training_data = {}
        # 有酸素運動データの準備
        aerobic_data = _prepare_aerobic_data(start_date, end_date, activity_stats)
    cycling_stats = calc_cycling_stats_for_period(start_date, end_date)
    strength_stats = calc_strength_stats_for_period(start_date, end_date)
    cycling_data = cycling_stats['daily'] if cycling_stats else None
    strength_data = strength_stats['daily'] if strength_stats else None

    # 栄養セクションのデータ準備
    nutrition_section_data = nutrition_stats if nutrition_stats else None

    # カロリー分析セクションのデータ準備
    calorie_analysis_data = None
    if nutrition_stats or activity_stats or eat_stats:
        calorie_analysis_data = {
            'table': body.format_daily_table(df_daily, body.DAILY_CALORIE_ANALYSIS_COLUMNS)
        }

    # 回復セクションのデータ準備
    recovery_data = _prepare_recovery_data(start_date, end_date, df_sleep_filtered, hrv_stats)

    # コンテキスト構築
    context = {
        'report_title': 'フィットネスデイリーレポート',
        'period': {
            'start': start_date.strftime('%Y-%m-%d'),
            'end': end_date.strftime('%Y-%m-%d'),
            'days': len(df)
        },
        'summary_metrics': summary_metrics,
        'body_composition_section': body.format_body_composition_section(df),
        'training_data': training_data,
        'aerobic_data': aerobic_data,
        'cycling_data': cycling_data,
        'strength_data': strength_data,
        'nutrition_data': nutrition_section_data,
        'calorie_analysis_data': calorie_analysis_data,
        'recovery_data': recovery_data,
        'detail_data': {
            'trend_image': 'img/trend.png',
            'daily_table': body.format_daily_table(
                df_daily,
                body.DAILY_BODY_COLUMNS,
                custom_labels={'calorie_balance': 'カロリー収支'}
            )
        }
    }

    return context


def _prepare_aerobic_data(start_date, end_date, activity_stats):
    """有酸素運動データを準備"""
    # Active ZoneとVO2 Maxデータを読み込み
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
        row = {'date': date}

        # アクティビティデータ（歩数）
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

    return aerobic_data


def _prepare_recovery_data(start_date, end_date, df_sleep_filtered, hrv_stats):
    """回復セクションのデータを準備"""
    if df_sleep_filtered is None and not HRV_MASTER_CSV.exists():
        return None

    # HRVと心拍数データを読み込み
    df_hrv_all = None
    if HRV_MASTER_CSV.exists():
        df_hrv_all = pd.read_csv(HRV_MASTER_CSV)
        df_hrv_all['date'] = pd.to_datetime(df_hrv_all['date'])
        df_hrv_all.set_index('date', inplace=True)

        # 7日移動統計を計算
        df_hrv_all = training.calc_hrv_7day_rolling_stats(df_hrv_all)

    df_hr_all = None
    if HEART_RATE_MASTER_CSV.exists():
        df_hr_all = pd.read_csv(HEART_RATE_MASTER_CSV)
        df_hr_all['date'] = pd.to_datetime(df_hr_all['date'])

    # 筋トレ判断データを準備
    training_readiness = None
    if df_hrv_all is not None:
        training_readiness = training.prepare_training_readiness_data(
            start_date, end_date, df_hrv_all, df_sleep_filtered
        )

    # 日別データの準備
    recovery_data = []
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

    for date in all_dates:
        row = {'date': date}

        # 睡眠データ
        if df_sleep_filtered is not None:
            sleep_day = df_sleep_filtered[df_sleep_filtered['dateOfSleep'] == date]
            if len(sleep_day) > 0:
                row['sleep_hours'] = sleep_day['minutesAsleep'].iloc[0] / 60
                row['deep_minutes'] = sleep_day['deepMinutes'].iloc[0] if 'deepMinutes' in sleep_day.columns else None
            else:
                row['sleep_hours'] = None
                row['deep_minutes'] = None
        else:
            row['sleep_hours'] = None
            row['deep_minutes'] = None

        # HRVデータ
        if df_hrv_all is not None and date in df_hrv_all.index:
            row['hrv'] = df_hrv_all.loc[date, 'daily_rmssd']
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

        # 筋トレ判断データを追加
        if training_readiness:
            training_day = next((t for t in training_readiness if t['date'] == date), None)
            if training_day:
                row['training_recommendation'] = training_day.get('recommendation', '-')
                row['training_intensity'] = training_day.get('intensity', 'unknown')
                row['training_reason'] = training_day.get('reason', '-')
                row['hrv_7day_mean'] = training_day.get('hrv_7day_mean')
                row['hrv_7day_lower'] = training_day.get('hrv_7day_lower')
                row['hrv_7day_upper'] = training_day.get('hrv_7day_upper')

        recovery_data.append(row)

    return recovery_data


def generate_report(output_dir, df, stats, sleep_stats=None, activity_stats=None, hrv_stats=None, nutrition_stats=None, eat_stats=None):
    """マークダウンレポートを生成（Jinja2テンプレート版）"""
    from lib.templates.renderer import BodyReportRenderer

    report_path = output_dir / 'REPORT.md'

    # データ準備
    context = prepare_report_data(df, stats, sleep_stats, activity_stats,
                                  hrv_stats, nutrition_stats, eat_stats)

    # テンプレートレンダリング
    renderer = BodyReportRenderer()
    report_content = renderer.render_daily_report(context)

    # ファイル出力
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f'Report: {report_path}')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Body Composition Report')
    add_common_report_args(parser, default_output=BASE_DIR / 'tmp/body_report', default_days=None)
    args = parser.parse_args()

    # Parse period arguments
    week, month, year = parse_period_args(args)

    # Load data
    df = pd.read_csv(DATA_CSV, index_col='date', parse_dates=True)

    # Filter by week, month or days
    df = filter_dataframe_by_period(
        df=df, date_column='date',
        week=week, month=month, year=year, days=args.days,
        is_index=True
    )

    if len(df) == 0:
        print("No data")
        return 1

    df = df.reset_index()
    print(f'Data: {len(df)} days')

    # 計算カラムを追加（LBM, FFMI）
    df = body.prepare_body_df(df)

    # Output directory
    output_dir = determine_output_dir(BASE_DIR, 'body', args.output, week, month, year)
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
