#!/usr/bin/env python
# coding: utf-8
"""
体組成データ処理ライブラリ

LBM・FFMIの計算、統計、テーブル生成を提供。
"""

import pandas as pd

# デフォルト身長 (cm)
DEFAULT_HEIGHT_CM = 170

# カラム設定: (表示名, フォーマット)
COLUMN_CONFIG = {
    'weight': ('体重', '.1f'),
    'muscle_mass': ('筋肉量', '.1f'),
    'body_fat_rate': ('体脂肪率', '.1f'),
    'body_fat_mass': ('体脂肪量', '.2f'),
    'lbm': ('除脂肪', '.1f'),
    'ffmi': ('FFMI', '.1f'),
    'visceral_fat_level': ('内臓脂肪', '.1f'),
    'basal_metabolic_rate': ('基礎代謝', '.0f'),
    'bone_mass': ('骨量', '.1f'),
    'body_age': ('体内年齢', '.0f'),
    'body_water_rate': ('体水分率', '.1f'),
    'muscle_quality_score': ('筋質点数', '.0f'),
}

# デフォルト表示カラム（日別データ用）
DAILY_COLUMNS = [
    'weight', 'muscle_mass', 'body_fat_rate', 'body_fat_mass',
    'lbm', 'ffmi', 'visceral_fat_level', 'basal_metabolic_rate',
    'bone_mass', 'body_age', 'body_water_rate', 'muscle_quality_score'
]

# サマリー用カラム
SUMMARY_COLUMNS = ['weight', 'muscle_mass', 'body_fat_rate', 'lbm', 'ffmi']


def calc_lbm(df):
    """
    LBM（除脂肪体重）を計算

    Parameters
    ----------
    df : DataFrame
        weight, body_fat_mass列を持つDataFrame

    Returns
    -------
    DataFrame
        lbm列を追加したDataFrame
    """
    df = df.copy()
    df['lbm'] = df['weight'] - df['body_fat_mass']
    return df


def calc_ffmi(df, height_cm=DEFAULT_HEIGHT_CM):
    """
    FFMI（除脂肪体重指数）を計算

    FFMI = LBM / (height_m^2) + 6.1 * (1.8 - height_m)

    Parameters
    ----------
    df : DataFrame
        lbm列を持つDataFrame
    height_cm : float
        身長 (cm)

    Returns
    -------
    DataFrame
        ffmi列を追加したDataFrame
    """
    df = df.copy()
    height_m = height_cm / 100
    df['ffmi'] = df['lbm'] / (height_m ** 2) + 6.1 * (1.8 - height_m)
    return df


def prepare_body_df(df, height_cm=DEFAULT_HEIGHT_CM):
    """
    体組成データフレームにLBM・FFMIを追加

    Parameters
    ----------
    df : DataFrame
        healthplanet_innerscan.csvを読み込んだDataFrame
    height_cm : float
        身長 (cm)

    Returns
    -------
    DataFrame
        LBM・FFMIカラムを追加したDataFrame
    """
    df = calc_lbm(df)
    df = calc_ffmi(df, height_cm)
    return df


def calc_body_stats(df, columns=None):
    """
    指定カラムの統計を計算

    Parameters
    ----------
    df : DataFrame
        体組成データ
    columns : list, optional
        計算するカラムのリスト（Noneの場合はSUMMARY_COLUMNS）

    Returns
    -------
    dict
        カラムごとの統計 {col: {first, last, change, mean}}
    """
    if columns is None:
        columns = SUMMARY_COLUMNS

    stats = {}
    for col in columns:
        if col in df.columns:
            vals = df[col].dropna()
            if len(vals) >= 1:
                stats[col] = {
                    'first': vals.iloc[0],
                    'last': vals.iloc[-1],
                    'change': vals.iloc[-1] - vals.iloc[0] if len(vals) > 1 else 0,
                    'mean': vals.mean(),
                }
    return stats


def format_daily_table(df, columns=None, date_format='%m-%d'):
    """
    体組成データをMarkdownテーブル形式でフォーマット

    Parameters
    ----------
    df : DataFrame
        体組成データ（date列必須）
    columns : list, optional
        表示するカラムのリスト（Noneの場合はDAILY_COLUMNS）
    date_format : str
        日付のフォーマット

    Returns
    -------
    str
        Markdownテーブル文字列
    """
    if columns is None:
        columns = DAILY_COLUMNS

    # 有効なカラムのみ
    valid_columns = [c for c in columns if c in COLUMN_CONFIG and c in df.columns]

    # ヘッダー生成
    headers = ['日付'] + [COLUMN_CONFIG[col][0] for col in valid_columns]
    header_row = '| ' + ' | '.join(headers) + ' |'
    separator_row = '|' + '|'.join(['------'] * len(headers)) + '|'

    # データ行生成
    data_rows = []
    for _, row in df.iterrows():
        date_str = pd.to_datetime(row['date']).strftime(date_format)
        values = [date_str]
        for col in valid_columns:
            fmt = COLUMN_CONFIG[col][1]
            values.append(f"{row[col]:{fmt}}")
        data_rows.append('| ' + ' | '.join(values) + ' |')

    return '\n'.join([header_row, separator_row] + data_rows)


def format_change(val, unit='', positive_is_good=True):
    """
    変化量をフォーマット

    Parameters
    ----------
    val : float
        変化量
    unit : str
        単位
    positive_is_good : bool
        プラスが良い変化かどうか（未使用、将来拡張用）

    Returns
    -------
    str
        フォーマットされた変化量
    """
    if val == 0:
        return f"±0{unit}"
    sign = '+' if val > 0 else ''
    return f"{sign}{val:.2f}{unit}"
