#!/usr/bin/env python
# coding: utf-8
"""
メンタル（心理的コンディション）分析ライブラリ

HRV、睡眠、安静時心拍数、呼吸数、SpO2から総合的なメンタル状態を評価
"""

import pandas as pd
import numpy as np


def calc_hrv_score(avg_rmssd):
    """
    HRVスコアを計算（0-30点）

    Args:
        avg_rmssd: 平均RMSSD (ms)

    Returns:
        HRVスコア（0-30）
    """
    if avg_rmssd is None or np.isnan(avg_rmssd):
        return 0
    # 40ms以上で満点、20ms以下で0点
    score = (avg_rmssd - 20) / 20 * 30
    return min(max(score, 0), 30)


def calc_sleep_score(sleep_stats):
    """
    睡眠スコアを計算（0-25点）

    Args:
        sleep_stats: 睡眠統計辞書
            - avg_efficiency: 平均睡眠効率（%）
            - deep_pct: 深い睡眠割合（%）
            - avg_sleep_hours: 平均睡眠時間

    Returns:
        睡眠スコア（0-25）
    """
    if not sleep_stats:
        return 0

    # 効率スコア（0-10点）: 85%以上で満点
    eff = sleep_stats.get('avg_efficiency', 0) or 0
    eff_score = min(eff / 85 * 10, 10)

    # 深い睡眠スコア（0-8点）: 20%以上で満点
    deep = sleep_stats.get('deep_pct', 0) or 0
    deep_score = min(deep / 20 * 8, 8)

    # 時間スコア（0-7点）: 8時間以上で満点
    hours = sleep_stats.get('avg_sleep_hours', 0) or 0
    hours_score = min(hours / 8 * 7, 7)

    return eff_score + deep_score + hours_score


def calc_rhr_score(avg_rhr):
    """
    安静時心拍数スコアを計算（0-20点）

    Args:
        avg_rhr: 平均安静時心拍数 (bpm)

    Returns:
        RHRスコア（0-20）
    """
    if avg_rhr is None or np.isnan(avg_rhr):
        return 0
    # 50bpm以下で満点、60bpm以上で10点
    score = 20 - (avg_rhr - 50)
    return min(max(score, 0), 20)


def calc_breathing_rate_score(avg_br):
    """
    呼吸数スコアを計算（0-15点）

    Args:
        avg_br: 平均呼吸数（回/分）

    Returns:
        呼吸数スコア（0-15）
    """
    if avg_br is None or np.isnan(avg_br):
        return None
    # 正常範囲（12-20回/分）内なら満点
    if 12 <= avg_br <= 20:
        return 15
    # 範囲外は減点
    deviation = min(abs(avg_br - 16), 8)
    return max(15 - deviation * 2, 0)


def calc_spo2_score(avg_spo2):
    """
    SpO2スコアを計算（0-10点）

    Args:
        avg_spo2: 平均SpO2（%）

    Returns:
        SpO2スコア（0-10）
    """
    if avg_spo2 is None or np.isnan(avg_spo2):
        return None
    # 95%以上で満点
    if avg_spo2 >= 95:
        return 10
    # 95%未満は減点
    return max(10 - (95 - avg_spo2) * 3, 0)


def evaluate_trend(values, window=3):
    """
    値のトレンド（上昇/下降/安定）を評価

    Args:
        values: 値のリストまたはSeries
        window: トレンド判定に使う直近のデータ数

    Returns:
        str: 'up', 'down', 'stable'
    """
    if len(values) < 2:
        return 'stable'

    recent = values[-window:] if len(values) >= window else values
    first = recent[0]
    last = recent[-1]

    if first == 0:
        return 'stable'

    change_pct = (last - first) / abs(first) * 100

    if change_pct > 5:
        return 'up'
    elif change_pct < -5:
        return 'down'
    return 'stable'


def format_trend(trend):
    """
    トレンドを表示用文字列に変換

    Args:
        trend: 'up', 'down', 'stable'

    Returns:
        表示用文字列
    """
    mapping = {
        'up': '↗ 上昇',
        'down': '↘ 下降',
        'stable': '→ 安定',
    }
    return mapping.get(trend, '→ 安定')


def prepare_responsiveness_daily_data(start_date, end_date, df_hrv, df_heart_rate, df_breathing, df_temp, df_spo2=None):
    """
    反応性の日別データを準備（ベースライン情報含む）

    Args:
        start_date: 開始日
        end_date: 終了日
        df_hrv: HRVデータフレーム（index=date、ベースライン計算済み）
        df_heart_rate: 心拍数データフレーム（index=date、ベースライン計算済み）
        df_breathing: 呼吸数データフレーム（index=date、ベースライン計算済み）
        df_temp: 皮膚温データフレーム（index=date、ベースライン計算済み）
        df_spo2: SpO2データフレーム（index=date、ベースライン計算済み）

    Returns:
        list[dict]: 日別データリスト（ベースライン乖離情報含む）
    """
    responsiveness_data = []
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

    for date in all_dates:
        row = {'date': date}

        # HRV (daily)
        if df_hrv is not None and date in df_hrv.index:
            val = df_hrv.loc[date, 'daily_rmssd']
            row['hrv_daily'] = float(val) if pd.notna(val) else None
            # ベースライン情報
            if 'daily_rmssd_baseline' in df_hrv.columns:
                baseline = df_hrv.loc[date, 'daily_rmssd_baseline']
                row['hrv_daily_baseline'] = float(baseline) if pd.notna(baseline) else None
                baseline_std = df_hrv.loc[date, 'daily_rmssd_baseline_std']
                row['hrv_daily_baseline_std'] = float(baseline_std) if pd.notna(baseline_std) else None
                dev_pct = df_hrv.loc[date, 'daily_rmssd_deviation_pct']
                row['hrv_daily_deviation_pct'] = float(dev_pct) if pd.notna(dev_pct) else None
                z_score = df_hrv.loc[date, 'daily_rmssd_z_score']
                row['hrv_daily_z_score'] = float(z_score) if pd.notna(z_score) else None
        else:
            row['hrv_daily'] = None

        # HRV (deep)
        if df_hrv is not None and date in df_hrv.index:
            val = df_hrv.loc[date, 'deep_rmssd']
            row['hrv_deep'] = float(val) if pd.notna(val) else None
            # ベースライン情報
            if 'deep_rmssd_baseline' in df_hrv.columns:
                baseline = df_hrv.loc[date, 'deep_rmssd_baseline']
                row['hrv_deep_baseline'] = float(baseline) if pd.notna(baseline) else None
                dev_pct = df_hrv.loc[date, 'deep_rmssd_deviation_pct']
                row['hrv_deep_deviation_pct'] = float(dev_pct) if pd.notna(dev_pct) else None
        else:
            row['hrv_deep'] = None

        # 安静時心拍数
        if df_heart_rate is not None and date in df_heart_rate.index:
            val = df_heart_rate.loc[date, 'resting_heart_rate']
            row['rhr'] = float(val) if pd.notna(val) else None
            # ベースライン情報
            if 'resting_heart_rate_baseline' in df_heart_rate.columns:
                baseline = df_heart_rate.loc[date, 'resting_heart_rate_baseline']
                row['rhr_baseline'] = float(baseline) if pd.notna(baseline) else None
                baseline_std = df_heart_rate.loc[date, 'resting_heart_rate_baseline_std']
                row['rhr_baseline_std'] = float(baseline_std) if pd.notna(baseline_std) else None
                dev_pct = df_heart_rate.loc[date, 'resting_heart_rate_deviation_pct']
                row['rhr_deviation_pct'] = float(dev_pct) if pd.notna(dev_pct) else None
                z_score = df_heart_rate.loc[date, 'resting_heart_rate_z_score']
                row['rhr_z_score'] = float(z_score) if pd.notna(z_score) else None
        else:
            row['rhr'] = None

        # 呼吸数
        if df_breathing is not None and date in df_breathing.index:
            val = df_breathing.loc[date, 'breathing_rate']
            row['breathing_rate'] = float(val) if pd.notna(val) else None
            # ベースライン情報
            if 'breathing_rate_baseline' in df_breathing.columns:
                baseline = df_breathing.loc[date, 'breathing_rate_baseline']
                row['breathing_rate_baseline'] = float(baseline) if pd.notna(baseline) else None
                baseline_std = df_breathing.loc[date, 'breathing_rate_baseline_std']
                row['breathing_rate_baseline_std'] = float(baseline_std) if pd.notna(baseline_std) else None
                dev_pct = df_breathing.loc[date, 'breathing_rate_deviation_pct']
                row['breathing_rate_deviation_pct'] = float(dev_pct) if pd.notna(dev_pct) else None
                z_score = df_breathing.loc[date, 'breathing_rate_z_score']
                row['breathing_rate_z_score'] = float(z_score) if pd.notna(z_score) else None
        else:
            row['breathing_rate'] = None

        # SpO2
        if df_spo2 is not None and date in df_spo2.index:
            avg_val = df_spo2.loc[date, 'avg_spo2']
            min_val = df_spo2.loc[date, 'min_spo2']
            row['spo2_avg'] = float(avg_val) if pd.notna(avg_val) else None
            row['spo2_min'] = float(min_val) if pd.notna(min_val) else None
            # ベースライン情報
            if 'avg_spo2_baseline' in df_spo2.columns:
                baseline = df_spo2.loc[date, 'avg_spo2_baseline']
                row['spo2_avg_baseline'] = float(baseline) if pd.notna(baseline) else None
                baseline_std = df_spo2.loc[date, 'avg_spo2_baseline_std']
                row['spo2_avg_baseline_std'] = float(baseline_std) if pd.notna(baseline_std) else None
                dev_pct = df_spo2.loc[date, 'avg_spo2_deviation_pct']
                row['spo2_avg_deviation_pct'] = float(dev_pct) if pd.notna(dev_pct) else None
                z_score = df_spo2.loc[date, 'avg_spo2_z_score']
                row['spo2_avg_z_score'] = float(z_score) if pd.notna(z_score) else None
        else:
            row['spo2_avg'] = None
            row['spo2_min'] = None

        # 皮膚温変動
        if df_temp is not None and date in df_temp.index:
            val = df_temp.loc[date, 'nightly_relative']
            row['temp_variation'] = float(val) if pd.notna(val) else None
            # ベースライン情報
            if 'nightly_relative_baseline' in df_temp.columns:
                baseline = df_temp.loc[date, 'nightly_relative_baseline']
                row['temp_variation_baseline'] = float(baseline) if pd.notna(baseline) else None
                baseline_std = df_temp.loc[date, 'nightly_relative_baseline_std']
                row['temp_variation_baseline_std'] = float(baseline_std) if pd.notna(baseline_std) else None
                dev_pct = df_temp.loc[date, 'nightly_relative_deviation_pct']
                row['temp_variation_deviation_pct'] = float(dev_pct) if pd.notna(dev_pct) else None
                z_score = df_temp.loc[date, 'nightly_relative_z_score']
                row['temp_variation_z_score'] = float(z_score) if pd.notna(z_score) else None
        else:
            row['temp_variation'] = None

        responsiveness_data.append(row)

    return responsiveness_data


def prepare_exertion_balance_daily_data(start_date, end_date, df_activity, df_azm):
    """
    運動バランスの日別データを準備

    Args:
        start_date: 開始日
        end_date: 終了日
        df_activity: アクティビティデータフレーム（index=date）
        df_azm: アクティブゾーン分データフレーム（index=date）

    Returns:
        list[dict]: 日別データリスト
    """
    exertion_data = []
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

    for date in all_dates:
        row = {'date': date}

        # アクティビティデータ
        if df_activity is not None and date in df_activity.index:
            val = pd.to_numeric(df_activity.loc[date, 'steps'], errors='coerce')
            row['steps'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_activity.loc[date, 'sedentaryMinutes'], errors='coerce')
            row['sedentary_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_activity.loc[date, 'lightlyActiveMinutes'], errors='coerce')
            row['lightly_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_activity.loc[date, 'fairlyActiveMinutes'], errors='coerce')
            row['fairly_min'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_activity.loc[date, 'veryActiveMinutes'], errors='coerce')
            row['very_min'] = int(val) if pd.notna(val) else None
        else:
            row['steps'] = None
            row['sedentary_min'] = None
            row['lightly_min'] = None
            row['fairly_min'] = None
            row['very_min'] = None

        # アクティブゾーン分
        if df_azm is not None and date in df_azm.index:
            val = pd.to_numeric(df_azm.loc[date, 'activeZoneMinutes'], errors='coerce')
            row['active_zone_minutes'] = int(val) if pd.notna(val) else None
            val = pd.to_numeric(df_azm.loc[date, 'fatBurnActiveZoneMinutes'], errors='coerce')
            row['fat_burn'] = float(val) if pd.notna(val) else None
            val = pd.to_numeric(df_azm.loc[date, 'cardioActiveZoneMinutes'], errors='coerce')
            row['cardio'] = float(val) if pd.notna(val) else None
            val = pd.to_numeric(df_azm.loc[date, 'peakActiveZoneMinutes'], errors='coerce')
            row['peak'] = float(val) if pd.notna(val) else None
        else:
            row['active_zone_minutes'] = None
            row['fat_burn'] = None
            row['cardio'] = None
            row['peak'] = None

        exertion_data.append(row)

    return exertion_data


def prepare_sleep_patterns_daily_data(start_date, end_date, df_sleep, df_levels=None):
    """
    睡眠パターンの日別データを準備

    Args:
        start_date: 開始日
        end_date: 終了日
        df_sleep: 睡眠データフレーム（dateOfSleep列あり）
        df_levels: 睡眠レベルデータフレーム（sleep_levels.csv、オプショナル）

    Returns:
        list[dict]: 日別データリスト（入眠潜時・起床後時間含む）
    """
    from lib.analytics.sleep import calc_sleep_timing

    sleep_data = []
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')

    # 入眠潜時・起床後時間を計算（df_levelsが提供されている場合）
    sleep_timing = {}
    if df_levels is not None:
        sleep_timing = calc_sleep_timing(df_levels)

    for date in all_dates:
        row = {'date': date}
        date_str = date.strftime('%Y-%m-%d')

        # 睡眠データ
        if df_sleep is not None:
            sleep_day = df_sleep[df_sleep['dateOfSleep'] == date]
            if len(sleep_day) > 0:
                # 就寝時刻
                if 'startTime' in sleep_day.columns:
                    start_time = sleep_day.iloc[0]['startTime']
                    if pd.notna(start_time):
                        row['bedtime'] = pd.to_datetime(start_time).strftime('%H:%M')
                    else:
                        row['bedtime'] = None
                else:
                    row['bedtime'] = None

                # 起床時刻
                if 'endTime' in sleep_day.columns:
                    end_time = sleep_day.iloc[0]['endTime']
                    if pd.notna(end_time):
                        row['waketime'] = pd.to_datetime(end_time).strftime('%H:%M')
                    else:
                        row['waketime'] = None
                else:
                    row['waketime'] = None

                # 睡眠時間
                val = sleep_day.iloc[0]['minutesAsleep']
                row['sleep_hours'] = float(val) / 60 if pd.notna(val) else None

                # 効率
                val = sleep_day.iloc[0]['efficiency']
                row['efficiency'] = float(val) if pd.notna(val) else None

                # 覚醒時間（分）
                if 'minutesAwake' in sleep_day.columns:
                    val = sleep_day.iloc[0]['minutesAwake']
                    row['minutes_awake'] = float(val) if pd.notna(val) else None
                else:
                    row['minutes_awake'] = None

                # 中途覚醒回数
                if 'wakeCount' in sleep_day.columns:
                    val = sleep_day.iloc[0]['wakeCount']
                    row['wake_count'] = int(val) if pd.notna(val) else None
                else:
                    row['wake_count'] = None
            else:
                row['bedtime'] = None
                row['waketime'] = None
                row['sleep_hours'] = None
                row['efficiency'] = None
                row['minutes_awake'] = None
                row['wake_count'] = None
        else:
            row['bedtime'] = None
            row['waketime'] = None
            row['sleep_hours'] = None
            row['efficiency'] = None
            row['minutes_awake'] = None
            row['wake_count'] = None

        # 入眠潜時・起床後時間（sleep_timingから取得）
        if date_str in sleep_timing:
            timing = sleep_timing[date_str]
            row['minutes_to_fall_asleep'] = timing.get('minutes_to_fall_asleep', 0)
            row['minutes_after_wakeup'] = timing.get('minutes_after_wakeup', 0)
        else:
            row['minutes_to_fall_asleep'] = None
            row['minutes_after_wakeup'] = None

        sleep_data.append(row)

    return sleep_data


# ベースライン計算期間の定義
BASELINE_WINDOWS = {
    'hrv_daily': 60,        # HRVは日々の変動が大きいため長期
    'hrv_deep': 60,
    'rhr': 30,              # 安静時心拍数は比較的安定
    'breathing_rate': 30,   # 呼吸数
    'spo2_avg': 30,         # SpO2
    'temp_variation': 30,   # 皮膚温変動
}


def calculate_baseline_metrics(
    df: pd.DataFrame,
    value_column: str,
    baseline_window: int = 30,
    min_periods: int = 7
) -> pd.DataFrame:
    """
    ベースラインと乖離指標を計算する共通関数

    個人のベースライン（移動平均）を計算し、現在値がベースラインから
    どれだけ乖離しているかを複数の指標で評価します。

    Parameters
    ----------
    df : DataFrame
        計算対象のDataFrame（index=date）
    value_column : str
        計算対象の列名（例: 'daily_rmssd', 'resting_heart_rate'）
    baseline_window : int
        ベースライン計算期間（日数）、デフォルト30日
    min_periods : int
        最小必要データ数、デフォルト7日

    Returns
    -------
    DataFrame
        以下の列が追加されたDataFrame:
        - {value_column}_baseline: 移動平均ベースライン
        - {value_column}_baseline_std: 標準偏差
        - {value_column}_deviation: 乖離（実数）
        - {value_column}_deviation_pct: 乖離率（%）
        - {value_column}_z_score: Z-score（標準偏差何個分か）

    Examples
    --------
    >>> df_hrv = calculate_baseline_metrics(df_hrv, 'daily_rmssd', baseline_window=60)
    >>> # HRVが45msで、ベースラインが40msの場合
    >>> # deviation = +5ms, deviation_pct = +12.5%, z_score = +0.8 など
    """
    df = df.copy()

    # 移動平均・標準偏差
    df[f'{value_column}_baseline'] = df[value_column].rolling(
        window=baseline_window, min_periods=min_periods
    ).mean()

    df[f'{value_column}_baseline_std'] = df[value_column].rolling(
        window=baseline_window, min_periods=min_periods
    ).std()

    # 乖離指標
    df[f'{value_column}_deviation'] = df[value_column] - df[f'{value_column}_baseline']

    df[f'{value_column}_deviation_pct'] = (
        df[f'{value_column}_deviation'] / df[f'{value_column}_baseline']
    ) * 100

    df[f'{value_column}_z_score'] = (
        df[f'{value_column}_deviation'] / df[f'{value_column}_baseline_std']
    )

    return df
