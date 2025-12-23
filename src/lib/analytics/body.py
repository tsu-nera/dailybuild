#!/usr/bin/env python
# coding: utf-8
"""
体組成データ処理ライブラリ

LBM・FFMIの計算、統計、テーブル生成を提供。
"""

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from lib.templates.filters import format_change

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
    'protein': ('プロテイン', '.1f'),
    'sleep_hours': ('睡眠', '.1f'),
}

# デフォルト表示カラム（日別データ用）
DAILY_COLUMNS = [
    'weight', 'muscle_mass', 'body_fat_rate', 'body_fat_mass',
    'lbm', 'ffmi', 'visceral_fat_level', 'basal_metabolic_rate',
    'body_age', 'body_water_rate', 'calories_in', 'calories_out'
]

# 体組成テーブル用カラム
DAILY_BODY_COLUMNS = [
    'weight', 'muscle_mass', 'body_fat_rate', 'ffmi',
    'calorie_balance', 'protein', 'sleep_hours'
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

# 統合テーブル用カラム（本質的な指標のみ）
DAILY_ESSENTIAL_COLUMNS = [
    'weight', 'muscle_mass', 'body_fat_rate', 'calorie_balance', 'protein'
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


def format_daily_table(df, columns=None, date_format='%m-%d', custom_labels=None):
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
    custom_labels : dict, optional
        カラム名の表示ラベルを上書きする辞書 {column: label}

    Returns
    -------
    str
        Markdownテーブル文字列
    """
    if columns is None:
        columns = DAILY_COLUMNS
    if custom_labels is None:
        custom_labels = {}

    # 有効なカラムのみ
    valid_columns = [c for c in columns if c in COLUMN_CONFIG and c in df.columns]

    # ヘッダー生成（カスタムラベルがあれば上書き）
    headers = ['日付'] + [
        custom_labels.get(col, COLUMN_CONFIG[col][0]) for col in valid_columns
    ]
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


def merge_daily_data(df_body, nutrition_stats=None, activity_stats=None, sleep_df=None):
    """
    体組成データに栄養・アクティビティ・睡眠データをマージ

    Parameters
    ----------
    df_body : DataFrame
        体組成データ（date列必須）
    nutrition_stats : dict, optional
        栄養統計データ（daily配列を含む）
    activity_stats : dict, optional
        アクティビティ統計データ（daily配列を含む）
    sleep_df : DataFrame, optional
        睡眠データ（dateOfSleep, minutesAsleepカラムを含む）

    Returns
    -------
    DataFrame
        マージされた日別データ（calories_in, calories_out, calorie_balance, sleep_hoursカラムを含む）
    """
    df = df_body.copy()

    # 栄養データをマージ（摂取カロリー、プロテイン）
    if nutrition_stats and 'daily' in nutrition_stats:
        df_nutrition_daily = pd.DataFrame(nutrition_stats['daily'])
        df_nutrition_daily['date'] = pd.to_datetime(df_nutrition_daily['date'])
        # カロリーとプロテインを取得
        columns_to_merge = ['date', 'calories']
        rename_map = {'calories': 'calories_in'}
        if 'protein' in df_nutrition_daily.columns:
            columns_to_merge.append('protein')
        df_nutrition_daily = df_nutrition_daily[columns_to_merge].rename(
            columns=rename_map
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

    # 睡眠データをマージ（睡眠時間）
    if sleep_df is not None:
        df_sleep = sleep_df.copy()
        df_sleep['date'] = pd.to_datetime(df_sleep['dateOfSleep'])
        # 分を時間に変換
        df_sleep['sleep_hours'] = df_sleep['minutesAsleep'] / 60
        df_sleep_daily = df_sleep[['date', 'sleep_hours']]
        df = df.merge(df_sleep_daily, on='date', how='left')

    return df


def format_body_composition_section(df):
    """
    体組成セクションを生成（パターンA: 日別変化 + パターンB: 構成比）

    Parameters
    ----------
    df : DataFrame
        日別体組成データ（date, weight, muscle_mass, body_fat_mass, bone_mass列を含む）

    Returns
    -------
    str
        Markdown形式の体組成セクション
    """
    df = df.copy()

    # 前日比の差分を計算
    df['weight_diff'] = df['weight'].diff()
    df['muscle_diff'] = df['muscle_mass'].diff()
    df['fat_diff'] = df['body_fat_mass'].diff()
    df['bone_diff'] = df['bone_mass'].diff()

    # 筋肉割合の計算（体重増加分に占める筋肉の割合）
    df['muscle_ratio'] = (df['muscle_diff'] / df['weight_diff'] * 100).where(df['weight_diff'] != 0)

    # パターンA: 日別詳細テーブル
    table_rows = []
    table_rows.append("| 日付 | 体重 | 筋肉 | 脂肪 | 骨 | LBM | 体脂肪率 | 体水分率 |")
    table_rows.append("|------|------|------|------|-----|-----|----------|----------|")

    for _, row in df.iterrows():
        date_str = pd.to_datetime(row['date']).strftime('%m-%d')

        # 絶対量
        weight = row['weight']
        muscle = row['muscle_mass']
        fat = row['body_fat_mass']
        bone = row['bone_mass']
        lbm = row['lbm']

        # 比率（生データ）
        fat_pct = row['body_fat_rate']
        water_pct = row['body_water_rate']

        # フォーマット
        weight_str = f"{weight:.1f}"
        muscle_str = f"{muscle:.1f}"
        fat_str = f"{fat:.2f}"
        bone_str = f"{bone:.1f}"
        lbm_str = f"{lbm:.1f}"
        fat_pct_str = f"{fat_pct:.1f}%"
        water_pct_str = f"{water_pct:.1f}%" if pd.notna(water_pct) else "-"

        table_rows.append(
            f"| {date_str} | {weight_str} | {muscle_str} | {fat_str} | {bone_str} | {lbm_str} | {fat_pct_str} | {water_pct_str} |"
        )

    table_a = '\n'.join(table_rows)

    # セクション全体
    section = f"""## 🧬 体組成

{table_a}

"""

    return section


def plot_progress_chart(weekly_df, save_path, target_ffmi=21.0, monthly_weight_gain=0.75, current_weight=None, current_ffmi=None, height_cm=DEFAULT_HEIGHT_CM):
    """
    FFMI目標達成までの進捗グラフを生成

    Parameters
    ----------
    weekly_df : DataFrame
        週次集計データ（iso_year, iso_weekをインデックスに持つ）
    save_path : Path
        保存先パス
    target_ffmi : float
        目標FFMI
    monthly_weight_gain : float
        月間体重増加目標（kg）
    current_weight : float, optional
        現在の体重（Noneの場合は最新データから取得）
    current_ffmi : float, optional
        現在のFFMI（Noneの場合は最新データから取得）
    height_cm : float
        身長（cm）
    """
    # 現在値の取得
    if current_weight is None or current_ffmi is None:
        latest = weekly_df.iloc[-1]
        current_weight = latest['weight']
        current_ffmi = latest['ffmi']

    # 目標体重の計算（体脂肪率12.5%維持）
    # target_ffmi = lbm / (height_m^2) + 6.1 * (1.8 - height_m)
    # lbm = (target_ffmi - 6.1 * (1.8 - height_m)) * height_m^2
    height_m = height_cm / 100
    target_lbm = (target_ffmi - 6.1 * (1.8 - height_m)) * (height_m ** 2)
    target_weight = target_lbm / 0.875  # 体脂肪率12.5%維持

    # 到達期間の計算
    weight_diff = target_weight - current_weight
    months_to_target = weight_diff / monthly_weight_gain

    # 予測線の生成（現在から目標まで）
    weeks_to_target = int(months_to_target * 4.33)  # 月→週変換
    projection_weeks = np.arange(0, weeks_to_target + 1)
    projection_weight = current_weight + (projection_weeks / 4.33) * monthly_weight_gain

    # 予測FFMIの計算（体脂肪率12.5%維持）
    projection_lbm = projection_weight * 0.875
    projection_ffmi = projection_lbm / (height_m ** 2) + 6.1 * (1.8 - height_m)

    # 実績データの準備
    actual_weeks = np.arange(len(weekly_df))
    actual_weight = weekly_df['weight'].values
    actual_ffmi = weekly_df['ffmi'].values

    # グラフ描画
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=False)

    # 体重グラフ
    ax1.plot(actual_weeks, actual_weight, 'o-', color='#3498DB',
             label='Actual', linewidth=2, markersize=6)
    ax1.plot(actual_weeks[-1] + projection_weeks, projection_weight,
             '--', color='#95A5A6', label=f'Projection (+{monthly_weight_gain}kg/month)', linewidth=2)
    ax1.axhline(y=target_weight, color='#E74C3C', linestyle=':',
                label=f'Target Weight {target_weight:.1f}kg', linewidth=2)
    ax1.set_ylabel('Weight (kg)', fontsize=11)
    ax1.set_title('Weight Progress & Projection', fontsize=12, fontweight='bold')
    ax1.legend(loc='upper left')
    ax1.grid(axis='y', alpha=0.3)

    # FFMIグラフ
    ax2.plot(actual_weeks, actual_ffmi, 'o-', color='#2ECC71',
             label='Actual', linewidth=2, markersize=6)
    ax2.plot(actual_weeks[-1] + projection_weeks, projection_ffmi,
             '--', color='#95A5A6', label='Projection', linewidth=2)
    ax2.axhline(y=target_ffmi, color='#E74C3C', linestyle=':',
                label=f'Target FFMI {target_ffmi}', linewidth=2)
    ax2.set_xlabel('Week', fontsize=11)
    ax2.set_ylabel('FFMI', fontsize=11)
    ax2.set_title('FFMI Progress & Projection', fontsize=12, fontweight='bold')
    ax2.legend(loc='upper left')
    ax2.grid(axis='y', alpha=0.3)

    # テキスト情報を追加
    info_text = f'ETA: ~{months_to_target:.1f} months ({weeks_to_target} weeks)'
    fig.text(0.99, 0.01, info_text, ha='right', fontsize=9, style='italic', color='#7F8C8D')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()

    return {
        'target_weight': target_weight,
        'target_ffmi': target_ffmi,
        'months_to_target': months_to_target,
        'weeks_to_target': weeks_to_target,
    }
