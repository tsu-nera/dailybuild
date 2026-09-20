"""
lib.analytics.nutrition.calc_nutrition_stats_for_period のテスト

protein_only（config/nutrition_logging.yaml）の日は calories が NaN になる。
ここを calories だけで絞ると、記録があるのに行が全部落ちて統計が None になり、
レポートは栄養セクションごと出力せずに正常終了する。目視でも実行でも検出
できない欠測の捏造なので、消費側でも押さえる。
"""

import numpy as np
import pandas as pd

from lib.analytics import nutrition


COLUMNS = ['date', 'calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium', 'water']


def make_df(rows):
    return pd.DataFrame(rows, columns=COLUMNS).assign(
        date=lambda d: pd.to_datetime(d['date'])
    )


def test_protein_only_day_is_not_dropped():
    """calories が NaN でも protein があれば記録日として残る"""
    df = make_df([
        ['2026-09-20', np.nan, np.nan, np.nan, np.nan, 110.36, np.nan, np.nan],
    ])

    stats = nutrition.calc_nutrition_stats_for_period(df)

    assert stats is not None
    assert stats['recorded_days'] == 1
    assert stats['avg_protein'] == 110.36
    assert stats['daily'][0]['protein'] == 110.36


def test_protein_only_day_does_not_fabricate_calories():
    """落とさない代わりに、記録の無い列を0で埋めない"""
    df = make_df([
        ['2026-09-20', np.nan, np.nan, np.nan, np.nan, 110.36, np.nan, np.nan],
    ])

    stats = nutrition.calc_nutrition_stats_for_period(df)

    assert np.isnan(stats['avg_calories'])
    assert np.isnan(stats['protein_pct'])
    assert np.isnan(stats['daily'][0]['calories'])


def test_complete_and_protein_only_days_coexist():
    """完全記録の日は従来どおり平均とPFC比率が出る"""
    df = make_df([
        ['2026-09-19', 1469.0, 104.67, 74.41, 25.21, 109.63, 566.99, 1200.0],
        ['2026-09-20', np.nan, np.nan, np.nan, np.nan, 110.36, np.nan, np.nan],
    ])

    stats = nutrition.calc_nutrition_stats_for_period(df)

    assert stats['recorded_days'] == 2
    assert stats['avg_calories'] == 1469.0        # NaN の日は平均に混ぜない
    assert stats['avg_protein'] == (109.63 + 110.36) / 2
    assert stats['protein_pct'] > 0


def test_all_missing_returns_none():
    """値が1つも無ければ従来どおり None"""
    df = make_df([
        ['2026-09-20', np.nan, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan],
    ])

    assert nutrition.calc_nutrition_stats_for_period(df) is None
