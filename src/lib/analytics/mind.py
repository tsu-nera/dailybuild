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


def calc_readiness_score(hrv_stats, sleep_stats, rhr_stats=None, br_stats=None, spo2_stats=None):
    """
    総合レディネススコアを計算（0-100）

    Args:
        hrv_stats: HRV統計辞書（avg_rmssd必須）
        sleep_stats: 睡眠統計辞書
        rhr_stats: 安静時心拍数統計辞書（avg_rhr、オプション）
        br_stats: 呼吸数統計辞書（avg_breathing_rate、オプション）
        spo2_stats: SpO2統計辞書（avg_spo2、オプション）

    Returns:
        総合レディネススコア（0-100）
    """
    # HRVスコア（30%）
    hrv_score = calc_hrv_score(hrv_stats.get('avg_rmssd')) if hrv_stats else 0

    # 睡眠スコア（25%）
    sleep_score = calc_sleep_score(sleep_stats)

    # RHRスコア（20%）
    rhr_score = 0
    if rhr_stats and rhr_stats.get('avg_rhr'):
        rhr_score = calc_rhr_score(rhr_stats['avg_rhr'])

    # 基本スコア（HRV + 睡眠 + RHR = 75点満点）
    base_score = hrv_score + sleep_score + rhr_score
    max_base = 75

    # オプション指標
    br_score = calc_breathing_rate_score(br_stats.get('avg_breathing_rate')) if br_stats else None
    spo2_score = calc_spo2_score(spo2_stats.get('avg_spo2')) if spo2_stats else None

    # スコアの統合
    total = base_score
    max_total = max_base

    if br_score is not None:
        total += br_score
        max_total += 15

    if spo2_score is not None:
        total += spo2_score
        max_total += 10

    # 100点満点に正規化
    normalized = (total / max_total) * 100 if max_total > 0 else 0

    return round(min(normalized, 100))


def calc_stress_index(hrv_stats, rhr_stats=None):
    """
    ストレス指数を計算（0-100、低=良好）

    HRV低下 + RHR上昇 = 高ストレス

    Args:
        hrv_stats: HRV統計辞書（avg_deviation必須）
        rhr_stats: 安静時心拍数統計辞書（オプション）

    Returns:
        ストレス指数（0-100）
    """
    if not hrv_stats:
        return 50  # デフォルト値

    # HRVストレス：ベースラインからの乖離がマイナスならストレス高
    hrv_deviation = hrv_stats.get('avg_deviation', 0) or 0
    hrv_stress = max(0, -hrv_deviation * 3)  # マイナス乖離を正のストレスに

    # RHRストレス：ベースラインからの上昇でストレス高
    rhr_stress = 0
    if rhr_stats:
        rhr_deviation = rhr_stats.get('change_rhr', 0) or 0
        rhr_stress = max(0, rhr_deviation * 8)

    # 合成（HRV重視）
    stress = hrv_stress * 0.6 + rhr_stress * 0.4

    return round(min(stress, 100))


def calc_recovery_index(hrv_stats, sleep_stats):
    """
    回復指数を計算（0-100、高=良好）

    HRV回復 + 睡眠品質 = 高回復

    Args:
        hrv_stats: HRV統計辞書
        sleep_stats: 睡眠統計辞書

    Returns:
        回復指数（0-100）
    """
    if not hrv_stats and not sleep_stats:
        return 50  # デフォルト値

    recovery = 0

    # HRV回復サイクル（0-40点）
    if hrv_stats:
        cycles = hrv_stats.get('cycles', 0) or 0
        cycle_score = min(cycles * 15, 40)
        recovery += cycle_score

    # 睡眠からの回復（0-60点）
    if sleep_stats:
        # 深い睡眠割合（0-25点）
        deep_pct = sleep_stats.get('deep_pct', 0) or 0
        deep_score = min(deep_pct / 20 * 25, 25)

        # 睡眠効率（0-20点）
        eff = sleep_stats.get('avg_efficiency', 0) or 0
        eff_score = min(eff / 90 * 20, 20)

        # 睡眠時間（0-15点）
        hours = sleep_stats.get('avg_sleep_hours', 0) or 0
        hours_score = min(hours / 7.5 * 15, 15)

        recovery += deep_score + eff_score + hours_score

    return round(min(recovery, 100))


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


def calc_mind_stats_for_period(df_hrv, df_rhr=None, df_sleep=None, df_br=None, df_spo2=None, df_cardio=None, df_temp=None):
    """
    指定期間のメンタル統計を計算

    Args:
        df_hrv: HRVデータフレーム（daily_rmssd列必須）
        df_rhr: 心拍数データフレーム（resting_heart_rate列、オプション）
        df_sleep: 睡眠データフレーム（オプション）
        df_br: 呼吸数データフレーム（breathing_rate列、オプション）
        df_spo2: SpO2データフレーム（avg_spo2列、オプション）
        df_cardio: 心肺スコアデータフレーム（vo2_max列、オプション）
        df_temp: 皮膚温データフレーム（nightly_relative列、オプション）

    Returns:
        dict: メンタル統計
    """
    from . import hrv as hrv_module
    from . import sleep as sleep_module

    # HRV統計
    hrv_stats = None
    if df_hrv is not None and len(df_hrv) > 0:
        hrv_stats = hrv_module.calc_hrv_stats_for_period(df_hrv, df_rhr)

    # 睡眠統計
    sleep_stats = None
    if df_sleep is not None and len(df_sleep) > 0:
        sleep_stats = sleep_module.calc_recovery_score(df_sleep)

    # RHR統計
    rhr_stats = None
    if df_rhr is not None and len(df_rhr) > 0:
        rhr = df_rhr['resting_heart_rate'].dropna()
        if len(rhr) > 0:
            rhr_stats = {
                'days': len(rhr),
                'avg_rhr': rhr.mean(),
                'min_rhr': rhr.min(),
                'max_rhr': rhr.max(),
                'first_rhr': rhr.iloc[0],
                'last_rhr': rhr.iloc[-1],
                'change_rhr': rhr.iloc[-1] - rhr.iloc[0] if len(rhr) > 1 else 0,
            }

    # 呼吸数統計
    br_stats = None
    if df_br is not None and len(df_br) > 0:
        br = df_br['breathing_rate'].dropna()
        if len(br) > 0:
            br_stats = {
                'days': len(br),
                'avg_breathing_rate': br.mean(),
                'min_breathing_rate': br.min(),
                'max_breathing_rate': br.max(),
            }

    # SpO2統計
    spo2_stats = None
    if df_spo2 is not None and len(df_spo2) > 0:
        spo2 = df_spo2['avg_spo2'].dropna()
        if len(spo2) > 0:
            spo2_stats = {
                'days': len(spo2),
                'avg_spo2': spo2.mean(),
                'min_spo2': spo2.min(),
                'max_spo2': spo2.max(),
            }

    # 心肺スコア統計
    cardio_stats = None
    if df_cardio is not None and len(df_cardio) > 0:
        vo2 = df_cardio['vo2_max'].dropna()
        if len(vo2) > 0:
            cardio_stats = {
                'days': len(vo2),
                'avg_vo2_max': vo2.mean(),
                'min_vo2_max': vo2.min(),
                'max_vo2_max': vo2.max(),
                'last_vo2_max': vo2.iloc[-1],
            }

    # 皮膚温統計
    temp_stats = None
    if df_temp is not None and len(df_temp) > 0:
        temp = df_temp['nightly_relative'].dropna()
        if len(temp) > 0:
            temp_stats = {
                'days': len(temp),
                'avg_temp_variation': temp.mean(),
                'min_temp_variation': temp.min(),
                'max_temp_variation': temp.max(),
                'std_temp_variation': temp.std(),
            }

    # 総合スコア計算
    readiness = calc_readiness_score(hrv_stats, sleep_stats, rhr_stats, br_stats, spo2_stats)
    stress = calc_stress_index(hrv_stats, rhr_stats)
    recovery = calc_recovery_index(hrv_stats, sleep_stats)

    # トレンド評価
    hrv_trend = 'stable'
    rhr_trend = 'stable'
    if hrv_stats and df_hrv is not None:
        hrv_values = df_hrv['daily_rmssd'].dropna().tolist()
        hrv_trend = evaluate_trend(hrv_values)
    if rhr_stats and df_rhr is not None:
        rhr_values = df_rhr['resting_heart_rate'].dropna().tolist()
        rhr_trend = evaluate_trend(rhr_values)

    # 状態評価
    if readiness >= 80:
        state = '最高'
    elif readiness >= 65:
        state = '良好'
    elif readiness >= 50:
        state = '普通'
    elif readiness >= 35:
        state = 'やや疲労'
    else:
        state = '疲労'

    return {
        'days': len(df_hrv) if df_hrv is not None else 0,
        'readiness_score': readiness,
        'stress_index': stress,
        'recovery_index': recovery,
        'state': state,
        'hrv_trend': hrv_trend,
        'rhr_trend': rhr_trend,
        'hrv_stats': hrv_stats,
        'sleep_stats': sleep_stats,
        'rhr_stats': rhr_stats,
        'br_stats': br_stats,
        'spo2_stats': spo2_stats,
        'cardio_stats': cardio_stats,
        'temp_stats': temp_stats,
    }


def build_daily_data(df_hrv, df_rhr=None, df_sleep=None, df_br=None, df_spo2=None):
    """
    日別データを構築

    Args:
        df_hrv: HRVデータフレーム
        df_rhr: 心拍数データフレーム
        df_sleep: 睡眠データフレーム
        df_br: 呼吸数データフレーム
        df_spo2: SpO2データフレーム

    Returns:
        日別データのリスト
    """
    # HRVをベースに日付を取得
    if df_hrv is None or len(df_hrv) == 0:
        return []

    dates = df_hrv.index.tolist()
    daily_data = []

    for date in dates:
        row = {'date': date}

        # HRV
        if date in df_hrv.index:
            row['daily_rmssd'] = df_hrv.loc[date, 'daily_rmssd']

        # RHR
        if df_rhr is not None and date in df_rhr.index:
            row['resting_heart_rate'] = df_rhr.loc[date, 'resting_heart_rate']

        # 睡眠
        if df_sleep is not None:
            sleep_date = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)
            sleep_row = df_sleep[df_sleep['dateOfSleep'] == sleep_date]
            if len(sleep_row) > 0:
                row['sleep_hours'] = sleep_row.iloc[0]['minutesAsleep'] / 60
                row['sleep_efficiency'] = sleep_row.iloc[0]['efficiency']

        # 呼吸数
        if df_br is not None and date in df_br.index:
            row['breathing_rate'] = df_br.loc[date, 'breathing_rate']

        # SpO2
        if df_spo2 is not None and date in df_spo2.index:
            row['avg_spo2'] = df_spo2.loc[date, 'avg_spo2']

        daily_data.append(row)

    return daily_data
