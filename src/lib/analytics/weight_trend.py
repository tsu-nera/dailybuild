#!/usr/bin/env python
# coding: utf-8
"""
体重トレンド（kg/週）

エネルギー収支を kcal に換算せず、体重の7日移動平均の3週差から kg/週 を出す
（Issue #25）。実測ノイズが3週窓でも ±510 kcal/日 相当あるため、kcal へは
戻さない。3週窓の測定日数が足りない場合は値を出さず「測定不足」を返す
（測定が疎な窓で傾きを出すと、ノイズをトレンドとして読んでしまう）。
"""

import pandas as pd

# トレンド計算の既定窓（3週間）
DEFAULT_WINDOW_DAYS = 21
# 窓内で必要な最低測定日数（未満なら測定不足）
DEFAULT_MIN_MEASURED_DAYS = 14
# 移動平均の日数
ROLLING_WINDOW_DAYS = 7


def calc_weight_trend(df_weight, end_date=None,
                       window_days=DEFAULT_WINDOW_DAYS,
                       min_measured_days=DEFAULT_MIN_MEASURED_DAYS):
    """
    体重の7日移動平均の3週差を kg/週 に直す

    Parameters
    ----------
    df_weight : DataFrame
        date, weight 列を持つデータフレーム（healthplanet_innerscan.csv 由来）。
        測定は毎日ではなく週0〜5点とばらつく前提
    end_date : str or Timestamp, optional
        基準日（省略時は df_weight の最終測定日）
    window_days : int, optional
        トレンド判定の窓（既定21日=3週）
    min_measured_days : int, optional
        窓内で必要な最低測定日数（未満なら測定不足）

    Returns
    -------
    dict
        - kg_per_week: float or None（測定不足なら None。kcal には換算しない）
        - measured_days: int（window_days 日の窓内の実測定日数）
        - window_days: int
        - sufficient: bool（measured_days >= min_measured_days）
    """
    df = df_weight[['date', 'weight']].dropna(subset=['weight']).copy()
    df['date'] = pd.to_datetime(df['date']).dt.normalize()
    df = df.sort_values('date')

    result = {
        'kg_per_week': None,
        'measured_days': 0,
        'window_days': window_days,
        'sufficient': False,
    }

    if len(df) == 0:
        return result

    if end_date is None:
        end_date = df['date'].max()
    end_date = pd.Timestamp(end_date).normalize()

    window_start = end_date - pd.Timedelta(days=window_days - 1)
    measured_days = int(
        ((df['date'] >= window_start) & (df['date'] <= end_date)).sum()
    )
    result['measured_days'] = measured_days
    result['sufficient'] = measured_days >= min_measured_days

    if not result['sufficient']:
        return result

    # 比較する2時点（window_start と end_date）それぞれの直近7日平均を出すため、
    # window_start からさらに6日遡った範囲で7日移動平均を計算する
    lookback_start = window_start - pd.Timedelta(days=ROLLING_WINDOW_DAYS - 1)
    daily = df.set_index('date')['weight']
    daily = daily.reindex(pd.date_range(lookback_start, end_date, freq='D'))
    rolling = daily.rolling(window=ROLLING_WINDOW_DAYS, min_periods=1).mean()

    weight_start = rolling.loc[window_start]
    weight_end = rolling.loc[end_date]

    if pd.isna(weight_start) or pd.isna(weight_end):
        result['sufficient'] = False
        return result

    diff_3weeks = weight_end - weight_start
    result['kg_per_week'] = diff_3weeks / 3
    return result
