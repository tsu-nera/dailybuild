"""
Google Health intraday 型の期間フィルタ・集計ロジック（ネットワーク不要、Issue #76）

`tests/test_googlehealth_date_range.py` と同じ fake_get パターンを使う。
書くのは以下だけ:
  1. filter の窓が civilTime のタイムゾーンずれを吸収できるだけ広いこと
  2. civilTime の日付で範囲外の点が落ちること
  3. heart_rate の1分バケットが切り捨て平均（round ではない）であること
  4. steps が FITBIT/Charge6 以外の取得元（二重計上の原因）を落とすこと
  5. steps のゼロ埋め（過去日は1440行、当日は未来の分を作らない）
  6. br が civil date ごとに physicalTime 最早の点を採ること
  7. hrv の行が rmssd だけを持つこと（coverage 等の列を作らない）
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.clients import googlehealth_client as gh
from lib.clients import googlehealth_intraday as intraday

START = dt.date(2026, 8, 30)
END = dt.date(2026, 9, 3)
CREDS = object()   # フェイクした _get は creds を見ない


def fake_get(*pages):
    """_get を差し替える。ページを順に返し、最後だけ nextPageToken を落とす"""
    calls = []

    def _fake(creds, path, params=None):
        index = len(calls)
        calls.append(params)
        body = {'dataPoints': list(pages[index])}
        if index + 1 < len(pages):
            body['nextPageToken'] = f'page{index + 1}'
        return body

    _fake.calls = calls
    return _fake


def civil(day: str, hour: int = 0, minute: int = 0, second: int = 0) -> dict:
    y, m, d = (int(x) for x in day.split('-'))
    out = {'date': {'year': y, 'month': m, 'day': d}}
    if hour or minute or second:
        out['time'] = {'hours': hour, 'minutes': minute, 'seconds': second}
    return out


def heart_rate_point(day: str, hour: int, minute: int, second: int, bpm) -> dict:
    return {
        'heartRate': {
            'sampleTime': {
                'physicalTime': f'{day}T{hour:02d}:{minute:02d}:{second:02d}Z',
                'civilTime': civil(day, hour, minute, second),
            },
            'beatsPerMinute': str(bpm),
        },
    }


# --- 1. filter の窓の広さ ---------------------------------------------------

def test_list_filtered_points_window_has_15_hour_margin(monkeypatch):
    fake = fake_get([])
    monkeypatch.setattr(gh, '_get', fake)

    gh.list_filtered_points(CREDS, 'heart-rate', 'heart_rate.sample_time.physical_time',
                            START, END)

    filter_str = fake.calls[0]['filter']
    assert 'heart_rate.sample_time.physical_time >= "2026-08-29T09:00:00Z"' in filter_str
    assert 'heart_rate.sample_time.physical_time < "2026-09-04T15:00:00Z"' in filter_str
    assert ' AND ' in filter_str


def test_list_filtered_points_pages_to_the_end(monkeypatch):
    fake = fake_get(
        [heart_rate_point('2026-09-01', 1, 0, 0, 60)],
        [heart_rate_point('2026-09-01', 1, 1, 0, 60)],
    )
    monkeypatch.setattr(gh, '_get', fake)

    points = gh.list_filtered_points(CREDS, 'heart-rate',
                                     'heart_rate.sample_time.physical_time', START, END)
    assert len(points) == 2
    assert len(fake.calls) == 2
    # pageSize は指定しない
    assert 'pageSize' not in fake.calls[0]


# --- 2. civilTime の日付で範囲外が落ちる -----------------------------------

def test_heart_rate_intraday_drops_dates_outside_the_window(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        heart_rate_point('2026-08-29', 10, 0, 0, 60),   # start より前
        heart_rate_point('2026-08-30', 10, 0, 0, 60),   # start ちょうど
        heart_rate_point('2026-09-03', 10, 0, 0, 60),   # end ちょうど
        heart_rate_point('2026-09-04', 10, 0, 0, 60),   # end より後
    ]))
    rows = intraday.fetch_heart_rate_intraday(CREDS, START, END)
    assert [r['datetime'][:10] for r in rows] == ['2026-08-30', '2026-09-03']


# --- 3. heart_rate の切り捨て平均 -------------------------------------------

def test_heart_rate_intraday_bucket_is_truncated_mean_not_round(monkeypatch):
    """60と61の平均は60.5。round なら61に丸まるが、切り捨てなら60。
    round では通らず int でのみ通ることを確認する"""
    monkeypatch.setattr(gh, '_get', fake_get([
        heart_rate_point('2026-09-01', 10, 30, 0, 60),
        heart_rate_point('2026-09-01', 10, 30, 30, 61),
    ]))
    rows = intraday.fetch_heart_rate_intraday(CREDS, START, END)
    assert len(rows) == 1
    assert rows[0]['datetime'] == '2026-09-01 10:30:00'
    assert rows[0]['heart_rate'] == 60


# --- 4. steps: 取得元の絞り込み ----------------------------------------------

def steps_point(day: str, hour: int, minute: int, count: int,
                platform: str, device_name: str = None, package_name: str = None) -> dict:
    source = {'platform': platform}
    if device_name is not None:
        source['device'] = {'displayName': device_name}
    if package_name is not None:
        source['application'] = {'packageName': package_name}
    return {
        'dataSource': source,
        'steps': {
            'interval': {
                'startTime': f'{day}T{hour:02d}:{minute:02d}:00Z',
                'civilStartTime': civil(day, hour, minute),
            },
            'count': str(count),
        },
    }


def test_steps_intraday_ignores_duplicate_sources(monkeypatch):
    """MobileTrack と HEALTH_CONNECT を混ぜても、FITBIT/Charge6 相当の点だけ数える。
    これを外すと歩数が二重・3.6倍に計上される"""
    monkeypatch.setattr(gh, '_get', fake_get([
        steps_point('2026-09-01', 10, 0, 30, 'FITBIT', device_name='Charge 6'),
        steps_point('2026-09-01', 10, 0, 25, 'FITBIT', device_name='MobileTrack'),
        steps_point('2026-09-01', 10, 0, 40, 'HEALTH_CONNECT', package_name='com.google.android.apps.fitness'),
    ]))
    rows = intraday.fetch_steps_intraday(CREDS, dt.date(2026, 9, 1), dt.date(2026, 9, 1))
    row = next(r for r in rows if r['datetime'] == '2026-09-01 10:00:00')
    assert row['steps'] == 30


# --- 5. steps: ゼロ埋め -------------------------------------------------------

def test_steps_intraday_zero_fills_past_day_to_1440_rows(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        steps_point('2026-08-30', 10, 0, 5, 'FITBIT', device_name='Charge 6'),
    ]))
    past_day = dt.date(2026, 8, 30)
    rows = intraday.fetch_steps_intraday(CREDS, past_day, past_day)
    assert len(rows) == 1440
    nonzero = [r for r in rows if r['steps'] != 0]
    assert nonzero == [{'datetime': '2026-08-30 10:00:00', 'steps': 5}]


def test_steps_intraday_does_not_fabricate_future_minutes_for_today(monkeypatch):
    today = dt.date.today()
    now = dt.datetime.now()
    monkeypatch.setattr(gh, '_get', fake_get([
        steps_point(today.isoformat(), 0, 0, 3, 'FITBIT', device_name='Charge 6'),
    ]))
    rows = intraday.fetch_steps_intraday(CREDS, today, today)
    last_expected = f'{today.isoformat()} {now.hour:02d}:{now.minute:02d}:00'
    assert rows[-1]['datetime'] == last_expected
    assert len(rows) == now.hour * 60 + now.minute + 1
    assert rows[-1]['datetime'] <= f'{today.isoformat()} 23:59:59'


def test_steps_intraday_does_not_zero_fill_a_day_without_any_point(monkeypatch):
    """1点も返らなかった日を0で埋めない。保存はキーマージなので、埋めると
    取得の沈黙故障（filter の誤り・同期前）が既存の実測値を0で上書きする"""
    monkeypatch.setattr(gh, '_get', fake_get([
        steps_point('2026-08-31', 10, 0, 5, 'FITBIT', device_name='Charge 6'),
    ]))
    rows = intraday.fetch_steps_intraday(CREDS, dt.date(2026, 8, 30), dt.date(2026, 8, 31))
    assert {r['datetime'][:10] for r in rows} == {'2026-08-31'}
    assert len(rows) == 1440


def test_steps_intraday_ignores_a_day_whose_only_points_are_other_sources(monkeypatch):
    """MobileTrack しか無い日も「Charge 6 の記録が無い日」なのでゼロ埋めしない"""
    monkeypatch.setattr(gh, '_get', fake_get([
        steps_point('2026-08-30', 10, 0, 5, 'FITBIT', device_name='MobileTrack'),
    ]))
    assert intraday.fetch_steps_intraday(CREDS, dt.date(2026, 8, 30), dt.date(2026, 8, 30)) == []


# --- 6. br: civil date ごとに physicalTime 最早の点 --------------------------

def br_point(day: str, physical_hour: int, physical_minute: int, light: float) -> dict:
    return {
        'respiratoryRateSleepSummary': {
            'sampleTime': {
                'physicalTime': f'{day}T{physical_hour:02d}:{physical_minute:02d}:00Z',
                'civilTime': civil(day, physical_hour, physical_minute),
            },
            'deepSleepStats': {'breathsPerMinute': 16},
            'lightSleepStats': {'breathsPerMinute': light},
            'remSleepStats': {'breathsPerMinute': 11},
            'fullSleepStats': {'breathsPerMinute': 16},
        },
    }


def test_br_intraday_uses_earliest_physical_time_per_civil_date(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        br_point('2026-09-01', 3, 48, 15.6),   # 最早
        br_point('2026-09-01', 9, 32, 14.6),
        br_point('2026-09-01', 11, 1, 14.8),
    ]))
    rows = intraday.fetch_br_intraday(CREDS, dt.date(2026, 9, 1), dt.date(2026, 9, 1))
    assert len(rows) == 1
    assert rows[0]['br_light'] == 15.6


# --- 7. hrv: rmssd だけを持つ ------------------------------------------------

def hrv_point(day: str, hour: int, minute: int, rmssd: float) -> dict:
    return {
        'heartRateVariability': {
            'sampleTime': {
                'physicalTime': f'{day}T{hour:02d}:{minute:02d}:00Z',
                'civilTime': civil(day, hour, minute),
            },
            'rootMeanSquareOfSuccessiveDifferencesMilliseconds': rmssd,
        },
    }


def test_hrv_intraday_rows_only_have_datetime_and_rmssd(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        hrv_point('2026-09-01', 6, 45, 41.6),
    ]))
    rows = intraday.fetch_hrv_intraday(CREDS, dt.date(2026, 9, 1), dt.date(2026, 9, 1))
    assert len(rows) == 1
    assert set(rows[0].keys()) == {'datetime', 'rmssd'}
    assert rows[0]['rmssd'] == 41.6
