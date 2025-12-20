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
        - iso_year, iso_week, exercise_jp, volume, is_bodyweight, reps, set_index を含む

    Returns
    -------
    DataFrame
        週・エクササイズごとの集計結果
        Columns:
        - iso_year: int
        - iso_week: int
        - exercise_jp: str (チョコザップマシン名)
        - total_volume: float
        - total_reps: int (総レップ数)
        - total_sets: int (総セット数)
        - min_weight: float (最小重量)
        - max_weight: float (最大重量)
        - is_bodyweight: bool
        - week_over_week_diff: float (前週比volume)
        - reps_diff: float (前週比reps)
        - sets_diff: float (前週比sets)

    Notes
    -----
    - グルーピング: (iso_year, iso_week, exercise_jp)
    - 前週比は同じexercise_jp内で計算
    - 最初の週は NaN となる
    """
    # 週・エクササイズでグルーピング
    grouped = df.groupby(['iso_year', 'iso_week', 'exercise_jp']).agg({
        'volume': 'sum',
        'reps': 'sum',
        'set_index': 'count',
        'weight_kg': ['min', 'max'],
        'is_bodyweight': 'first',  # 同じエクササイズなら全て同じ
    }).reset_index()

    # マルチレベルカラムをフラット化
    grouped.columns = ['iso_year', 'iso_week', 'exercise_jp', 'total_volume', 'total_reps', 'total_sets', 'min_weight', 'max_weight', 'is_bodyweight']

    # エクササイズごとに前週比を計算
    grouped = grouped.sort_values(['exercise_jp', 'iso_year', 'iso_week'])
    grouped['week_over_week_diff'] = grouped.groupby('exercise_jp')['total_volume'].diff()
    grouped['reps_diff'] = grouped.groupby('exercise_jp')['total_reps'].diff()
    grouped['sets_diff'] = grouped.groupby('exercise_jp')['total_sets'].diff()

    return grouped


def calc_daily_stats(df):
    """
    日次トレーニング統計を計算

    Parameters
    ----------
    df : DataFrame
        標準化されたDataFrame（start_dt, end_dt, exercise_title, weight_kg, repsを含む）
        - start_dt, end_dt: datetime型
        - title: str (ワークアウトタイトル)
        - start_time, end_time: str (元の文字列形式)
        - exercise_title: str
        - weight_kg: float (nullable)
        - reps: int
        - set_index: int

    Returns
    -------
    DataFrame
        日ごとの統計
        Columns:
        - date: date (トレーニング日)
        - title: str (ワークアウトタイトル)
        - start_time: str (開始時刻の文字列)
        - end_time: str (終了時刻の文字列)
        - duration_minutes: int (トレーニング時間、分)
        - exercise_count: int (種目数)
        - total_reps: int (総レップ数)
        - total_sets: int (総セット数)
        - total_volume_kg: float (総ボリューム)

    Notes
    -----
    - 日付は start_dt から抽出
    - ボリュームは weight_kg × reps で計算
    - 結果は日付降順でソート
    """
    df = df.copy()

    # 日付カラムを追加
    df['date'] = df['start_dt'].dt.date

    # ボリューム計算 (weight * reps)
    df['volume'] = df['weight_kg'].fillna(0) * df['reps']

    # 日次集計
    daily = df.groupby('date').agg(
        title=('title', 'first'),
        start_time=('start_time', 'first'),
        end_time=('end_time', 'first'),
        start_dt=('start_dt', 'min'),
        end_dt=('end_dt', 'max'),
        exercise_count=('exercise_title', 'nunique'),
        total_reps=('reps', 'sum'),
        total_sets=('set_index', 'count'),
        total_volume_kg=('volume', 'sum')
    ).reset_index()

    # トレーニング時間を計算（分単位）
    daily['duration_minutes'] = (
        (daily['end_dt'] - daily['start_dt']).dt.total_seconds() / 60
    ).astype(int)

    # カラムを整理（不要なカラムを削除）
    daily = daily[[
        'date',
        'title',
        'start_time',
        'end_time',
        'duration_minutes',
        'exercise_count',
        'total_reps',
        'total_sets',
        'total_volume_kg'
    ]]

    # 日付降順でソート
    daily = daily.sort_values('date', ascending=False)

    return daily


def calc_weekly_stats_from_daily(daily_df):
    """
    日次統計から週次統計を計算

    Parameters
    ----------
    daily_df : DataFrame
        calc_daily_stats()の出力、または同等のDataFrame
        - date: date型
        - duration_minutes: int
        - exercise_count: int
        - total_reps: int
        - total_sets: int
        - total_volume_kg: float

    Returns
    -------
    DataFrame
        週ごとの統計
        Columns:
        - iso_year: int
        - iso_week: int
        - training_days: int (トレーニング日数)
        - duration_minutes: int (週の総トレーニング時間、分)
        - exercise_count: int (種目数の合計)
        - total_reps: int (総レップ数)
        - total_sets: int (総セット数)
        - total_volume_kg: float (総ボリューム)

    Notes
    -----
    - 日次データを週単位で集計
    - exercise_countは週内の合計（ユニーク数ではない）
    - training_daysは週内のユニークな日付数
    - duration_minutesは週内の各日のトレーニング時間の合計
    """
    df = daily_df.copy()

    # dateをdatetime型に変換（必要な場合）
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'])

    # ISO週番号を追加
    df['iso_year'] = df['date'].dt.isocalendar().year
    df['iso_week'] = df['date'].dt.isocalendar().week

    # 週ごとに集計
    weekly = df.groupby(['iso_year', 'iso_week']).agg(
        training_days=('date', 'nunique'),
        duration_minutes=('duration_minutes', 'sum'),
        exercise_count=('exercise_count', 'sum'),
        total_reps=('total_reps', 'sum'),
        total_sets=('total_sets', 'sum'),
        total_volume_kg=('total_volume_kg', 'sum')
    ).reset_index()

    # カラム順序を整理
    weekly = weekly[[
        'iso_year',
        'iso_week',
        'training_days',
        'duration_minutes',
        'exercise_count',
        'total_reps',
        'total_sets',
        'total_volume_kg'
    ]]

    # 週番号でソート（降順）
    weekly = weekly.sort_values(['iso_year', 'iso_week'], ascending=False)

    return weekly


def calc_weekly_stats(df):
    """
    週次トレーニング統計を計算（全体のサマリー）

    Parameters
    ----------
    df : DataFrame
        prepare_workout_df()処理済みのDataFrame
        - iso_year, iso_week, volume, reps, is_bodyweight, start_dt, exercise_jp を含む

    Returns
    -------
    DataFrame
        週ごとの統計
        Columns:
        - iso_year: int
        - iso_week: int
        - training_days: int (トレーニング日数)
        - exercise_count: int (種目数)
        - total_reps: int (総レップ数)
        - total_sets: int (総セット数)
        - total_volume_kg: float (総ボリューム、重量ありのみ)

    Notes
    -----
    - ボリュームは重量ありエクササイズのみ集計（is_bodyweight=Falseのみ）
    - トレーニング日数は週内のユニークな日付数
    """
    # 週ごとに集計
    stats = df.groupby(['iso_year', 'iso_week']).agg({
        'exercise_jp': 'nunique',  # 種目数
        'reps': 'sum',  # 総レップ数
        'set_index': 'count',  # 総セット数（行数）
    }).reset_index()

    stats = stats.rename(columns={
        'exercise_jp': 'exercise_count',
        'reps': 'total_reps',
        'set_index': 'total_sets'
    })

    # トレーニング日数を計算（週内のユニークな日付数）
    df['training_date'] = df['start_dt'].dt.date
    training_days = df.groupby(['iso_year', 'iso_week'])['training_date'].nunique().reset_index()
    training_days = training_days.rename(columns={'training_date': 'training_days'})

    # 重量ありのボリュームのみを集計
    weighted_volume = df[~df['is_bodyweight']].groupby(['iso_year', 'iso_week'])['volume'].sum().reset_index()
    weighted_volume = weighted_volume.rename(columns={'volume': 'total_volume_kg'})

    # マージ
    stats = stats.merge(training_days, on=['iso_year', 'iso_week'], how='left')
    stats = stats.merge(weighted_volume, on=['iso_year', 'iso_week'], how='left')

    # NaNを0で埋める
    stats['total_volume_kg'] = stats['total_volume_kg'].fillna(0)
    stats['training_days'] = stats['training_days'].fillna(0).astype(int)

    # カラム順序を整理
    stats = stats[[
        'iso_year',
        'iso_week',
        'training_days',
        'exercise_count',
        'total_reps',
        'total_sets',
        'total_volume_kg'
    ]]

    return stats
