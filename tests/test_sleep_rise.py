"""
離床が Fitbit の睡眠記録の終了で埋められないことの検証

睡眠レポートの「離床」は以前 endTime をそのまま出しており、目は覚めたまま布団にいた
時間が抜けていた（10-17 は 09:28 と出たが本人の離床は 10:05）。目標 rise_time の
達成判定に使うので、歩数が無い朝を endTime で埋めると達成を捏造する。
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lib.analytics.sleep.rise import minutes_late, rise_time


def _steps(start, values):
    idx = pd.date_range(start, periods=len(values), freq='1min')
    return pd.Series(values, index=idx)


def test_rise_is_first_sustained_walking_not_a_few_steps():
    # 06:29 起床、07:00 に15歩（トイレ程度）、08:30 から歩き続ける
    v = [0] * 240
    v[31] = 15
    v[121:131] = [10] * 10
    steps = _steps('2026-10-19 06:29', v)
    assert rise_time(steps, pd.Timestamp('2026-10-19 06:29')) == pd.Timestamp('2026-10-19 08:30')


def test_no_step_records_gives_none():
    steps = _steps('2026-10-18 06:00', [0] * 60)   # 前日の記録しか無い
    assert rise_time(steps, pd.Timestamp('2026-10-19 06:29')) is None


def test_no_walking_within_window_gives_none():
    steps = _steps('2026-10-19 06:29', [0] * 600)
    assert rise_time(steps, pd.Timestamp('2026-10-19 06:29')) is None


def test_bedtime_after_midnight_is_late():
    assert minutes_late(pd.Timestamp('2026-10-19 00:07'), '22:45', evening=True) == 82
    assert minutes_late(pd.Timestamp('2026-10-18 22:30'), '22:45', evening=True) == -15
    assert minutes_late(pd.Timestamp('2026-10-19 08:30'), '05:45') == 165
