#!/usr/bin/env python
# coding: utf-8
"""
ワークアウトデータ分析ライブラリ

データソース非依存のtraining volume計算・週次集計・統計分析を提供。

Training Volume:
- 重量エクササイズ: weight_kg × reps
- 自重エクササイズ: reps のみ
"""

import pandas as pd
import numpy as np


# チョコザップマシン名マッピング（Hevy → チョコザップ）
CHOCOZAP_MACHINE_MAPPING = {
    'Seated Shoulder Press (Machine)': 'ショルダープレス',
    'Lat Pulldown (Machine)': 'ラットプルダウン',
    'Seated Dip Machine': 'ディップス',
    'Preacher Curl (Machine)': 'バイセップスカール',
    'Leg Press Horizontal (Machine)': 'レッグプレス',
    'Chest Press (Machine)': 'チェストプレス',
}


def calc_training_volume(row):
    """
    1セットのTraining Volumeを計算（データソース非依存）

    Parameters
    ----------
    row : Series
        DataFrameの1行（weight_kg, repsを含む）

    Returns
    -------
    float
        Training Volume
        - 重量あり: weight_kg × reps
        - 自重: reps のみ
    """
    if pd.notna(row['weight_kg']):
        return row['weight_kg'] * row['reps']
    else:
        return float(row['reps'])


def prepare_workout_df(df):
    """
    ワークアウトデータフレームに分析用カラムを追加

    Parameters
    ----------
    df : DataFrame
        標準化されたDataFrame（start_dt, exercise_title, weight_kg, repsを含む）
        - start_dt: datetime型
        - exercise_title: str
        - weight_kg: float (nullable)
        - reps: int

    Returns
    -------
    DataFrame
        ISO週番号・volume・is_bodyweight・exercise_jp列を追加したDataFrame

    Notes
    -----
    - ISO週番号は月曜始まり〜日曜終わり
    - volumeは calc_training_volume() で計算
    - is_bodyweight は weight_kg が NaN かどうかで判定
    - exercise_jpはチョコザップのマシン名（日本語）
    """
    df = df.copy()

    # チョコザップマシン名に変換
    df['exercise_jp'] = df['exercise_title'].map(CHOCOZAP_MACHINE_MAPPING).fillna(df['exercise_title'])

    # ISO週番号を追加（月曜始まり）
    df['iso_year'] = df['start_dt'].dt.isocalendar().year
    df['iso_week'] = df['start_dt'].dt.isocalendar().week

    # Training Volume計算
    df['volume'] = df.apply(calc_training_volume, axis=1)

    # エクササイズタイプを判定（重量あり/自重）
    df['is_bodyweight'] = df['weight_kg'].isna()

    return df


def calc_weekly_volume(df):
    """
    週次・エクササイズごとのTraining Volume合計を計算

    Parameters
    ----------
    df : DataFrame
        prepare_workout_df()処理済みのDataFrame
        - iso_year, iso_week, exercise_jp, volume, is_bodyweight を含む

    Returns
    -------
    DataFrame
        週・エクササイズごとの集計結果
        Columns:
        - iso_year: int
        - iso_week: int
        - exercise_jp: str (チョコザップマシン名)
        - total_volume: float
        - is_bodyweight: bool
        - week_over_week_diff: float (前週比)

    Notes
    -----
    - グルーピング: (iso_year, iso_week, exercise_jp)
    - 前週比は同じexercise_jp内で計算
    - 最初の週は NaN となる
    """
    # 週・エクササイズでグルーピング
    grouped = df.groupby(['iso_year', 'iso_week', 'exercise_jp']).agg({
        'volume': 'sum',
        'is_bodyweight': 'first',  # 同じエクササイズなら全て同じ
    }).reset_index()

    grouped = grouped.rename(columns={'volume': 'total_volume'})

    # エクササイズごとに前週比を計算
    grouped = grouped.sort_values(['exercise_jp', 'iso_year', 'iso_week'])
    grouped['week_over_week_diff'] = grouped.groupby('exercise_jp')['total_volume'].diff()

    return grouped


def calc_weekly_stats(df):
    """
    週次トレーニング統計を計算（全体のサマリー）

    Parameters
    ----------
    df : DataFrame
        prepare_workout_df()処理済みのDataFrame
        - iso_year, iso_week, volume, reps, is_bodyweight, start_dt を含む

    Returns
    -------
    DataFrame
        週ごとの統計
        Columns:
        - iso_year: int
        - iso_week: int
        - training_days: int (トレーニング日数)
        - total_reps: int (総レップ数)
        - total_sets: int (総セット数)
        - total_volume: float (総ボリューム、重量ありのみ)

    Notes
    -----
    - ボリュームは重量ありエクササイズのみ集計（is_bodyweight=Falseのみ）
    - トレーニング日数は週内のユニークな日付数
    """
    # 週ごとに集計
    stats = df.groupby(['iso_year', 'iso_week']).agg({
        'reps': 'sum',  # 総レップ数
        'set_index': 'count',  # 総セット数（行数）
    }).reset_index()

    stats = stats.rename(columns={
        'reps': 'total_reps',
        'set_index': 'total_sets'
    })

    # トレーニング日数を計算（週内のユニークな日付数）
    df['training_date'] = df['start_dt'].dt.date
    training_days = df.groupby(['iso_year', 'iso_week'])['training_date'].nunique().reset_index()
    training_days = training_days.rename(columns={'training_date': 'training_days'})

    # 重量ありのボリュームのみを集計
    weighted_volume = df[~df['is_bodyweight']].groupby(['iso_year', 'iso_week'])['volume'].sum().reset_index()
    weighted_volume = weighted_volume.rename(columns={'volume': 'total_volume'})

    # マージ
    stats = stats.merge(training_days, on=['iso_year', 'iso_week'], how='left')
    stats = stats.merge(weighted_volume, on=['iso_year', 'iso_week'], how='left')

    # NaNを0で埋める
    stats['total_volume'] = stats['total_volume'].fillna(0)
    stats['training_days'] = stats['training_days'].fillna(0).astype(int)

    return stats
