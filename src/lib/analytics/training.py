#!/usr/bin/env python
# coding: utf-8
"""
トレーニング判断ロジック

科学的根拠:
- Kiviniemi et al. (2007): HRVベースのトレーニング処方
- Javaloyes et al. (2019): HRVガイドトレーニングアルゴリズム
- AHA (2025): Post-viral運動再開ガイドライン
"""

import pandas as pd
import numpy as np

from .sleep import flag_inconsistent


def calc_hrv_7day_rolling_stats(df_hrv, metric_col='daily_rmssd'):
    """
    HRVの7日移動平均と標準偏差を計算

    Parameters
    ----------
    df_hrv : DataFrame
        HRVデータ（date列がindex）
        必須カラム: metric_col（デフォルト: 'daily_rmssd'）
    metric_col : str
        統計を計算する対象カラム名

    Returns
    -------
    DataFrame
        以下のカラムを追加したDataFrame:
        - hrv_7day_mean: 7日移動平均
        - hrv_7day_std: 7日移動標準偏差
        - hrv_7day_lower: 正常範囲下限（mean - 0.5*std）
        - hrv_7day_upper: 正常範囲上限（mean + 0.5*std）

    References
    ----------
    Javaloyes et al. (2019) - HRVガイドトレーニングアルゴリズム
    """
    df = df_hrv.copy()

    # 7日移動平均・標準偏差を計算
    df['hrv_7day_mean'] = df[metric_col].rolling(window=7, min_periods=3).mean()
    df['hrv_7day_std'] = df[metric_col].rolling(window=7, min_periods=3).std()

    # 正常範囲（mean ± 0.5*std）
    df['hrv_7day_lower'] = df['hrv_7day_mean'] - 0.5 * df['hrv_7day_std']
    df['hrv_7day_upper'] = df['hrv_7day_mean'] + 0.5 * df['hrv_7day_std']

    return df


def should_workout_today(hrv_today, hrv_7day_mean, hrv_7day_std, sleep_efficiency=None):
    """
    HRVベースの筋トレ実施可否判断（Kiviniemiアルゴリズム）

    Parameters
    ----------
    hrv_today : float
        今日のHRV（RMSSD, ms）
    hrv_7day_mean : float
        7日移動平均
    hrv_7day_std : float
        7日移動標準偏差
    sleep_efficiency : float, optional
        昨夜の睡眠効率（%）

    Returns
    -------
    dict
        {
            'recommendation': str,  # 推奨アクション
            'intensity': str,       # 推奨強度（'rest', 'low', 'medium', 'high'）
            'reason': str,          # 理由
            'hrv_status': str,      # HRVステータス
        }

    References
    ----------
    - Kiviniemi et al. (2007): HRV-guided training
    - Javaloyes et al. (2019): Modified Kiviniemi algorithm (7day rolling avg ± 0.5*SD)
    """
    result = {
        'recommendation': '',
        'intensity': '',
        'reason': '',
        'hrv_status': '',
    }

    # データ不足チェック
    if pd.isna(hrv_today) or pd.isna(hrv_7day_mean) or pd.isna(hrv_7day_std):
        result['recommendation'] = 'データなし'
        result['intensity'] = 'unknown'
        result['reason'] = 'HRVデータが不足'
        result['hrv_status'] = '-'
        return result

    # Kiviniemiアルゴリズム: mean ± 0.5*SD
    lower_threshold = hrv_7day_mean - 0.5 * hrv_7day_std
    upper_threshold = hrv_7day_mean + 0.5 * hrv_7day_std

    # HRVベースの判断
    if hrv_today < lower_threshold:
        intensity = 'low'
        result['hrv_status'] = f'{hrv_today:.1f} < {lower_threshold:.1f}'
        result['recommendation'] = '休養または軽め（50%）'
        result['reason'] = 'HRVが7日平均より低い'
    elif hrv_today > upper_threshold:
        intensity = 'high'
        result['hrv_status'] = f'{hrv_today:.1f} > {upper_threshold:.1f}'
        result['recommendation'] = '通常トレーニングOK'
        result['reason'] = 'HRVが7日平均より高い'
    else:
        intensity = 'medium'
        result['hrv_status'] = f'{lower_threshold:.1f} ≤ {hrv_today:.1f} ≤ {upper_threshold:.1f}'
        result['recommendation'] = '中強度トレーニング（70%）'
        result['reason'] = 'HRVは正常範囲内'

    # 睡眠効率による補正（高強度→中強度への降格のみ）
    if sleep_efficiency is not None and sleep_efficiency < 80 and intensity == 'high':
        intensity = 'medium'
        result['recommendation'] = '中強度まで（睡眠不足）'
        result['reason'] += '、ただし睡眠効率が低い'

    result['intensity'] = intensity
    return result


def prepare_training_readiness_data(start_date, end_date, df_hrv, df_sleep=None):
    """
    筋トレ実施可否判断のための日別データを準備

    Parameters
    ----------
    start_date : pd.Timestamp
        開始日
    end_date : pd.Timestamp
        終了日
    df_hrv : DataFrame
        HRVデータ（7日移動統計を含む）
    df_sleep : DataFrame, optional
        睡眠データ（dateOfSleep列を含む）

    Returns
    -------
    list of dict
        日別の筋トレ判断データ
    """
    daily_data = []
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')

    # 睡眠データをdictに変換
    # サマリとステージ内訳が内部矛盾している行（#65）はefficiencyが壊れているため、
    # 該当行のefficiencyはNone（不明）として扱う。should_workout_todayはNoneを許容する。
    sleep_dict = {}
    if df_sleep is not None:
        inconsistent_flag = flag_inconsistent(df_sleep)
        for idx, row in df_sleep.iterrows():
            if inconsistent_flag.loc[idx]:
                row = row.copy()
                row['efficiency'] = None
            sleep_dict[row['dateOfSleep']] = row

    for date in date_range:
        row = {'date': date}

        # HRVデータを取得
        if date in df_hrv.index:
            hrv_row = df_hrv.loc[date]
            row['hrv_today'] = hrv_row.get('daily_rmssd')
            row['hrv_7day_mean'] = hrv_row.get('hrv_7day_mean')
            row['hrv_7day_std'] = hrv_row.get('hrv_7day_std')
            row['hrv_7day_lower'] = hrv_row.get('hrv_7day_lower')
            row['hrv_7day_upper'] = hrv_row.get('hrv_7day_upper')
        else:
            row['hrv_today'] = None
            row['hrv_7day_mean'] = None
            row['hrv_7day_std'] = None
            row['hrv_7day_lower'] = None
            row['hrv_7day_upper'] = None

        # 睡眠データを取得
        if date in sleep_dict:
            sleep_row = sleep_dict[date]
            row['sleep_efficiency'] = sleep_row.get('efficiency')
        else:
            row['sleep_efficiency'] = None

        # 筋トレ判断を実行
        judgment = should_workout_today(
            hrv_today=row['hrv_today'],
            hrv_7day_mean=row['hrv_7day_mean'],
            hrv_7day_std=row['hrv_7day_std'],
            sleep_efficiency=row['sleep_efficiency']
        )
        row.update(judgment)

        daily_data.append(row)

    return daily_data


def format_training_readiness_table(daily_data):
    """
    筋トレ判断データをMarkdownテーブル形式にフォーマット

    Parameters
    ----------
    daily_data : list of dict
        日別の筋トレ判断データ

    Returns
    -------
    str
        Markdownテーブル
    """
    lines = []
    lines.append('| 日付 | HRV | 7日平均 | 判定 | 推奨 |')
    lines.append('|------|-----|---------|------|------|')

    for day in daily_data:
        date_str = day['date'].strftime('%m/%d')
        hrv_str = f"{day['hrv_today']:.1f}" if day['hrv_today'] is not None else '-'
        mean_str = f"{day['hrv_7day_mean']:.1f}" if day['hrv_7day_mean'] is not None else '-'

        # 強度アイコン
        intensity_icon = {
            'rest': '🔴 休養',
            'low': '🟡 軽め',
            'medium': '🟢 中程度',
            'high': '🟢 通常',
            'unknown': '⚪ 不明'
        }.get(day.get('intensity', 'unknown'), '⚪ 不明')

        recommendation = day.get('recommendation', '-')

        lines.append(f"| {date_str} | {hrv_str} | {mean_str} | {intensity_icon} | {recommendation} |")

    return '\n'.join(lines)
