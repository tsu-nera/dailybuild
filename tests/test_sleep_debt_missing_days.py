"""
睡眠負債が欠測日を「睡眠0時間」として計上しないことの検証

以前はレポート側が計算機へ渡す前に日付を連続化し fill_value=0 で埋めていた
（Rise app 互換として意図的に入っていた）。その結果、Fitbit を着けなかった日が
「0時間寝た」として負債に載り、2026-08-11 の1日で負債が 8.0h → 16.8h に跳ね、
14日窓から抜けるまで2週間ぶん系列全体が嵩上げされていた。直近365日では74日
（20.3%）が欠測なので、遡るほど負債は実態より大きく出ていた。

宣言されている唯一の週次目標が sleep_debt_h = 0 なので、この膨張は目標評価を
そのまま歪める。
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lib.analytics.sleep.sleep_debt_clean import SleepDebtCalculator


def _calculator(rows, sleep_need_hours=8.0):
    """(日付文字列, 睡眠分) のリストから計算機を作る"""
    df = pd.DataFrame(
        [{'dateOfSleep': pd.Timestamp(d), 'minutesAsleep': m, 'timeInBed': m}
         for d, m in rows]
    )
    return SleepDebtCalculator(
        sleep_data=df, sleep_need_hours=sleep_need_hours,
        window_days=14, min_data_points=5,
    )


def _dates(start, n):
    d0 = datetime.fromisoformat(start)
    return [(d0 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n)]


def test_missing_day_does_not_inflate_debt():
    """欠測日がある系列は、その日を詰めた系列と同じ負債になること"""
    days = _dates('2026-08-01', 14)
    full = [(d, 420) for d in days]

    gap = [(d, m) for d, m in full if d != '2026-08-07']
    end = datetime.fromisoformat('2026-08-14')

    debt_gap = _calculator(gap).calculate(end_date=end).sleep_debt_hours
    debt_dense = _calculator([(d, 420) for d in _dates('2026-08-01', 13)]).calculate(
        end_date=datetime.fromisoformat('2026-08-13')).sleep_debt_hours

    # 欠測日は不足分として数えない。13夜ぶんの負債と一致する
    assert debt_gap == pytest.approx(debt_dense, abs=0.01)


def test_missing_day_is_not_counted_as_zero_sleep():
    """欠測日を0分の行として渡した場合との差が、捏造の大きさそのものになる"""
    days = _dates('2026-08-01', 14)
    gap = [(d, 420) for d in days if d != '2026-08-07']
    zero_filled = [(d, 0 if d == '2026-08-07' else 420) for d in days]
    end = datetime.fromisoformat('2026-08-14')

    debt_gap = _calculator(gap).calculate(end_date=end).sleep_debt_hours
    debt_zero = _calculator(zero_filled).calculate(end_date=end).sleep_debt_hours

    assert debt_zero > debt_gap, '0埋めの方が負債が大きくならないのは前提が崩れている'


def test_actual_sleep_is_none_on_missing_day():
    """欠測日の実績は None。0.0 だと「0時間寝た」と区別できない"""
    days = _dates('2026-08-01', 14)
    gap = [(d, 420) for d in days if d != '2026-08-07']
    calc = _calculator(gap)

    missing = calc.calculate(end_date=datetime.fromisoformat('2026-08-07'))
    present = calc.calculate(end_date=datetime.fromisoformat('2026-08-08'))

    assert missing.actual_sleep_hours is None
    assert present.actual_sleep_hours == pytest.approx(7.0)


def test_history_table_shows_dash_for_missing_day():
    """日別推移の実績列は欠測日を '-' で出すこと"""
    from lib.analytics.sleep.sleep_debt_clean import format_debt_history_table

    days = _dates('2026-08-01', 14)
    gap = [(d, 420) for d in days if d != '2026-08-07']
    history = _calculator(gap).get_history(
        datetime.fromisoformat('2026-08-06'), datetime.fromisoformat('2026-08-08'))

    table = format_debt_history_table(history)
    actual = dict(zip(table['日付'], table['実績']))
    assert actual['08/07'] == '-'
    assert actual['08/08'] == '7.0h'
