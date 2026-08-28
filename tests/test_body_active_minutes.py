"""
body.merge_daily_data() の active_minutes 合算テスト（Issue #82）

Google Health 移行で activityCalories / sedentaryMinutes に対応する型が
無くなったため、lightlyActiveMinutes + fairlyActiveMinutes +
veryActiveMinutes から active_minutes を導く。0埋めで欠測を捏造しないこと
が本命の再発防止対象。
"""

import math

import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.analytics import body


def _df_body(dates):
    return pd.DataFrame({'date': pd.to_datetime(dates)})


def test_active_minutes_sums_three_levels():
    df_body = _df_body(['2026-08-01'])
    activity_stats = {
        'daily': [
            {
                'date': '2026-08-01',
                'caloriesOut': 2000,
                'lightlyActiveMinutes': 100,
                'fairlyActiveMinutes': 20,
                'veryActiveMinutes': 10,
            }
        ]
    }

    df = body.merge_daily_data(df_body, activity_stats=activity_stats)

    assert df.loc[0, 'active_minutes'] == 130


def test_active_minutes_is_nan_when_all_three_missing():
    """3列とも欠測の日は active_minutes が NaN になり、0 にならない"""
    df_body = _df_body(['2026-08-01'])
    activity_stats = {
        'daily': [
            {
                'date': '2026-08-01',
                'caloriesOut': 2000,
                'lightlyActiveMinutes': None,
                'fairlyActiveMinutes': None,
                'veryActiveMinutes': None,
            }
        ]
    }

    df = body.merge_daily_data(df_body, activity_stats=activity_stats)

    assert math.isnan(df.loc[0, 'active_minutes'])


def test_active_minutes_treats_missing_level_as_zero_when_others_present():
    """一部レベルだけ値がある日は、欠けたレベルを0分として合算する"""
    df_body = _df_body(['2026-08-01'])
    activity_stats = {
        'daily': [
            {
                'date': '2026-08-01',
                'caloriesOut': 2000,
                'lightlyActiveMinutes': 50,
                'fairlyActiveMinutes': None,
                'veryActiveMinutes': None,
            }
        ]
    }

    df = body.merge_daily_data(df_body, activity_stats=activity_stats)

    assert df.loc[0, 'active_minutes'] == 50


def test_active_minutes_raw_columns_are_dropped():
    """3列の生カラムは計算後dfに残さない"""
    df_body = _df_body(['2026-08-01'])
    activity_stats = {
        'daily': [
            {
                'date': '2026-08-01',
                'caloriesOut': 2000,
                'lightlyActiveMinutes': 50,
                'fairlyActiveMinutes': 10,
                'veryActiveMinutes': 5,
            }
        ]
    }

    df = body.merge_daily_data(df_body, activity_stats=activity_stats)

    for col in ('lightlyActiveMinutes', 'fairlyActiveMinutes', 'veryActiveMinutes'):
        assert col not in df.columns
    assert 'activityCalories' not in df.columns
    assert 'activity_calories' not in df.columns


def test_merge_without_active_minutes_columns_does_not_add_column():
    """active-minutes 系列が無い activity_stats では active_minutes を追加しない"""
    df_body = _df_body(['2026-08-01'])
    activity_stats = {
        'daily': [
            {'date': '2026-08-01', 'caloriesOut': 2000},
        ]
    }

    df = body.merge_daily_data(df_body, activity_stats=activity_stats)

    assert 'active_minutes' not in df.columns
