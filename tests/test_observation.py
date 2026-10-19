"""観察日記: 材料が欠けた区切りを別の材料で埋めないこと（欠測の捏造をしない）"""

import datetime as dt
import sys
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.observation.ha import JST
from lib.observation.landmarks import DayData, judge, window
from lib.observation.timeline import items, phone_sessions, unknown_gaps

CFG = yaml.safe_load((BASE_DIR / 'config' / 'observation.yaml').read_text(encoding='utf-8'))
E = CFG['entities']
DAY = dt.date(2026, 10, 17)


def t(day, h, m=0):
    return dt.datetime(2026, 10, day, h, m, tzinfo=JST)


def sleep(start, end, date_of_sleep):
    return {'kind': 'sleep', 'source': 'wearable_sleep', 'name': 'sleep', 'start': start, 'end': end,
            'attrs': {'date_of_sleep': date_of_sleep, 'log_id': date_of_sleep}}


def noise(*points):
    """[(時刻, dBFS)] の1分値"""
    return [(tm, str(v), False) for tm, v in points]


def day_data(hist, events):
    lo, hi = window(DAY, CFG['day_start_hour'], JST)
    return DayData(day=DAY, lo=lo, hi=hi, cfg=CFG, hist=hist, events=events)


def by_name(d):
    return {lm.name: lm for lm in judge(d)}


MORNING_SLEEP = sleep(t(17, 0, 53), t(17, 9, 28), '2026-10-17')


def test_rise_is_not_filled_with_sleep_end_when_noise_is_missing():
    lms = by_name(day_data({}, [MORNING_SLEEP]))
    assert lms['睡眠記録終了'].time == t(17, 9, 28)
    assert lms['離床'].time is None
    assert lms['出発'].time is None


def test_rise_uses_curtain_and_noise():
    hist = {
        E['noise']: noise(*[(t(17, 10, 5) + dt.timedelta(minutes=i), -30) for i in range(35)]),
        E['illuminance']: [(t(17, 10, 0), '61', False), (t(17, 10, 9), '248', False)],
    }
    lms = by_name(day_data(hist, [MORNING_SLEEP]))
    assert lms['離床'].time == t(17, 10, 5)
    assert lms['出発'].time == t(17, 10, 39)


def test_depart_unknown_while_noise_continues():
    pts = [(t(17, 10, 5) + dt.timedelta(minutes=10 * i), -30) for i in range(40)]
    lms = by_name(day_data({E['noise']: noise(*pts)}, [MORNING_SLEEP]))
    assert lms['離床'].time == t(17, 10, 5)
    assert lms['出発'].time is None


def test_stale_phone_has_no_sessions_and_no_screen_off():
    night = sleep(t(18, 0, 30), t(18, 7, 0), '2026-10-18')
    hist = {E['phone']['screen']: [(t(17, 4), 'on', True)]}   # 窓の開始時点の値だけで以後届かない
    d = day_data(hist, [night])
    assert phone_sessions(d) == []
    assert by_name(d)['画面off'].time is None


def test_sleep_started_before_window_is_not_an_unknown_gap():
    prev = sleep(t(17, 0, 53), t(17, 9, 28), '2026-10-17')
    d = day_data({}, [prev, {'kind': 'exercise', 'source': 'googlehealth_exercise', 'name': 'x',
                              'start': t(17, 10), 'end': t(17, 11), 'attrs': {}}])
    rows = items(d)
    gaps = unknown_gaps(d, rows)
    assert all(not (a < t(17, 9) < b) for a, b in gaps)


def test_rise_is_not_taken_from_evening_noise_after_staying_out():
    # 外泊の朝: 家の生活音は夜に帰宅してから
    hist = {E['noise']: noise(*[(t(17, 23) + dt.timedelta(minutes=i), -26) for i in range(10)])}
    lms = by_name(day_data(hist, [MORNING_SLEEP]))
    assert lms['離床'].time is None


def _automated(**keys):
    cfg = {**CFG, 'automated_since': keys}
    lo, hi = window(DAY, CFG['day_start_hour'], JST)
    return cfg, lo, hi


def test_automated_curtain_is_not_taken_as_rise():
    # 自動のカーテンが 06:00 に開いても、離床は生活音の立ち上がり（08:30）
    cfg, lo, hi = _automated(illuminance=DAY)
    hist = {
        E['noise']: noise(*[(t(17, 8, 30) + dt.timedelta(minutes=i), -30) for i in range(20)]),
        E['illuminance']: [(t(17, 5, 59), '20', False), (t(17, 6, 0), '200', False)],
    }
    d = DayData(day=DAY, lo=lo, hi=hi, cfg=cfg, hist=hist,
                events=[sleep(t(16, 23, 40), t(17, 5, 50), '2026-10-17')])
    assert by_name(d)['離床'].time == t(17, 8, 30)


def test_automated_lights_give_no_lights_off_and_home_needs_noise():
    cfg, lo, hi = _automated(lights=DAY)
    night = sleep(t(17, 23, 40), t(18, 6, 0), '2026-10-18')
    on_off = [(t(17, 18, 0), 'on', False), (t(17, 23, 0), 'off', False)]
    hist = {eid: on_off for eid in E['lights']}
    d = DayData(day=DAY, lo=lo, hi=hi, cfg=cfg, hist=hist, events=[MORNING_SLEEP, night])
    lms = by_name(d)
    assert lms['消灯'].time is None
    assert lms['帰宅'].time is None   # 自動で点いた照明だけでは帰宅にしない
