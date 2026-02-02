#!/usr/bin/env python
# coding: utf-8
"""
栄養データの分析・統計計算

主要な機能:
- 栄養統計の計算
- グリセミック負荷（GL）の予測（Pongutta et al., 2021）
- 血糖値インパクトスコア
"""

import pandas as pd
import numpy as np

# ============================================================================
# Fitbit mealTypeId 定義
# ============================================================================

MEAL_TYPE_BREAKFAST = 1      # 朝食
MEAL_TYPE_MORNING_SNACK = 2  # 午前の間食
MEAL_TYPE_LUNCH = 3          # 昼食
MEAL_TYPE_AFTERNOON_SNACK = 4  # 午後の間食
MEAL_TYPE_DINNER = 5         # 夕食
MEAL_TYPE_EVENING_SNACK = 6  # 夜の間食
MEAL_TYPE_ANYTIME = 7        # 任意

# 夜の食事（睡眠に影響する食事タイミング）
MEAL_TYPE_EVENING = [MEAL_TYPE_DINNER, MEAL_TYPE_EVENING_SNACK]


def calc_nutrition_stats_for_period(df_nutrition):
    """
    指定期間の栄養統計を計算

    Parameters
    ----------
    df_nutrition : pd.DataFrame
        栄養データ（dateカラム必須）

    Returns
    -------
    dict or None
        栄養統計。データがない場合はNone
    """
    if df_nutrition is None or len(df_nutrition) == 0:
        return None

    # カロリーが0より大きい日のみでフィルタ（記録がある日のみ）
    df_recorded = df_nutrition[df_nutrition['calories'] > 0].copy()

    if len(df_recorded) == 0:
        return None

    # 統計を計算
    avg_calories = df_recorded['calories'].mean()
    avg_carbs = df_recorded['carbs'].mean()
    avg_fat = df_recorded['fat'].mean()
    avg_protein = df_recorded['protein'].mean()

    # PFC比率（カロリーベース）
    # 炭水化物: 4kcal/g, 脂質: 9kcal/g, タンパク質: 4kcal/g
    carbs_pct = (avg_carbs * 4 / avg_calories * 100) if avg_calories > 0 else 0
    fat_pct = (avg_fat * 9 / avg_calories * 100) if avg_calories > 0 else 0
    protein_pct = (avg_protein * 4 / avg_calories * 100) if avg_calories > 0 else 0

    # 日別データにPFC比率を追加
    daily_data = []
    for _, row in df_nutrition.iterrows():
        cal = row['calories']
        if cal > 0:
            p_pct = (row['protein'] * 4 / cal * 100)
            f_pct = (row['fat'] * 9 / cal * 100)
            c_pct = (row['carbs'] * 4 / cal * 100)
        else:
            p_pct = None
            f_pct = None
            c_pct = None

        daily_data.append({
            'date': row['date'],
            'calories': row['calories'],
            'protein': row['protein'],
            'fat': row['fat'],
            'carbs': row['carbs'],
            'fiber': row['fiber'],
            'sodium': row['sodium'],
            'water': row['water'],
            'p_pct': p_pct,
            'f_pct': f_pct,
            'c_pct': c_pct,
        })

    return {
        'days': len(df_nutrition),
        'recorded_days': len(df_recorded),
        'avg_calories': avg_calories,
        'avg_carbs': avg_carbs,
        'avg_fat': avg_fat,
        'avg_fiber': df_recorded['fiber'].mean(),
        'avg_protein': avg_protein,
        'avg_sodium': df_recorded['sodium'].mean(),
        'avg_water': df_recorded['water'].mean(),
        # PFC比率（カロリーベース）
        'carbs_pct': carbs_pct,
        'fat_pct': fat_pct,
        'protein_pct': protein_pct,
        # 日別データ（PFC比率含む）
        'daily': daily_data,
    }


# ============================================================================
# グリセミック負荷（GL）予測
# ============================================================================

def calc_predicted_gl(carbs, fiber, protein, fat):
    """
    研究ベースのグリセミック負荷（GL）予測式

    出典: Pongutta et al. (2021)
    "Development of a Prediction Model to Estimate the Glycemic Load
    of Ready-to-Eat Meals"
    Foods 10(11), 2626
    https://doi.org/10.3390/foods10112626

    検証結果: R² = 0.82

    Parameters
    ----------
    carbs : float
        炭水化物 (g)
    fiber : float
        食物繊維 (g)
    protein : float
        タンパク質 (g)
    fat : float
        脂質 (g)

    Returns
    -------
    float
        予測グリセミック負荷
        - 低 (< 10): 血糖値への影響が小さい
        - 中 (10-20): 中程度の血糖値上昇
        - 高 (> 20): 大きな血糖値上昇

    Notes
    -----
    予測式:
    GL = 19.27 + (0.39 × AC) - (0.21 × Fat)
         - (0.01 × Protein²) - (0.01 × Fiber²)

    where AC (Available Carbohydrate) = Carbs - Fiber

    タンパク質と食物繊維は二次項で、非線形効果（飽和効果）を反映
    """
    # 利用可能炭水化物（正味炭水化物）
    available_carbs = max(0, carbs - fiber)

    # GL予測式
    gl = (19.27 +
          0.39 * available_carbs -
          0.21 * fat -
          0.01 * (protein ** 2) -
          0.01 * (fiber ** 2))

    # 負の値は0に
    return max(0, gl)


def categorize_gl(gl):
    """
    グリセミック負荷をカテゴリに分類

    Parameters
    ----------
    gl : float
        グリセミック負荷

    Returns
    -------
    str
        カテゴリラベル（'低', '中', '高'）
    """
    if gl < 10:
        return "低"
    elif gl < 20:
        return "中"
    else:
        return "高"


def add_glycemic_scores(df_nutrition):
    """
    栄養データフレームにGLスコアを追加

    Parameters
    ----------
    df_nutrition : pd.DataFrame
        carbs, fiber, protein, fatを含む栄養データ

    Returns
    -------
    pd.DataFrame
        predicted_gl, gl_categoryが追加されたデータフレーム

    Examples
    --------
    >>> df = pd.read_csv('nutrition.csv')
    >>> df = add_glycemic_scores(df)
    >>> print(df[['date', 'predicted_gl', 'gl_category']].head())
    """
    df = df_nutrition.copy()

    # GL計算
    df['predicted_gl'] = df.apply(
        lambda row: calc_predicted_gl(
            row['carbs'], row['fiber'],
            row['protein'], row['fat']
        ), axis=1
    )

    # カテゴリ分類
    df['gl_category'] = df['predicted_gl'].apply(categorize_gl)

    return df


def analyze_glycemic_impact(df_nutrition):
    """
    グリセミック負荷の詳細分析

    Parameters
    ----------
    df_nutrition : pd.DataFrame
        栄養データ（calories > 0の日のみ）

    Returns
    -------
    dict
        GL統計とカテゴリ別の情報

    Examples
    --------
    >>> df = pd.read_csv('nutrition.csv')
    >>> df_valid = df[df['calories'] > 0]
    >>> analysis = analyze_glycemic_impact(df_valid)
    >>> print(f"Average GL: {analysis['avg_gl']:.1f}")
    """
    if df_nutrition is None or len(df_nutrition) == 0:
        return None

    # GLスコアを追加
    df = add_glycemic_scores(df_nutrition)

    # 統計計算
    avg_gl = df['predicted_gl'].mean()
    median_gl = df['predicted_gl'].median()
    min_gl = df['predicted_gl'].min()
    max_gl = df['predicted_gl'].max()
    std_gl = df['predicted_gl'].std()

    # カテゴリ別の集計
    category_counts = df['gl_category'].value_counts().to_dict()

    # カテゴリ別の栄養素平均
    category_nutrients = {}
    for category in ['低', '中', '高']:
        if category in df['gl_category'].values:
            cat_df = df[df['gl_category'] == category]
            category_nutrients[category] = {
                'count': len(cat_df),
                'avg_carbs': cat_df['carbs'].mean(),
                'avg_fiber': cat_df['fiber'].mean(),
                'avg_protein': cat_df['protein'].mean(),
                'avg_fat': cat_df['fat'].mean(),
                'avg_gl': cat_df['predicted_gl'].mean(),
            }

    return {
        'avg_gl': avg_gl,
        'median_gl': median_gl,
        'min_gl': min_gl,
        'max_gl': max_gl,
        'std_gl': std_gl,
        'category_counts': category_counts,
        'category_nutrients': category_nutrients,
        'daily_data': df.to_dict('records')
    }


# ============================================================================
# 夜の食事のみのGL計算（nutrition_logs.csv）
# ============================================================================

def calc_evening_gl_from_logs(logs_csv_path):
    """
    nutrition_logs.csvから夜の食事（夕食+夜の間食）のGLを計算

    夜の食事として、夕食（mealTypeId=5）と夜の間食（mealTypeId=6）を対象とします。

    Parameters
    ----------
    logs_csv_path : str
        nutrition_logs.csvのパス

    Returns
    -------
    pd.DataFrame
        日付（date）とevening_gl, evening_gl_categoryを含むデータフレーム
        データがない場合は空のDataFrame

    Examples
    --------
    >>> df_evening = calc_evening_gl_from_logs('data/fitbit/nutrition_logs.csv')
    >>> print(df_evening[['date', 'evening_gl', 'evening_gl_category']])
    """
    import os

    # ファイルが存在しない場合は空のDataFrameを返す
    if not os.path.exists(logs_csv_path):
        return pd.DataFrame(columns=['date', 'evening_gl', 'evening_gl_category'])

    # nutrition_logs.csvを読み込む
    try:
        df_logs = pd.read_csv(logs_csv_path)
    except Exception as e:
        print(f"Warning: Could not read {logs_csv_path}: {e}")
        return pd.DataFrame(columns=['date', 'evening_gl', 'evening_gl_category'])

    if len(df_logs) == 0:
        return pd.DataFrame(columns=['date', 'evening_gl', 'evening_gl_category'])

    # 夕食と夜の間食のみフィルタ
    df_evening = df_logs[df_logs['mealTypeId'].isin(MEAL_TYPE_EVENING)].copy()

    if len(df_evening) == 0:
        return pd.DataFrame(columns=['date', 'evening_gl', 'evening_gl_category'])

    # logDateをdateに変換
    df_evening['date'] = pd.to_datetime(df_evening['logDate']).dt.date

    # 栄養素カラムがNaNの場合は0に
    nutrient_cols = ['calories', 'protein', 'fat', 'carbs', 'fiber', 'sodium']
    for col in nutrient_cols:
        if col in df_evening.columns:
            df_evening[col] = df_evening[col].fillna(0)

    # 日付ごとにグループ化して栄養素を合計
    evening_daily = df_evening.groupby('date').agg({
        'calories': 'sum',
        'carbs': 'sum',
        'fiber': 'sum',
        'protein': 'sum',
        'fat': 'sum',
    }).reset_index()

    # evening_glを計算
    evening_daily['evening_gl'] = evening_daily.apply(
        lambda row: calc_predicted_gl(
            row['carbs'], row['fiber'],
            row['protein'], row['fat']
        ), axis=1
    )

    # evening_gl_categoryを追加
    evening_daily['evening_gl_category'] = evening_daily['evening_gl'].apply(categorize_gl)

    # 必要なカラムのみ返す
    return evening_daily[['date', 'evening_gl', 'evening_gl_category']]


def add_evening_gl_to_nutrition(df_nutrition, logs_csv_path):
    """
    栄養データに夜の食事のみのGLを追加

    Parameters
    ----------
    df_nutrition : pd.DataFrame
        栄養データ（dateカラム必須）
    logs_csv_path : str
        nutrition_logs.csvのパス

    Returns
    -------
    pd.DataFrame
        evening_gl, evening_gl_categoryが追加されたデータフレーム
        データがない場合はNaN

    Examples
    --------
    >>> df = pd.read_csv('data/fitbit/nutrition.csv')
    >>> df = add_evening_gl_to_nutrition(df, 'data/fitbit/nutrition_logs.csv')
    >>> print(df[['date', 'predicted_gl', 'evening_gl']])
    """
    # 夜の食事のGLを計算
    df_evening = calc_evening_gl_from_logs(logs_csv_path)

    df = df_nutrition.copy()

    if len(df_evening) == 0:
        # データがない場合はNaNカラムを追加
        df['evening_gl'] = np.nan
        df['evening_gl_category'] = np.nan
        return df

    # dateカラムを統一（Timestamp型で統一）
    # df_eveningのdateは現在date型なので、Timestampに変換
    df_evening['date'] = pd.to_datetime(df_evening['date'])

    # df['date']が既にTimestamp型の場合はそのまま、そうでない場合は変換
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'])

    # 結合
    df = df.merge(df_evening, on='date', how='left')

    return df
