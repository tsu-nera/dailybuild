"""
lib.analytics.weight_daily のテスト

体重の日次系列は複数経路の写しを1本にする。壊れ方は2つとも気づけない:

1. どの経路にも無い日に値が入る（欠測の捏造）
2. 同じ日が経路の数だけ並ぶ（二重計上）
"""

import pandas as pd

from lib.analytics.weight_daily import build_weight_daily


def hp(rows):
    return pd.DataFrame(rows, columns=['date', 'weight'])


def gh(rows):
    return pd.DataFrame(rows, columns=['time', 'date', 'weight_kg'])


def test_days_absent_from_every_source_have_no_row():
    out = build_weight_daily({
        'healthplanet': hp([('2026-10-01', 60.0), ('2026-10-04', 61.0)]),
        'googlehealth': gh([('2026-10-02 07:00:00', '2026-10-02', 60.5)]),
    })

    assert out['date'].dt.strftime('%Y-%m-%d').tolist() == ['2026-10-01', '2026-10-02', '2026-10-04']


def test_same_day_in_two_sources_is_one_row_from_the_preferred_source():
    out = build_weight_daily({
        'healthplanet': hp([('2026-10-01', 60.0)]),
        'googlehealth': gh([('2026-10-01 07:00:00', '2026-10-01', 60.3)]),
    })

    assert len(out) == 1
    assert out.iloc[0][['weight', 'source']].tolist() == [60.0, 'healthplanet']


def test_missing_value_in_preferred_source_falls_back():
    out = build_weight_daily({
        'healthplanet': hp([('2026-10-01', None)]),
        'googlehealth': gh([('2026-10-01 07:00:00', '2026-10-01', 60.3)]),
    })

    assert out.iloc[0][['weight', 'source']].tolist() == [60.3, 'googlehealth']


def test_multiple_measurements_in_a_day_take_the_first():
    out = build_weight_daily({
        'googlehealth': gh([
            ('2018-02-03 23:24:02', '2018-02-03', 88.0),
            ('2018-02-03 22:22:30', '2018-02-03', 87.5),
        ]),
    })

    assert out['weight'].tolist() == [87.5]


def test_no_sources_gives_empty_frame():
    out = build_weight_daily({})

    assert out.empty
    assert list(out.columns) == ['date', 'weight', 'source']
