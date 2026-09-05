#!/usr/bin/env python
# coding: utf-8
"""
アクティビティデータの分析ライブラリ

exercise_source.load_sessions() が返す正規化済みセッションから
EAT（運動活動熱産生）・サイクリング・筋トレの日別集計を計算する。
"""

import pandas as pd

from lib import exercise_source


def calc_eat_stats_for_period(df_sessions):
    """
    運動セッションからEAT統計を計算

    Args:
        df_sessions: exercise_source.load_sessions() の戻り値
            必須カラム: start, calories, display_name, duration_min

    Returns:
        dict: 日別EATデータとサマリー統計
        {
            'daily': [{'date': '2025-12-01', 'eat': 200, 'activities': [...]}],
            'total_eat': 1400,
            'avg_eat': 100,
            'days': 14,
        }
        データがない場合はNone
    """
    if df_sessions is None or df_sessions.empty:
        return None

    df = df_sessions.copy()
    df['date'] = df['start'].dt.date

    # 日別にグループ化してEATを計算
    daily_data = []
    for date, group in df.groupby('date'):
        # その日のアクティビティ詳細
        activities = []
        for _, row in group.iterrows():
            activities.append({
                'name': row['display_name'],
                'calories': row['calories'],
                'duration_min': row['duration_min'],
            })

        daily_data.append({
            'date': date.strftime('%Y-%m-%d'),
            'eat': group['calories'].sum(),
            'activities': activities,
        })

    # ソート
    daily_data.sort(key=lambda x: x['date'])

    # サマリー統計
    total_eat = sum(d['eat'] for d in daily_data)
    days = len(daily_data)

    return {
        'daily': daily_data,
        'total_eat': total_eat,
        'avg_eat': total_eat / days if days > 0 else 0,
        'days': days,
    }


def calc_cycling_stats_for_period(df_sessions):
    """サイクリング日別集計（exercise_source.CYCLING_TYPES）

    Args:
        df_sessions: exercise_source.load_sessions() の戻り値
            必須カラム: start, exercise_type, duration_min, distance_km,
                       calories, average_heart_rate

    Returns:
        dict or None: {'daily': [{date, count, duration, distance_km,
                                   avg_hr, calories}, ...],
                       'total_distance_km': float, 'total_duration': int,
                       'days': int}
    """
    return _calc_sport_stats(
        df_sessions,
        types=exercise_source.CYCLING_TYPES,
        with_distance=True,
    )


def calc_strength_stats_for_period(df_sessions):
    """筋トレ日別集計（exercise_source.STRENGTH_TYPES）

    Args:
        df_sessions: exercise_source.load_sessions() の戻り値

    Returns:
        dict or None: {'daily': [{date, count, duration, avg_hr, calories}, ...],
                       'total_duration': int, 'days': int}
    """
    return _calc_sport_stats(
        df_sessions,
        types=exercise_source.STRENGTH_TYPES,
        with_distance=False,
    )


def _calc_sport_stats(df_sessions, types, with_distance):
    """指定 exercise_type の日別集計を生成"""
    if df_sessions is None or df_sessions.empty:
        return None

    df = df_sessions[df_sessions['exercise_type'].isin(types)].copy()
    if df.empty:
        return None

    df['date'] = df['start'].dt.date
    df['hr_x_dur'] = df['average_heart_rate'].fillna(0) * df['duration_min']
    df['has_hr_dur'] = df['average_heart_rate'].notna() * df['duration_min']

    daily = []
    for date, g in df.groupby('date'):
        dur = int(g['duration_min'].sum())
        cal = float(g['calories'].sum())
        hr_dur = g['has_hr_dur'].sum()
        avg_hr = float(g['hr_x_dur'].sum() / hr_dur) if hr_dur > 0 else None
        row = {
            'date': pd.Timestamp(date),
            'count': len(g),
            'duration': dur,
            'avg_hr': avg_hr,
            'calories': cal,
        }
        if with_distance:
            row['distance_km'] = float(g['distance_km'].sum())
        daily.append(row)

    daily.sort(key=lambda r: r['date'])

    result = {
        'daily': daily,
        'total_duration': sum(r['duration'] for r in daily),
        'days': len(daily),
    }
    if with_distance:
        result['total_distance_km'] = sum(r['distance_km'] for r in daily)
    return result


def merge_eat_to_daily(df_daily, eat_stats):
    """
    日別データにEATを追加

    Args:
        df_daily: 日別データのDataFrame
        eat_stats: calc_eat_stats_for_periodの戻り値

    Returns:
        pandas.DataFrame: EATカラムが追加されたDataFrame
    """
    if eat_stats is None:
        df_daily['eat'] = 0
        return df_daily

    # EATの日別データをDataFrameに変換
    df_eat = pd.DataFrame(eat_stats['daily'])
    df_eat['date'] = pd.to_datetime(df_eat['date'])
    df_eat = df_eat[['date', 'eat']]

    # マージ
    df_daily['date'] = pd.to_datetime(df_daily['date'])
    df_merged = df_daily.merge(df_eat, on='date', how='left')
    df_merged['eat'] = df_merged['eat'].fillna(0)

    return df_merged


def calc_tef(df_daily):
    """
    TEF（食事誘発性熱産生）を計算

    TEF ≈ 摂取カロリー × 0.1（一般的な推定値）

    摂取カロリーがない日は0とする。

    Args:
        df_daily: 日別データのDataFrame
            必須カラム: calories_in

    Returns:
        pandas.DataFrame: TEFカラムが追加されたDataFrame
    """
    df = df_daily.copy()

    # calories_inがあればTEFを計算
    if 'calories_in' in df.columns:
        # 摂取カロリーの10%をTEFとして推定
        df['tef'] = df['calories_in'].fillna(0) * 0.1
    else:
        df['tef'] = 0

    return df
