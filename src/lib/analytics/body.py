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
    'basal_metabolic_rate': ('BMR', '.0f'),
    'bone_mass': ('骨量', '.1f'),
    'body_age': ('体内年齢', '.0f'),
    'body_water_rate': ('体水分率', '.1f'),
    'muscle_quality_score': ('筋質点数', '.0f'),
    'calories_in': ('In', '.0f'),
    'calories_out': ('Out', '.0f'),
    'calorie_balance': ('Balance', '.0f'),
    'eat': ('EAT', '.0f'),
    'neat': ('NEAT', '.0f'),
    'tef': ('TEF', '.0f'),
    'activity_calories': ('活動C', '.0f'),
}

# デフォルト表示カラム（日別データ用）
DAILY_COLUMNS = [
    'weight', 'muscle_mass', 'body_fat_rate', 'body_fat_mass',
    'lbm', 'ffmi', 'visceral_fat_level', 'basal_metabolic_rate',
    'body_age', 'body_water_rate', 'calories_in', 'calories_out'
]

# 体組成テーブル用カラム
DAILY_BODY_COLUMNS = [
    'weight', 'muscle_mass', 'body_fat_rate',
    'visceral_fat_level', 'body_water_rate'
]

# カロリー収支テーブル用カラム
DAILY_CALORIE_COLUMNS = [
    'weight', 'basal_metabolic_rate', 'calories_in', 'calories_out', 'calorie_balance'
]

# カロリー分析テーブル用カラム（TDEE分解：BMR, NEAT, TEF, EAT）
DAILY_CALORIE_ANALYSIS_COLUMNS = [
    'weight', 'calorie_balance', 'calories_in', 'calories_out',
    'basal_metabolic_rate', 'neat', 'tef', 'eat'
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
            val = row[col]
            # NaNや欠損値は「-」で表示
            if pd.isna(val):
                values.append('-')
            else:
                fmt = COLUMN_CONFIG[col][1]
                values.append(f"{val:{fmt}}")
        data_rows.append('| ' + ' | '.join(values) + ' |')

    return '\n'.join([header_row, separator_row] + data_rows)


def merge_daily_data(df_body, nutrition_stats=None, activity_stats=None):
    """
    体組成データに栄養・アクティビティデータをマージ

    Parameters
    ----------
    df_body : DataFrame
        体組成データ（date列必須）
    nutrition_stats : dict, optional
        栄養統計データ（daily配列を含む）
    activity_stats : dict, optional
        アクティビティ統計データ（daily配列を含む）

    Returns
    -------
    DataFrame
        マージされた日別データ（calories_in, calories_out, calorie_balanceカラムを含む）
    """
    df = df_body.copy()

    # 栄養データをマージ（摂取カロリー）
    if nutrition_stats and 'daily' in nutrition_stats:
        df_nutrition_daily = pd.DataFrame(nutrition_stats['daily'])
        df_nutrition_daily['date'] = pd.to_datetime(df_nutrition_daily['date'])
        df_nutrition_daily = df_nutrition_daily[['date', 'calories']].rename(
            columns={'calories': 'calories_in'}
        )
        df = df.merge(df_nutrition_daily, on='date', how='left')

    # アクティビティデータをマージ（消費カロリー）
    if activity_stats and 'daily' in activity_stats:
        df_activity_daily = pd.DataFrame(activity_stats['daily'])
        df_activity_daily['date'] = pd.to_datetime(df_activity_daily['date'])
        # caloriesOutとactivityCaloriesをマージ
        columns_to_merge = ['date', 'caloriesOut']
        rename_map = {'caloriesOut': 'calories_out'}
        if 'activityCalories' in df_activity_daily.columns:
            columns_to_merge.append('activityCalories')
            rename_map['activityCalories'] = 'activity_calories'
        df_activity_daily = df_activity_daily[columns_to_merge].rename(
            columns=rename_map
        )
        df = df.merge(df_activity_daily, on='date', how='left')

    # カロリー収支を計算（摂取 - 消費）
    if 'calories_in' in df.columns and 'calories_out' in df.columns:
        df['calorie_balance'] = df['calories_in'] - df['calories_out']

    return df


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
