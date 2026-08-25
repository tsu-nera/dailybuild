#!/usr/bin/env python
# coding: utf-8
"""
睡眠データ分析ライブラリ

Fitbit APIから取得した睡眠データの統計分析を行う。
可視化は sleep_plots.py 側にある。
"""

import pandas as pd

from .summary_integrity import STAGE_GAP_THRESHOLD_MINUTES, split_by_integrity


# =============================================================================
# 定数
# =============================================================================

# 睡眠ステージの色設定（Fitbitアプリ風）
STAGE_COLORS = {
    'wake': '#FF9500',   # オレンジ
    'rem': '#9B59B6',    # 紫
    'light': '#5DADE2',  # 水色
    'deep': '#2E4053',   # 濃紺
    'asleep': '#5DADE2', # 水色（古いフォーマット、lightと同じ扱い）
    'restless': '#FFB74D',  # 薄いオレンジ（古いフォーマット）
    'awake': '#FF9500',  # オレンジ（古いフォーマット、wakeと同じ扱い）
}

# Y軸の位置（上から wake, rem, light, deep）
STAGE_Y_POSITION = {
    'wake': 3,
    'rem': 2,
    'light': 1,
    'deep': 0,
    'asleep': 1,  # 古いフォーマット、lightと同じ位置
    'restless': 3,  # 古いフォーマット、wakeと同じ位置
    'awake': 3,  # 古いフォーマット、wakeと同じ位置
}


# =============================================================================
# 統計分析
# =============================================================================

def _time_to_minutes(dt):
    """datetimeを0:00からの分数に変換（深夜跨ぎ対応）"""
    minutes = dt.hour * 60 + dt.minute
    # 18時以降は前日扱い（負の値にして平均計算を正しくする）
    if minutes >= 18 * 60:
        minutes -= 24 * 60
    return minutes


def _minutes_to_time_str(minutes):
    """分数を HH:MM 形式に変換"""
    if minutes < 0:
        minutes += 24 * 60
    hours = int(minutes // 60) % 24
    mins = int(minutes % 60)
    return f"{hours:02d}:{mins:02d}"


def calc_sleep_stats(df_master, recommended_hours=7.0):
    """
    睡眠サマリーデータから基本統計を計算

    Fitbitの睡眠サマリには、ステージ内訳（deep+light+rem）とminutesAsleepが
    大きく乖離するレコードが混在する（#65）。壊れているのはminutesAsleepと
    efficiency側で、ステージ内訳は生タイムラインと整合しているため、
    duration/efficiencyは乖離行を除外して計算し、stagesは全行から計算する。

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame
        recommended_hours: 推奨睡眠時間（デフォルト7時間）

    Returns:
        dict: 統計情報
    """
    df = df_master.copy()
    df['sleepHours'] = df['minutesAsleep'] / 60

    df_clean, df_inconsistent = split_by_integrity(df_master)
    fallback = len(df_clean) == 0
    df_for_duration = df if fallback else df_clean.copy()
    df_for_duration['sleepHours'] = df_for_duration['minutesAsleep'] / 60

    stats = {
        'period': {
            'start': df['dateOfSleep'].min() if 'dateOfSleep' in df.columns else df.index.min(),
            'end': df['dateOfSleep'].max() if 'dateOfSleep' in df.columns else df.index.max(),
            'days': len(df),
        },
        'duration': {
            'mean_hours': df_for_duration['sleepHours'].mean(),
            'mean_minutes': df_for_duration['minutesAsleep'].mean(),
            'min_hours': df_for_duration['sleepHours'].min(),
            'max_hours': df_for_duration['sleepHours'].max(),
            'std_hours': df_for_duration['sleepHours'].std(),
        },
        'efficiency': {
            'mean': df_for_duration['efficiency'].mean(),
            'min': df_for_duration['efficiency'].min(),
            'max': df_for_duration['efficiency'].max(),
        },
        'stages': {
            'deep_minutes': df['deepMinutes'].mean(),
            'light_minutes': df['lightMinutes'].mean(),
            'rem_minutes': df['remMinutes'].mean(),
            'wake_minutes': df['wakeMinutes'].mean(),
            'deep_count': df['deepCount'].mean(),
            'light_count': df['lightCount'].mean(),
            'rem_count': df['remCount'].mean(),
        },
        'integrity': {
            'total': len(df_master),
            'excluded': len(df_inconsistent),
            'threshold_minutes': STAGE_GAP_THRESHOLD_MINUTES,
        },
    }
    if fallback:
        stats['integrity']['fallback'] = True

    # ステージ割合を計算
    total = stats['duration']['mean_minutes']
    if total > 0:
        stats['stages']['deep_pct'] = stats['stages']['deep_minutes'] / total * 100
        stats['stages']['light_pct'] = stats['stages']['light_minutes'] / total * 100
        stats['stages']['rem_pct'] = stats['stages']['rem_minutes'] / total * 100

    # 就寝・起床時刻の統計
    if 'startTime' in df.columns and 'endTime' in df.columns:
        df['startTime_dt'] = pd.to_datetime(df['startTime'])
        df['endTime_dt'] = pd.to_datetime(df['endTime'])

        bedtime_minutes = df['startTime_dt'].apply(_time_to_minutes)
        waketime_minutes = df['endTime_dt'].apply(_time_to_minutes)

        stats['bedtime'] = {
            'mean': _minutes_to_time_str(bedtime_minutes.mean()),
            'std_minutes': bedtime_minutes.std(),
            'earliest': _minutes_to_time_str(bedtime_minutes.min()),
            'latest': _minutes_to_time_str(bedtime_minutes.max()),
        }
        stats['waketime'] = {
            'mean': _minutes_to_time_str(waketime_minutes.mean()),
            'std_minutes': waketime_minutes.std(),
            'earliest': _minutes_to_time_str(waketime_minutes.min()),
            'latest': _minutes_to_time_str(waketime_minutes.max()),
        }

    # 睡眠負債の計算
    recommended_minutes = recommended_hours * 60
    df['sleep_debt_minutes'] = df['minutesAsleep'] - recommended_minutes
    stats['sleep_debt'] = {
        'total_minutes': df['sleep_debt_minutes'].sum(),
        'total_hours': df['sleep_debt_minutes'].sum() / 60,
        'daily_avg_minutes': df['sleep_debt_minutes'].mean(),
        'recommended_hours': recommended_hours,
        'days_met_goal': (df['minutesAsleep'] >= recommended_minutes).sum(),
    }

    # 週間合計
    stats['weekly_total'] = {
        'time_in_bed_minutes': df['timeInBed'].sum(),
        'time_in_bed_hours': df['timeInBed'].sum() / 60,
        'minutes_asleep': df['minutesAsleep'].sum(),
        'hours_asleep': df['minutesAsleep'].sum() / 60,
    }

    return stats


def calc_time_stats(times):
    """
    datetime型のリストから時刻統計を計算

    Args:
        times: datetime型のリスト

    Returns:
        dict: 平均・最早・最遅・標準偏差を含む辞書
    """
    if not times:
        return {}

    minutes_list = [_time_to_minutes(t) for t in times]
    mean_min = sum(minutes_list) / len(minutes_list)
    std_min = (sum((m - mean_min) ** 2 for m in minutes_list) / len(minutes_list)) ** 0.5

    return {
        'mean': _minutes_to_time_str(mean_min),
        'earliest': _minutes_to_time_str(min(minutes_list)),
        'latest': _minutes_to_time_str(max(minutes_list)),
        'std_minutes': std_min,
    }


def calc_sleep_timing(df_levels):
    """
    睡眠レベルデータから入眠潜時と起床後時間を計算

    Args:
        df_levels: sleep_levels.csvを読み込んだDataFrame

    Returns:
        dict: 日付をキーとした入眠潜時・起床後時間の辞書
    """
    df = df_levels.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['dateTime']):
        df['dateTime'] = pd.to_datetime(df['dateTime'])

    results = {}
    for date in df['dateOfSleep'].unique():
        day = df[df['dateOfSleep'] == date].sort_values('dateTime')
        main_sleep = day[day['isShort'] == False]

        if len(main_sleep) == 0:
            continue

        # 入眠潜時: 最初がwakeなら、そのseconds
        first = main_sleep.iloc[0]
        fall_asleep = first['seconds'] / 60 if first['level'] == 'wake' else 0

        # 起床後: 最後がwakeなら、そのseconds
        last = main_sleep.iloc[-1]
        after_wake = last['seconds'] / 60 if last['level'] == 'wake' else 0

        results[date] = {
            'minutes_to_fall_asleep': fall_asleep,
            'minutes_after_wakeup': after_wake,
        }

    return results


def calc_recovery_score(df_master):
    """
    筋トレ向け回復スコアを計算

    深い睡眠（成長ホルモン分泌）、睡眠効率、睡眠時間から
    筋肉回復に適した睡眠かを0-100のスコアで評価する。

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame

    Returns:
        dict: 回復スコアと各指標
    """
    df = df_master.copy()

    # 基本統計
    avg_sleep_hours = df['minutesAsleep'].mean() / 60
    avg_efficiency = df['efficiency'].mean()
    avg_deep_minutes = df['deepMinutes'].mean()
    avg_rem_minutes = df['remMinutes'].mean()
    avg_light_minutes = df['lightMinutes'].mean()
    total_sleep_hours = df['minutesAsleep'].sum() / 60

    result = {
        'days': len(df),
        'avg_sleep_hours': avg_sleep_hours,
        'avg_efficiency': avg_efficiency,
        'avg_deep_minutes': avg_deep_minutes,
        'avg_rem_minutes': avg_rem_minutes,
        'avg_light_minutes': avg_light_minutes,
        'total_sleep_hours': total_sleep_hours,
    }

    # 深い睡眠・REMの割合
    total_sleep = df['minutesAsleep'].mean()
    if total_sleep > 0:
        result['deep_pct'] = avg_deep_minutes / total_sleep * 100
        result['rem_pct'] = avg_rem_minutes / total_sleep * 100
    else:
        result['deep_pct'] = 0
        result['rem_pct'] = 0

    # 回復スコア計算
    # 深い睡眠: 18%を100点（13-23%が推奨範囲の中央）
    # 効率: 85%を100点
    # 時間: 7時間を100点
    deep_score = min(result['deep_pct'] / 18 * 100, 100)
    efficiency_score = min(avg_efficiency / 85 * 100, 100)
    duration_score = min(avg_sleep_hours / 7 * 100, 100)

    result['recovery_score'] = deep_score * 0.4 + efficiency_score * 0.3 + duration_score * 0.3
    result['deep_score'] = deep_score
    result['efficiency_score'] = efficiency_score
    result['duration_score'] = duration_score

    return result


def print_sleep_stats(stats):
    """統計情報を整形して出力"""
    print("=== 睡眠データ基本情報 ===")
    print(f"期間: {stats['period']['start']} ～ {stats['period']['end']}")
    print(f"データ件数: {stats['period']['days']}日分\n")

    print("=== 睡眠時間の統計 ===")
    print(f"平均睡眠時間: {stats['duration']['mean_hours']:.1f}時間 ({stats['duration']['mean_minutes']:.0f}分)")
    print(f"最短: {stats['duration']['min_hours']:.1f}時間")
    print(f"最長: {stats['duration']['max_hours']:.1f}時間")
    print(f"標準偏差: {stats['duration']['std_hours']:.1f}時間\n")

    print("=== 睡眠効率 ===")
    print(f"平均効率: {stats['efficiency']['mean']:.1f}%")
    print(f"最低: {stats['efficiency']['min']}%")
    print(f"最高: {stats['efficiency']['max']}%\n")

    print("=== 睡眠ステージ平均 ===")
    print(f"深い睡眠: {stats['stages']['deep_minutes']:.0f}分 ({stats['stages'].get('deep_pct', 0):.1f}%)")
    print(f"浅い睡眠: {stats['stages']['light_minutes']:.0f}分 ({stats['stages'].get('light_pct', 0):.1f}%)")
    print(f"レム睡眠: {stats['stages']['rem_minutes']:.0f}分 ({stats['stages'].get('rem_pct', 0):.1f}%)")
    print(f"覚醒: {stats['stages']['wake_minutes']:.0f}分")

