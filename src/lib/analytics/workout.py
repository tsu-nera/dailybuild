#!/usr/bin/env python
# coding: utf-8
"""
ワークアウトデータ分析ライブラリ

`scripts/hevy.py show` が使う週次集計（部位別セット数 / 種目別 e1RM / 腹囲）を提供。
"""

from pathlib import Path

import pandas as pd
import yaml

EXERCISE_MUSCLES_YAML = Path(__file__).resolve().parents[3] / 'config' / 'exercise_muscles.yaml'

# 部位コード → 表示名。yaml に無い値が来たらコードのままフォールバックする
MUSCLE_LABELS = {
    'chest': '胸',
    'back': '背中',
    'shoulders': '肩',
    'legs': '脚',
    'arms': '腕',
}


def load_muscle_mapping(yaml_path=EXERCISE_MUSCLES_YAML):
    """種目名（正規化後） → 部位コード のマッピングを yaml から読み込む"""
    with Path(yaml_path).open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    exercises = data.get('exercises') or {}
    return {name: info['muscle'] for name, info in exercises.items()}


def add_week_label(df, date_column='start_dt'):
    """ISO週ラベル（`YYYY-Wxx`）の列 week_label を追加する"""
    df = df.copy()
    iso = df[date_column].dt.isocalendar()
    df['week_label'] = iso['year'].astype(str) + '-W' + iso['week'].astype(int).map('{:02d}'.format)
    return df


def recent_iso_weeks(n, today=None):
    """直近 n 週の ISO週ラベルを古い→新しいの順で返す（今週を含む）

    記録の無い週も表に出すため、データではなく暦から週の一覧を作る。
    """
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.now().normalize()
    iso_today = today.isocalendar()
    monday_this_week = today - pd.Timedelta(days=int(iso_today.weekday) - 1)

    labels = []
    for i in range(n - 1, -1, -1):
        monday = monday_this_week - pd.Timedelta(days=7 * i)
        iso = monday.isocalendar()
        labels.append(f'{iso.year}-W{iso.week:02d}')
    return labels


def weekly_muscle_sets(df, muscle_map, week_labels):
    """
    週 × 部位のセット数、トレーニング日数、未マッピング種目を集計する

    Parameters
    ----------
    df : DataFrame
        parse_hevy_csv() 済みの DataFrame（start_dt, exercise_title を含む）
    muscle_map : dict
        exercise_title（正規化後） → 部位コード
    week_labels : list[str]
        表に出す週（古い→新しい）。この範囲外のセットは無視する

    Returns
    -------
    (sets_table, unmapped)
        sets_table : DataFrame
            index=week_labels、columns=部位コード（アルファベット順）+ 'training_days'。
            記録が1セットも無い週も 0 の行として含む
        unmapped : DataFrame
            columns=['exercise_title', 'sets']。yaml に無い種目とそのセット数
            （セット数降順）。無ければ空の DataFrame
    """
    df = add_week_label(df)
    df = df[df['week_label'].isin(week_labels)].copy()

    if df.empty:
        training_days = pd.Series(0, index=week_labels, dtype=int)
    else:
        training_days = (
            df.groupby('week_label')['start_dt']
            .apply(lambda s: s.dt.date.nunique())
            .reindex(week_labels, fill_value=0)
            .astype(int)
        )

    df['muscle'] = df['exercise_title'].map(muscle_map)
    unmapped_mask = df['muscle'].isna()

    unmapped = (
        df.loc[unmapped_mask]
        .groupby('exercise_title')
        .size()
        .reset_index(name='sets')
        .sort_values('sets', ascending=False)
        .reset_index(drop=True)
    )

    mapped = df.loc[~unmapped_mask]
    if mapped.empty:
        sets_table = pd.DataFrame(index=week_labels)
    else:
        sets_table = (
            mapped.groupby(['week_label', 'muscle'])
            .size()
            .unstack(fill_value=0)
        )
        sets_table = sets_table.reindex(week_labels, fill_value=0)
        sets_table = sets_table.reindex(columns=sorted(sets_table.columns), fill_value=0)

    sets_table['training_days'] = training_days

    return sets_table, unmapped


def calc_e1rm(weight_kg, reps):
    """Epley 式で 1レップ最大重量を推定する（自重は呼び出し側で除外する）"""
    return weight_kg * (1 + reps / 30)


def weekly_e1rm(df, week_labels):
    """
    種目別 e1RM の週次推移（その週の最大値）を計算する

    `weight_kg` が空（自重）のセットは計算から除外する。窓の中で1度も
    実施していない種目は結果に含めない（列が全て NaN になるので呼び出し側で
    dropna(axis=1, how='all') する想定）。

    Parameters
    ----------
    df : DataFrame
        parse_hevy_csv() 済みの DataFrame
    week_labels : list[str]
        表に出す週（古い→新しい）

    Returns
    -------
    DataFrame
        index=week_labels、columns=exercise_title。未実施セルは NaN
    """
    df = df[df['weight_kg'].notna()].copy()
    if df.empty:
        return pd.DataFrame(index=week_labels)

    df['e1rm'] = calc_e1rm(df['weight_kg'], df['reps'])
    df = add_week_label(df)
    df = df[df['week_label'].isin(week_labels)]

    if df.empty:
        return pd.DataFrame(index=week_labels)

    pivot = df.groupby(['week_label', 'exercise_title'])['e1rm'].max().unstack()
    pivot = pivot.reindex(week_labels)
    pivot = pivot.sort_index(axis=1)
    return pivot


def weekly_waist(measurements_df, week_labels):
    """
    腹囲（waist_cm）の週次推移。測定の無い週は NaN のままにし、前週の値で埋めない。
    同じ週に複数の測定があれば日付が最も新しいものを採る。

    Parameters
    ----------
    measurements_df : DataFrame
        parse_hevy_measurements() 済みの DataFrame（date, waist_cm を含む）
    week_labels : list[str]
        表に出す週（古い→新しい）

    Returns
    -------
    Series
        index=week_labels、値は waist_cm（float、未測定週は NaN）
    """
    df = measurements_df.dropna(subset=['waist_cm']).copy()
    if df.empty:
        return pd.Series(index=week_labels, dtype=float, name='waist_cm')

    df['date'] = pd.to_datetime(df['date'])
    df = add_week_label(df, date_column='date')
    df = df.sort_values('date')
    weekly = df.groupby('week_label')['waist_cm'].last()
    return weekly.reindex(week_labels)
