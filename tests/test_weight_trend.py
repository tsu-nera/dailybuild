"""
lib.analytics.weight_trend のテスト（Issue #25）

体重の実測ノイズは3週窓でも±510kcal/日相当あり、測定が疎な窓で傾きを出すと
ノイズをトレンドとして読んでしまう。3週(21日)窓の測定日数が14日未満なら
値を返さず「測定不足」を示すガードが本体。kcal には換算しない。
"""

import pandas as pd

from lib.analytics.weight_trend import calc_weight_trend


def make_daily_weight_df(start, end, weight_fn):
    dates = pd.date_range(start, end, freq='D')
    return pd.DataFrame({
        'date': dates.strftime('%Y-%m-%d'),
        'weight': [weight_fn(i) for i in range(len(dates))],
    })


def test_insufficient_measured_days_returns_no_value():
    # 27日分の範囲があっても、実測が21日窓のうち数点しかない(週1点=3点)
    dates = ['2026-08-01', '2026-08-08', '2026-08-15', '2026-08-22']
    df = pd.DataFrame({'date': dates, 'weight': [70.0, 69.8, 69.5, 69.2]})

    result = calc_weight_trend(df, end_date='2026-08-22')

    assert result['sufficient'] is False
    assert result['kg_per_week'] is None
    assert result['measured_days'] < 14
    assert result['window_days'] == 21


def test_sufficient_measured_days_returns_declining_trend():
    # 27日間、ほぼ毎日測定し、体重が緩やかに減少するデータ
    df = make_daily_weight_df('2026-08-01', '2026-08-27', lambda i: 70.0 - 0.05 * i)

    result = calc_weight_trend(df, end_date='2026-08-27')

    assert result['sufficient'] is True
    assert result['measured_days'] >= 14
    assert result['kg_per_week'] is not None
    # 体重は減少しているのでトレンドは負
    assert result['kg_per_week'] < 0


def test_flat_weight_yields_near_zero_trend():
    df = make_daily_weight_df('2026-08-01', '2026-08-27', lambda i: 70.0)

    result = calc_weight_trend(df, end_date='2026-08-27')

    assert result['sufficient'] is True
    assert abs(result['kg_per_week']) < 1e-9


def test_no_data_returns_insufficient():
    df = pd.DataFrame({'date': [], 'weight': []})

    result = calc_weight_trend(df, end_date='2026-08-27')

    assert result['sufficient'] is False
    assert result['kg_per_week'] is None
    assert result['measured_days'] == 0


def test_does_not_convert_to_kcal():
    # トレンドの結果に kcal 系のキーが無いことを確認する（kcal 換算関数を作らない方針）
    df = make_daily_weight_df('2026-08-01', '2026-08-27', lambda i: 70.0 - 0.05 * i)

    result = calc_weight_trend(df, end_date='2026-08-27')

    assert not any('kcal' in key for key in result.keys())
