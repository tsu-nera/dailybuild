"""early_rising.py: Companion App が止まった夜にスマホの値を捏造しないこと"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

spec = importlib.util.spec_from_file_location('early_rising', BASE_DIR / 'scripts' / 'early_rising.py')
er = importlib.util.module_from_spec(spec)
spec.loader.exec_module(er)

JST = er.JST
WAKE = dt.date(2026, 10, 17)


def t(day, h, m=0):
    return dt.datetime(2026, 10, day, h, m, tzinfo=JST)


def sleep_events():
    return [{'kind': 'sleep', 'start': t(17, 0, 53), 'end': t(17, 9, 28), 'name': 'sleep',
             'attrs': {'date_of_sleep': WAKE.isoformat()}}]


def test_stale_screen_on_is_not_counted():
    # 窓の開始時点で on のまま、以後何も届かない（10-15 22:34 に止まった実例）
    hist = {
        er.PHONE_SCREEN: [(t(16, 15), 'on', True)],
        er.PHONE_APP: [(t(16, 15), 'com.android.chrome', True)],
    }
    row = er.night_row(sleep_events(), hist, WAKE)
    assert 'phone_min' not in row
    assert 'apps' not in row
    assert 'morning_phone_min' not in row


def test_stops_between_sleep_and_wake_keeps_night_only():
    hist = {
        er.PHONE_SCREEN: [(t(16, 15), 'off', True), (t(16, 23), 'on', False), (t(17, 0, 40), 'off', False)],
        er.PHONE_BATTERY: [(t(17, 3), '80', False)],
    }
    row = er.night_row(sleep_events(), hist, WAKE)
    assert row['phone_min'] == 100
    assert 'morning_phone_min' not in row


def test_alive_phone_is_counted():
    hist = {
        er.PHONE_SCREEN: [(t(16, 15), 'off', True), (t(16, 23), 'on', False), (t(17, 0, 40), 'off', False),
                          (t(17, 9, 30), 'on', False), (t(17, 9, 40), 'off', False)],
    }
    row = er.night_row(sleep_events(), hist, WAKE)
    assert row['phone_min'] == 100
    assert row['morning_phone_min'] == 10


def test_noise_bursts_join_within_gap():
    series = [(t(16, 22, 15), '-26', False), (t(16, 22, 18), '-35', False),
              (t(16, 22, 30), '-30', False), (t(16, 22, 31), 'unavailable', False)]
    bursts = er.noise_bursts(series)
    assert [b[0] for b in bursts] == [t(16, 22, 15), t(16, 22, 30)]
