"""
XOSS の FIT 要約（Issue #253）のテスト

session だけを読む・時刻は JST の tz-aware・欠けた値を 0 にしない・session が無ければ
行を作らない（0 km の行を捏造しない）ことを、fitdecode の出力を模したフェイクで確認する。
"""

import datetime as dt
import logging

from lib.xoss import fit_summary

UTC = dt.timezone.utc


def _session(**over):
    fields = {
        'start_time': dt.datetime(2026, 10, 31, 11, 42, 35, tzinfo=UTC),
        'timestamp': dt.datetime(2026, 10, 31, 12, 43, 0, tzinfo=UTC),
        'total_elapsed_time': 3625.0, 'total_timer_time': 3095.0,
        'total_distance': 15477.47, 'total_ascent': 92, 'total_descent': 146,
        'avg_speed': 5.0, 'max_speed': 11.06, 'sport': 'cycling', 'sub_sport': 'road',
        'avg_heart_rate': 0, 'avg_altitude': -500.0,
    }
    fields.update(over)
    return ('session', fields)


def test_session_gives_distance_jst_times_and_timer():
    row = fit_summary.summarize('20261031204235.fit', [('record', {'distance': 1.0}), _session()])

    assert row['distance_m'] == 15477.47
    assert row['timer_s'] == 3095.0
    assert row['start'] == '2026-10-31T20:42:35+09:00'
    assert row['end'] == '2026-10-31T21:43:00+09:00'
    assert list(row) == fit_summary.COLUMNS


def test_heart_rate_and_altitude_are_not_in_row():
    row = fit_summary.summarize('a.fit', [_session()])

    assert not any('heart' in k or 'alt' in k for k in row)


def test_missing_field_is_empty_not_zero():
    row = fit_summary.summarize('a.fit', [_session(total_distance=None, total_ascent=None)])

    assert row['distance_m'] == ''
    assert row['ascent_m'] == ''


def test_no_session_returns_none_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger='xoss'):
        row = fit_summary.summarize('a.fit', [('record', {'distance': 0})])

    assert row is None
    assert 'session' in caplog.text


def test_multiple_sessions_returns_none(caplog):
    with caplog.at_level(logging.WARNING, logger='xoss'):
        assert fit_summary.summarize('a.fit', [_session(), _session()]) is None
    assert caplog.records
