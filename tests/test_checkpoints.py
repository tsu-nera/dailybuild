"""チェックポイント: 材料が無い区切りを別の材料で埋めないこと（欠測の捏造をしない）"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.analytics.checkpoints import (JST, PHONE_ALARM, PHONE_SCREEN, PHONE_ZONE, Inputs,
                                       judge)

WAKE = dt.date(2026, 11, 18)


def t(day, h, m=0):
    return dt.datetime(2026, 11, day, h, m, tzinfo=JST)


def sleep():
    return {'start': t(17, 23), 'end': t(18, 6), 'attrs': {}}


def steps(points):
    """[(時刻, 歩数)] の1分値"""
    return pd.Series([v for _, v in points], index=pd.DatetimeIndex([p for p, _ in points], tz=JST),
                     dtype=int)


def inputs(**kw):
    base = dict(wake_date=WAKE, sleep=sleep(), stages=[], steps=steps([]), states={})
    base.update(kw)
    return Inputs(**base)


def names(i):
    return {name for name, _, _ in judge(i)}


def test_no_sleep_no_sleep_checkpoints():
    """睡眠記録の無い夜は入眠・最終覚醒・離床・画面off・帰宅を出さない"""
    i = inputs(sleep=None, states={PHONE_SCREEN: [(t(17, 22), 'on'), (t(17, 23), 'off')]})
    assert names(i) == set()


def test_rise_needs_steps():
    """歩数が無い朝は離床を作らない（睡眠記録の終了で代わりにしない）"""
    assert 'rise' not in names(inputs())


def test_scattered_steps_are_not_rise():
    """単発の数歩（寝返り・トイレ）は離床にしない"""
    i = inputs(steps=steps([(t(18, 6, 10), 7), (t(18, 6, 40), 7)]))
    assert 'rise' not in names(i)


def test_rise_from_steps():
    i = inputs(steps=steps([(t(18, 6, 30 + k), 10) for k in range(4)]))
    got = {n: tm for n, tm, _ in judge(i)}
    assert got['rise'] == t(18, 6, 30)


def test_stopped_phone_gives_no_screen_or_home():
    """Companion App が入眠より前に止まった夜は、残った最後の値から画面off・帰宅を作らない"""
    i = inputs(states={
        PHONE_SCREEN: [(t(17, 20), 'on'), (t(17, 21), 'off')],
        PHONE_ZONE: [(t(17, 16), 'not_home'), (t(17, 19), 'home')],
    })
    assert not {'screen_off', 'home'} & names(i)


def test_stayed_home_has_no_home_time():
    """一日中在宅の夜は帰宅の行を作らない"""
    i = inputs(states={PHONE_ZONE: [(t(17, 10), 'home'), (t(18, 1), 'home')]})
    assert 'home' not in names(i)


def test_calendar_values_are_not_alarms():
    """カレンダー通知の 1970 年の値はアラームにしない"""
    i = inputs(states={PHONE_ALARM: [(t(17, 22), '1970-01-01T21:16:29+00:00')]})
    assert 'alarm' not in names(i)


def test_first_alarm_of_the_morning():
    i = inputs(states={PHONE_ALARM: [(t(17, 22), '2026-11-17T21:00:00+00:00'),
                                     (t(18, 6, 3), '2026-11-17T21:30:00+00:00')]})
    got = {n: tm for n, tm, _ in judge(i)}
    assert got['alarm'] == t(18, 6)
