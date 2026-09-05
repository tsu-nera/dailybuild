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

from lib import exercise_source
from lib.analytics import sleep, hrv, body, nutrition, activity, training
from lib.analytics import hr_zones
from lib.analytics import zone2
from lib.utils.report_args import add_common_report_args, parse_period_args, determine_output_dir, filter_dataframe_by_period
from lib.utils.data_loader import determine_target_period
from lib.utils.private_data import ensure_dir

BASE_DIR = project_root
DATA_CSV = BASE_DIR / 'data/healthplanet_innerscan.csv'
SLEEP_MASTER_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
ACTIVITY_MASTER_CSV = BASE_DIR / 'data/fitbit/activity.csv'
HRV_MASTER_CSV = BASE_DIR / 'data/fitbit/hrv.csv'
HEART_RATE_MASTER_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'
HEART_RATE_INTRADAY_CSV = BASE_DIR / 'data/fitbit/heart_rate_intraday.csv'
NUTRITION_MASTER_CSV = BASE_DIR / 'data/fitbit/nutrition.csv'
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

    # active_minutes = lightly + fairly + very（3列とも欠測ならNaN。0埋めしない）
    active_minutes_cols = ['lightlyActiveMinutes', 'fairlyActiveMinutes', 'veryActiveMinutes']
    avg_active_minutes = df_period[active_minutes_cols].sum(axis=1, min_count=1).mean()

    # 統計を計算
    return {
        'days': len(df_period),
        'avg_calories_out': df_period['caloriesOut'].mean(),
        'total_calories_out': df_period['caloriesOut'].sum(),
        'avg_active_minutes': avg_active_minutes,
        'avg_steps': df_period['steps'].mean(),
        'total_steps': df_period['steps'].sum(),
        # 日別データ
        'daily': df_period[
            ['date', 'caloriesOut', 'steps'] + active_minutes_cols
        ].to_dict('records'),
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
    df_period = _load_exercise_sessions_for_period(start_date, end_date)
    if df_period is None:
        return None

    # ライブラリの関数を使用してEAT統計を計算
    return activity.calc_eat_stats_for_period(df_period)


def _load_exercise_sessions_for_period(start_date, end_date):
    """exercise.csv を読み込み、期間でスライス（platform 重複解決済み）"""
    start = pd.Timestamp(start_date).date()
    end = pd.Timestamp(end_date).date()
    return exercise_source.load_sessions(start, end)


def calc_cycling_stats_for_period(start_date, end_date):
    """指定期間のサイクリング統計を計算"""
    df_period = _load_exercise_sessions_for_period(start_date, end_date)
    if df_period is None:
        return None
    return activity.calc_cycling_stats_for_period(df_period)


def calc_strength_stats_for_period(start_date, end_date):
    """指定期間の筋トレ統計を計算"""
    df_period = _load_exercise_sessions_for_period(start_date, end_date)
    if df_period is None:
        return None
    return activity.calc_strength_stats_for_period(df_period)


def prepare_report_data(df, stats, sleep_stats=None, activity_stats=None,
                        hrv_stats=None, nutrition_stats=None, eat_stats=None,
                        target_end=None):
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
    target_end : pd.Timestamp, optional
        レポート引数の終了日（今日など）。hr_zones の RHR 計算基準日として使う。
        healthplanet 最終測定日（= dates.max()）でなく必ずこちらを渡すこと。

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

    # TEFを計算
    df_daily = activity.calc_tef(df_daily)

    # サマリーメトリクスの準備
    summary_metrics = [
        {
            'label': '体重',
            'n': stats['weight']['n'],
            'first': f"{stats['weight']['first']:.2f}kg",
            'last': f"{stats['weight']['last']:.2f}kg",
            'change': body.format_change(stats['weight']['change'], 'kg')
        },
        {
            'label': '筋肉量',
            'n': stats['muscle_mass']['n'],
            'first': f"{stats['muscle_mass']['first']:.2f}kg",
            'last': f"{stats['muscle_mass']['last']:.2f}kg",
            'change': body.format_change(stats['muscle_mass']['change'], 'kg')
        },
        {
            'label': '体脂肪率',
            'n': stats['body_fat_rate']['n'],
            'first': f"{stats['body_fat_rate']['first']:.1f}%",
            'last': f"{stats['body_fat_rate']['last']:.1f}%",
            'change': body.format_change(stats['body_fat_rate']['change'], '%', positive_is_good=False)
        },
        {
            'label': 'FFMI',
            'n': stats['ffmi']['n'],
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
        # 有酸素運動データの準備（ref_date=target_end で RHR 基準日を統一）
        aerobic_data = _prepare_aerobic_data(start_date, end_date, activity_stats, ref_date=target_end)
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

    # hr_zone_meta を取得（_prepare_aerobic_data 実行後にセットされる）
    hr_zone_meta = getattr(_prepare_aerobic_data, 'hr_zone_meta', None)
    zone2_meta = getattr(_prepare_aerobic_data, 'zone2_meta', None)

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
        'hr_zone_meta': hr_zone_meta,
        'zone2_meta': zone2_meta,
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


def _prepare_aerobic_data(start_date, end_date, activity_stats, ref_date=None):
    """有酸素運動データを準備（hr_zones ベースのゾーン分類）

    Parameters
    ----------
    start_date : pd.Timestamp
        表示期間開始日（healthplanet 測定日由来）
    end_date : pd.Timestamp
        表示期間終了日（healthplanet 測定日由来）
    activity_stats : dict
        アクティビティ統計
    ref_date : datetime.date, optional
        RHR ウィンドウ計算の基準日。未指定時は end_date を使用するが、
        必ず target_end（レポート引数の終了日=今日など）を渡すこと。
        mind と境界を一致させる設計要件のため。
    """
    import datetime as _dt

    # hr_zones 算出
    personal_cfg = hr_zones.load_personal_config()
    hr_zones_cfg = personal_cfg.get('hr_zones', {})
    resting_hr_cfg = hr_zones_cfg.get('resting_hr', {})
    window_days = resting_hr_cfg.get('window_days', 30)
    fallback = resting_hr_cfg.get('fallback', 48)
    method = hr_zones_cfg.get('method', 'hrr')

    # ref_date: RHR ウィンドウ計算の基準日は必ず target_end を使う（healthplanet 最終日でなく）
    if ref_date is not None:
        end_dt = ref_date.date() if hasattr(ref_date, 'date') else ref_date
    else:
        end_dt = end_date.date() if hasattr(end_date, 'date') else end_date

    df_hr_daily_raw = None
    if HEART_RATE_MASTER_CSV.exists():
        df_hr_daily_raw = pd.read_csv(HEART_RATE_MASTER_CSV)

    df_hr_intraday = None
    if HEART_RATE_INTRADAY_CSV.exists():
        df_hr_intraday = pd.read_csv(HEART_RATE_INTRADAY_CSV, index_col='datetime', parse_dates=True)

    max_hr = hr_zones.calc_max_hr(personal_cfg, end_dt)
    resting_hr = hr_zones.calc_resting_hr(df_hr_daily_raw, end_dt, window_days, fallback) if df_hr_daily_raw is not None else float(fallback)
    bounds = hr_zones.compute_zone_bounds(max_hr, resting_hr, method)

    df_zone = None
    if df_hr_intraday is not None:
        df_zone = hr_zones.calc_daily_zone_minutes(df_hr_intraday, bounds)

    # Zone2（LT1アンカー）日別分。%HRR ゾーンとは別目的（issue #21）
    zone2_by_date = {}
    zone2_meta = None
    if df_hr_intraday is not None:
        z2_daily, zone2_meta = zone2.prepare_zone2_daily_data(
            start_date.date() if hasattr(start_date, 'date') else start_date,
            end_date.date() if hasattr(end_date, 'date') else end_date,
            df_hr_intraday, personal_cfg, ref_date=end_dt
        )
        zone2_by_date = {d['date']: d['zone2_min'] for d in z2_daily}

    # VO2 Max データ
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

        # 心拍ゾーンデータ
        if df_zone is not None and date in df_zone.index:
            val = pd.to_numeric(df_zone.loc[date, 'z1_min'], errors='coerce')
            row['z1_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_zone.loc[date, 'z2_min'], errors='coerce')
            row['z2_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_zone.loc[date, 'z3_min'], errors='coerce')
            row['z3_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_zone.loc[date, 'z4_min'], errors='coerce')
            row['z4_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_zone.loc[date, 'z5_min'], errors='coerce')
            row['z5_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_zone.loc[date, 'total_zone_min'], errors='coerce')
            row['total_zone_min'] = int(val) if pd.notna(val) else None
        else:
            row['z1_min'] = None
            row['z2_min'] = None
            row['z3_min'] = None
            row['z4_min'] = None
            row['z5_min'] = None
            row['total_zone_min'] = None

        # Zone2（LT1アンカー）分
        row['zone2_min'] = zone2_by_date.get(date)

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

    # meta を返すためにグローバル変数に格納（コンテキストで参照）
    birth_date = personal_cfg.get('birth_date')
    if isinstance(birth_date, str):
        birth_date = _dt.date.fromisoformat(birth_date)
    age = hr_zones.calc_age(birth_date, end_dt)
    _prepare_aerobic_data.hr_zone_meta = {
        'max_hr': max_hr,
        'resting_hr': resting_hr,
        'age': age,
        'method': method,
        'hrr': float(max_hr - resting_hr),
        'bounds': bounds,
        'window_days': window_days,
    }
    _prepare_aerobic_data.zone2_meta = zone2_meta

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


def generate_report(output_dir, df, stats, sleep_stats=None, activity_stats=None, hrv_stats=None, nutrition_stats=None, eat_stats=None, target_end=None, show_charts=True):
    """マークダウンレポートを生成（Jinja2テンプレート版）"""
    from lib.templates.renderer import BodyReportRenderer

    report_path = output_dir / 'REPORT.md'

    # データ準備
    context = prepare_report_data(df, stats, sleep_stats, activity_stats,
                                  hrv_stats, nutrition_stats, eat_stats,
                                  target_end=target_end)
    context['show_charts'] = show_charts

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

    # target_end: hr_zones の RHR 計算基準日（mind と統一するため明示的に取得）
    try:
        _, target_end = determine_target_period(week, month, year, args.days)
    except ValueError:
        target_end = None

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
    ensure_dir(output_dir)
    img_dir = output_dir / 'img'
    if not args.no_charts:
        ensure_dir(img_dir)

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
    if not args.no_charts:
        plot_main_chart(df, img_dir / 'trend.png')

    # Generate report
    generate_report(output_dir, df, stats, sleep_stats, activity_stats, hrv_stats, nutrition_stats, eat_stats, target_end=target_end, show_charts=not args.no_charts)

    return 0


if __name__ == '__main__':
    exit(main())
