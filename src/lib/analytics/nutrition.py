#!/usr/bin/env python
# coding: utf-8
"""
栄養データの分析・統計計算
"""

import pandas as pd


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
