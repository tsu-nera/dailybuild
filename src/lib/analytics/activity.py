#!/usr/bin/env python
# coding: utf-8
"""
アクティビティデータの分析ライブラリ

個別のアクティビティログからEAT（運動活動熱産生）を計算する。
"""

import pandas as pd


def calc_eat_stats_for_period(df_activity_logs):
    """
    アクティビティログからEAT統計を計算

    Args:
        df_activity_logs: アクティビティログのDataFrame
            必須カラム: startTime, calories, activityName

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
    if df_activity_logs is None or df_activity_logs.empty:
        return None

    # startTimeから日付を抽出
    df = df_activity_logs.copy()
    df['date'] = pd.to_datetime(df['startTime']).dt.date

    # 日別にグループ化してEATを計算
    daily_data = []
    for date, group in df.groupby('date'):
        # その日のアクティビティ詳細
        activities = []
        for _, row in group.iterrows():
            activities.append({
                'name': row['activityName'],
                'calories': row['calories'],
                'duration_min': row['durationMinutes'],
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


def calc_neat(df_daily):
    """
    NEAT（非運動性活動熱産生）を計算

    NEAT = activity_calories - EAT

    Args:
        df_daily: 日別データのDataFrame
            必須カラム: activity_calories, eat

    Returns:
        pandas.DataFrame: NEATカラムが追加されたDataFrame
    """
    df = df_daily.copy()

    # activity_caloriesとeatが両方あればNEATを計算
    if 'activity_calories' in df.columns and 'eat' in df.columns:
        df['neat'] = df['activity_calories'] - df['eat']
        # 負の値は0にする（データ不整合の場合）
        df['neat'] = df['neat'].clip(lower=0)
    else:
        df['neat'] = 0

    return df


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
