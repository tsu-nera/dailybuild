#!/usr/bin/env python
# coding: utf-8
"""
HRV（心拍変動）分析ライブラリ

HRVからトレーニング負荷と回復状態を評価
"""

import pandas as pd
import numpy as np


def calc_hrv_baseline(df, window=7):
    """
    HRVのベースライン（移動平均）を計算

    Args:
        df: HRVデータフレーム（daily_rmssd列が必要）
        window: 移動平均のウィンドウ（日数、デフォルト: 7）

    Returns:
        ベースライン列を追加したDataFrame
    """
    df = df.copy()
    df['hrv_baseline'] = df['daily_rmssd'].rolling(window=window, min_periods=1).mean()
    return df


def calc_hrv_deviation(df):
    """
    HRVベースラインからの乖離率を計算

    Args:
        df: HRVデータフレーム（daily_rmssd, hrv_baseline列が必要）

    Returns:
        乖離率列を追加したDataFrame
    """
    df = df.copy()
    df['hrv_deviation_pct'] = ((df['daily_rmssd'] - df['hrv_baseline']) / df['hrv_baseline'] * 100)
    return df


def detect_recovery_cycles(df, threshold_down=-10, threshold_up=5):
    """
    HRVの下降→回復サイクルを検出

    Args:
        df: HRVデータフレーム（hrv_deviation_pct列が必要）
        threshold_down: 下降判定閾値（%、デフォルト: -10%）
        threshold_up: 回復判定閾値（%、デフォルト: +5%）

    Returns:
        サイクル数
    """
    df = df.copy()
    deviation = df['hrv_deviation_pct'].dropna()

    if len(deviation) == 0:
        return 0

    cycles = 0
    in_stress = False

    for val in deviation:
        if val <= threshold_down:
            in_stress = True
        elif in_stress and val >= threshold_up:
            cycles += 1
            in_stress = False

    return cycles


def calc_training_load_score(df):
    """
    トレーニング負荷スコアを計算

    HRVの変動パターンから、適切な負荷がかかっているかを評価
    - 変動の大きさ（標準偏差）
    - 下降→回復サイクルの頻度
    - 平均的な乖離率

    Args:
        df: HRVデータフレーム（hrv_deviation_pct列が必要）

    Returns:
        dict: 負荷スコアと詳細
    """
    df = df.copy()
    deviation = df['hrv_deviation_pct'].dropna()

    if len(deviation) < 3:
        return None

    # 変動の大きさ（標準偏差）
    variability = deviation.std()

    # 下降→回復サイクル数
    cycles = detect_recovery_cycles(df)

    # 平均乖離率
    avg_deviation = deviation.mean()

    # 負荷スコアの計算
    # 1. 変動が大きい = 負荷がかかっている（0-40点）
    variability_score = min(variability * 2, 40)

    # 2. サイクルが適度にある = 回復できている（0-40点）
    cycle_score = min(cycles * 10, 40)

    # 3. 平均的に少し低め = 適度なストレス（0-20点）
    if -10 <= avg_deviation <= 0:
        deviation_score = 20
    elif -20 <= avg_deviation < -10:
        deviation_score = 10
    else:
        deviation_score = 0

    total_score = variability_score + cycle_score + deviation_score

    return {
        'load_score': total_score,
        'variability': variability,
        'cycles': cycles,
        'avg_deviation': avg_deviation,
        'variability_score': variability_score,
        'cycle_score': cycle_score,
        'deviation_score': deviation_score,
    }


def calc_rhr_baseline(df, window=7):
    """
    安静時心拍数のベースライン（移動平均）を計算

    Args:
        df: 心拍数データフレーム（resting_heart_rate列が必要）
        window: 移動平均のウィンドウ（日数、デフォルト: 7）

    Returns:
        ベースライン列を追加したDataFrame
    """
    df = df.copy()
    df['rhr_baseline'] = df['resting_heart_rate'].rolling(window=window, min_periods=1).mean()
    return df


def calc_rhr_deviation(df):
    """
    安静時心拍数のベースラインからの乖離を計算

    Args:
        df: 心拍数データフレーム（resting_heart_rate, rhr_baseline列が必要）

    Returns:
        乖離列を追加したDataFrame
    """
    df = df.copy()
    df['rhr_deviation'] = df['resting_heart_rate'] - df['rhr_baseline']
    return df


def calc_recovery_state_score(df_hrv, df_rhr):
    """
    HRVと心拍数を組み合わせた回復状態スコアを計算

    Args:
        df_hrv: HRVデータフレーム（hrv_deviation_pct列が必要）
        df_rhr: 心拍数データフレーム（rhr_deviation列が必要）

    Returns:
        dict: 回復状態スコアと詳細
    """
    # データをマージ（日付でjoin）
    df_merged = pd.merge(
        df_hrv[['hrv_deviation_pct']],
        df_rhr[['rhr_deviation']],
        left_index=True,
        right_index=True,
        how='inner'
    )

    if len(df_merged) < 3:
        return None

    # HRV評価（高い = 良い）
    avg_hrv_dev = df_merged['hrv_deviation_pct'].mean()
    if avg_hrv_dev >= 5:
        hrv_score = 50  # 優秀
    elif avg_hrv_dev >= 0:
        hrv_score = 40  # 良好
    elif avg_hrv_dev >= -10:
        hrv_score = 30  # 普通
    elif avg_hrv_dev >= -20:
        hrv_score = 20  # やや疲労
    else:
        hrv_score = 10  # 疲労

    # RHR評価（低い = 良い）
    avg_rhr_dev = df_merged['rhr_deviation'].mean()
    if avg_rhr_dev <= -3:
        rhr_score = 50  # 優秀（適応）
    elif avg_rhr_dev <= 0:
        rhr_score = 40  # 良好
    elif avg_rhr_dev <= 3:
        rhr_score = 30  # 普通
    elif avg_rhr_dev <= 6:
        rhr_score = 20  # やや疲労
    else:
        rhr_score = 10  # 疲労

    total_score = hrv_score + rhr_score

    # 状態評価
    if total_score >= 85:
        state = "最高"
    elif total_score >= 70:
        state = "良好"
    elif total_score >= 55:
        state = "普通"
    elif total_score >= 40:
        state = "やや疲労"
    else:
        state = "疲労"

    return {
        'recovery_score': total_score,
        'recovery_state': state,
        'hrv_score': hrv_score,
        'rhr_score': rhr_score,
        'avg_hrv_deviation': avg_hrv_dev,
        'avg_rhr_deviation': avg_rhr_dev,
    }


def calc_hrv_stats_for_period(df_hrv, df_rhr=None):
    """
    指定期間のHRV統計を計算

    Args:
        df_hrv: HRVデータフレーム（daily_rmssd列が必要）
        df_rhr: 心拍数データフレーム（resting_heart_rate列、オプション）

    Returns:
        dict: HRV統計
    """
    if len(df_hrv) == 0:
        return None

    # ベースラインと乖離率を計算
    df_hrv = calc_hrv_baseline(df_hrv)
    df_hrv = calc_hrv_deviation(df_hrv)

    # 基本統計
    daily_rmssd = df_hrv['daily_rmssd'].dropna()
    if len(daily_rmssd) == 0:
        return None

    # トレーニング負荷スコア
    load_score_data = calc_training_load_score(df_hrv)

    stats = {
        'days': len(df_hrv),
        'avg_rmssd': daily_rmssd.mean(),
        'std_rmssd': daily_rmssd.std(),
        'min_rmssd': daily_rmssd.min(),
        'max_rmssd': daily_rmssd.max(),
        'first_rmssd': daily_rmssd.iloc[0] if len(daily_rmssd) > 0 else None,
        'last_rmssd': daily_rmssd.iloc[-1] if len(daily_rmssd) > 0 else None,
        'change_rmssd': daily_rmssd.iloc[-1] - daily_rmssd.iloc[0] if len(daily_rmssd) > 1 else 0,
    }

    # トレーニング負荷スコアを追加
    if load_score_data:
        stats.update(load_score_data)

    # 心拍数データがあれば統合評価
    if df_rhr is not None and len(df_rhr) > 0:
        df_rhr = calc_rhr_baseline(df_rhr)
        df_rhr = calc_rhr_deviation(df_rhr)

        rhr = df_rhr['resting_heart_rate'].dropna()
        if len(rhr) > 0:
            stats['avg_rhr'] = rhr.mean()
            stats['std_rhr'] = rhr.std()
            stats['first_rhr'] = rhr.iloc[0]
            stats['last_rhr'] = rhr.iloc[-1]
            stats['change_rhr'] = rhr.iloc[-1] - rhr.iloc[0] if len(rhr) > 1 else 0

            # 回復状態スコアを計算
            recovery_data = calc_recovery_state_score(df_hrv, df_rhr)
            if recovery_data:
                stats.update(recovery_data)

    return stats
