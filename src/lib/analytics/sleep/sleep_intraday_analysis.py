#!/usr/bin/env python
# coding: utf-8
"""
睡眠中のIntradayデータ分析ライブラリ

分単位のバイタルサイン（心拍数、呼吸数など）を睡眠時間帯で分析する。
"""

import pandas as pd
import numpy as np


# =============================================================================
# 心拍数分析
# =============================================================================

def calc_resting_hr_baseline(df_hr_daily, lookback_days=7):
    """
    安静時心拍数のベースライン（過去N日間の平均）を計算

    Args:
        df_hr_daily: heart_rate.csv を読み込んだDataFrame (date, resting_heart_rate)
        lookback_days: 過去何日分の平均を取るか（デフォルト7日）

    Returns:
        float: ベースライン心拍数
    """
    if df_hr_daily is None or len(df_hr_daily) == 0:
        return None

    df = df_hr_daily.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'])

    df = df.sort_values('date', ascending=False)
    recent = df.head(lookback_days)

    if len(recent) == 0:
        return None

    return recent['resting_heart_rate'].mean()


def calc_sleep_heart_rate_stats(df_sleep, df_hr_intraday, df_hr_daily=None, baseline_days=7):
    """
    睡眠中の心拍数統計を計算

    Args:
        df_sleep: sleep.csv を読み込んだDataFrame
        df_hr_intraday: heart_rate_intraday.csv を読み込んだDataFrame
        df_hr_daily: heart_rate.csv を読み込んだDataFrame (オプション)
        baseline_days: 安静時心拍数ベースライン計算期間（デフォルト7日）

    Returns:
        dict: 日付をキーとした心拍数統計の辞書
    """
    if df_hr_intraday is None or len(df_hr_intraday) == 0:
        return {}

    df_hr = df_hr_intraday.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_hr['datetime']):
        df_hr['datetime'] = pd.to_datetime(df_hr['datetime'])

    # 安静時心拍数ベースラインを計算
    resting_baseline = None
    if df_hr_daily is not None:
        resting_baseline = calc_resting_hr_baseline(df_hr_daily, baseline_days)

    results = {}

    for _, row in df_sleep.iterrows():
        date = row['dateOfSleep']
        sleep_start = pd.to_datetime(row['startTime'])
        sleep_end = pd.to_datetime(row['endTime'])

        # 睡眠時間帯の心拍数を抽出
        sleep_hr = df_hr[
            (df_hr['datetime'] >= sleep_start) &
            (df_hr['datetime'] <= sleep_end)
        ]

        if len(sleep_hr) == 0:
            continue

        # 統計値を計算
        avg_hr = sleep_hr['heart_rate'].mean()
        min_hr = sleep_hr['heart_rate'].min()
        max_hr = sleep_hr['heart_rate'].max()

        # 当日の安静時心拍数（heart_rate.csv）
        daily_resting_hr = None
        if df_hr_daily is not None:
            daily_record = df_hr_daily[df_hr_daily['date'] == date]
            if len(daily_record) > 0:
                daily_resting_hr = int(daily_record['resting_heart_rate'].iloc[0])

        # ベースラインとの比較
        above_baseline = None
        below_baseline = None
        above_pct = None
        below_pct = None

        if resting_baseline is not None:
            total = len(sleep_hr)
            above_baseline = (sleep_hr['heart_rate'] > resting_baseline).sum()
            below_baseline = (sleep_hr['heart_rate'] <= resting_baseline).sum()
            above_pct = (above_baseline / total) * 100
            below_pct = (below_baseline / total) * 100

        results[date] = {
            'avg_hr': avg_hr,
            'min_hr': int(min_hr),
            'max_hr': int(max_hr),
            'data_points': len(sleep_hr),
            'resting_baseline': resting_baseline,
            'daily_resting_hr': daily_resting_hr,
            'above_baseline_pct': above_pct,
            'below_baseline_pct': below_pct,
        }

    return results


def calc_advanced_hr_metrics(df_sleep, df_hr_intraday):
    """
    高度な心拍数指標を計算（ディップ率、最低HR到達時間）

    Args:
        df_sleep: sleep.csv を読み込んだDataFrame
        df_hr_intraday: heart_rate_intraday.csv を読み込んだDataFrame

    Returns:
        dict: 日付をキーとした高度な心拍数指標の辞書
            - dip_rate_avg: 夜間心拍数ディップ率（睡眠平均）(%)
            - dip_rate_min: 夜間心拍数ディップ率（最低心拍数）(%)
            - night_day_ratio: 夜/昼心拍数比率
            - time_to_min_hr: 入眠から最低心拍数までの時間（分）
            - min_hr_time: 最低心拍数の発生時刻
            - avg_day_hr: 日中平均心拍数
            - avg_sleep_hr: 睡眠中平均心拍数
            - min_sleep_hr: 睡眠中最低心拍数
    """
    if df_hr_intraday is None or len(df_hr_intraday) == 0:
        return {}

    df_hr = df_hr_intraday.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_hr['datetime']):
        df_hr['datetime'] = pd.to_datetime(df_hr['datetime'])

    results = {}

    for _, row in df_sleep.iterrows():
        date = row['dateOfSleep']
        sleep_start = pd.to_datetime(row['startTime'])
        sleep_end = pd.to_datetime(row['endTime'])

        # 日中の平均心拍数を計算（6:00-22:00）
        day_start = sleep_start.replace(hour=6, minute=0, second=0)
        day_end = sleep_start.replace(hour=22, minute=0, second=0)

        day_hr = df_hr[
            (df_hr['datetime'] >= day_start) &
            (df_hr['datetime'] < day_end)
        ]

        if len(day_hr) == 0:
            continue

        avg_day_hr = day_hr['heart_rate'].mean()

        # 睡眠時間帯の心拍数を抽出
        sleep_hr = df_hr[
            (df_hr['datetime'] >= sleep_start) &
            (df_hr['datetime'] <= sleep_end)
        ]

        if len(sleep_hr) == 0:
            continue

        # 睡眠中の心拍数統計
        min_sleep_hr = sleep_hr['heart_rate'].min()
        avg_sleep_hr = sleep_hr['heart_rate'].mean()

        # ディップ率を計算
        dip_rate_avg = ((avg_day_hr - avg_sleep_hr) / avg_day_hr) * 100
        dip_rate_min = ((avg_day_hr - min_sleep_hr) / avg_day_hr) * 100
        night_day_ratio = avg_sleep_hr / avg_day_hr

        # 入眠から最低心拍数までの時間
        min_hr_idx = sleep_hr['heart_rate'].idxmin()
        min_hr_time = sleep_hr.loc[min_hr_idx, 'datetime']
        time_to_min_hr = (min_hr_time - sleep_start).total_seconds() / 60  # 分単位

        results[date] = {
            'dip_rate_avg': dip_rate_avg,
            'dip_rate_min': dip_rate_min,
            'night_day_ratio': night_day_ratio,
            'time_to_min_hr': time_to_min_hr,
            'min_hr_time': min_hr_time.strftime('%H:%M'),
            'avg_day_hr': avg_day_hr,
            'avg_sleep_hr': avg_sleep_hr,
            'min_sleep_hr': int(min_sleep_hr),
        }

    return results


# =============================================================================
# HRV分析
# =============================================================================

def calc_hrv_intraday_metrics(df_sleep, df_hrv_intraday):
    """
    HRV Intradayから高度な指標を計算

    Args:
        df_sleep: sleep.csv を読み込んだDataFrame
        df_hrv_intraday: hrv_intraday.csv を読み込んだDataFrame

    Returns:
        dict: 日付をキーとしたHRV指標の辞書
            - avg_rmssd: 平均RMSSD（副交感神経活動）
            - avg_hf: 平均HF（高周波成分）
            - avg_lf: 平均LF（低周波成分）
            - avg_lf_hf_ratio: 平均LF/HF比（自律神経バランス）
            - initial_lf_hf_ratio: 入眠後30分のLF/HF比
            - final_lf_hf_ratio: 起床前30分のLF/HF比
            - lf_hf_decline_rate: LF/HF比の低下率(%)
            - hf_activation_speed: HF上昇速度（入眠後60分でのHF変化率）
            - data_points: データポイント数
    """
    if df_hrv_intraday is None or len(df_hrv_intraday) == 0:
        return {}

    df_hrv = df_hrv_intraday.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_hrv['datetime']):
        df_hrv['datetime'] = pd.to_datetime(df_hrv['datetime'])

    # LF/HF比を計算（APIから返されない場合）
    if 'lf_hf_ratio' not in df_hrv.columns or df_hrv['lf_hf_ratio'].isna().all():
        df_hrv['lf_hf_ratio'] = df_hrv['lf'] / df_hrv['hf']

    results = {}

    for _, row in df_sleep.iterrows():
        date = row['dateOfSleep']
        sleep_start = pd.to_datetime(row['startTime'])
        sleep_end = pd.to_datetime(row['endTime'])

        # 睡眠時間帯のHRVデータを抽出
        sleep_hrv = df_hrv[
            (df_hrv['datetime'] >= sleep_start) &
            (df_hrv['datetime'] <= sleep_end)
        ].copy()

        if len(sleep_hrv) == 0:
            continue

        # 基本統計
        avg_rmssd = sleep_hrv['rmssd'].mean()
        avg_hf = sleep_hrv['hf'].mean()
        avg_lf = sleep_hrv['lf'].mean()
        avg_lf_hf_ratio = sleep_hrv['lf_hf_ratio'].mean()

        # 入眠後30分のLF/HF比
        initial_period = sleep_hrv[
            sleep_hrv['datetime'] <= sleep_start + pd.Timedelta(minutes=30)
        ]
        initial_lf_hf_ratio = initial_period['lf_hf_ratio'].mean() if len(initial_period) > 0 else None

        # 起床前30分のLF/HF比
        final_period = sleep_hrv[
            sleep_hrv['datetime'] >= sleep_end - pd.Timedelta(minutes=30)
        ]
        final_lf_hf_ratio = final_period['lf_hf_ratio'].mean() if len(final_period) > 0 else None

        # LF/HF比の低下率
        lf_hf_decline_rate = None
        if initial_lf_hf_ratio is not None and final_lf_hf_ratio is not None and initial_lf_hf_ratio > 0:
            lf_hf_decline_rate = ((initial_lf_hf_ratio - final_lf_hf_ratio) / initial_lf_hf_ratio) * 100

        # HF上昇速度（入眠後60分でのHF変化率）
        initial_hf_period = sleep_hrv[
            sleep_hrv['datetime'] <= sleep_start + pd.Timedelta(minutes=30)
        ]
        later_hf_period = sleep_hrv[
            (sleep_hrv['datetime'] > sleep_start + pd.Timedelta(minutes=30)) &
            (sleep_hrv['datetime'] <= sleep_start + pd.Timedelta(minutes=60))
        ]

        hf_activation_speed = None
        if len(initial_hf_period) > 0 and len(later_hf_period) > 0:
            initial_hf = initial_hf_period['hf'].mean()
            later_hf = later_hf_period['hf'].mean()
            if initial_hf > 0:
                hf_activation_speed = ((later_hf - initial_hf) / initial_hf) * 100

        results[date] = {
            'avg_rmssd': avg_rmssd,
            'avg_hf': avg_hf,
            'avg_lf': avg_lf,
            'avg_lf_hf_ratio': avg_lf_hf_ratio,
            'initial_lf_hf_ratio': initial_lf_hf_ratio,
            'final_lf_hf_ratio': final_lf_hf_ratio,
            'lf_hf_decline_rate': lf_hf_decline_rate,
            'hf_activation_speed': hf_activation_speed,
            'data_points': len(sleep_hrv),
        }

    return results
