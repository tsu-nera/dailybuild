"""googlehealth_fetcher のテスト（Issue #49）

ネットワークを使わない。FETCHERS を差し替えて保存経路のみ検証する。
"""

import datetime as dt

import pandas as pd
import pytest

from lib import googlehealth_fetcher as ghf
from lib.clients import googlehealth_api
from lib.utils import private_data


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ghf, 'DATA_DIR', tmp_path)
    return tmp_path


@pytest.fixture
def fake_rows(monkeypatch):
    """FETCHERS['hrv'] を差し替えて任意の行を返させる"""
    def install(rows):
        monkeypatch.setitem(
            googlehealth_api.FETCHERS, 'hrv', lambda creds, s, e: rows
        )
    return install


def test_resolve_range_uses_days_when_no_start_date():
    start, end = ghf._resolve_range(days=7, start_date=None, end_date=None)
    assert end == dt.date.today()
    assert (end - start).days == 6  # 当日を含めて7日


def test_resolve_range_prefers_start_date_over_days():
    start, end = ghf._resolve_range(days=7, start_date=dt.date(2026, 1, 1),
                                    end_date=dt.date(2026, 1, 10))
    assert (start, end) == (dt.date(2026, 1, 1), dt.date(2026, 1, 10))


def test_empty_result_is_reported_as_error(data_dir, fake_rows):
    """0件を成功として返さないこと（取得の沈黙故障を見逃さないため）"""
    fake_rows([])
    result = ghf.fetch_endpoint(None, 'hrv', days=3)
    assert result['records'] == 0
    assert result['error'], '0件がエラーとして報告されていない'
    assert not (data_dir / 'hrv.csv').exists(), '0件なのにCSVを書いている'


def test_rows_are_saved_with_date_index(data_dir, fake_rows):
    fake_rows([
        {'date': '2026-08-01', 'daily_rmssd': 30.1, 'deep_rmssd': 28.0},
        {'date': '2026-08-02', 'daily_rmssd': 31.5, 'deep_rmssd': 29.4},
    ])
    result = ghf.fetch_endpoint(None, 'hrv', days=3)

    assert result['records'] == 2
    saved = pd.read_csv(data_dir / 'hrv.csv')
    assert list(saved.columns) == ['date', 'daily_rmssd', 'deep_rmssd']
    assert saved['date'].tolist() == ['2026-08-01', '2026-08-02']


def test_merge_preserves_existing_rows(data_dir, fake_rows):
    """既定のマージモードで既存の日付が消えないこと"""
    existing = pd.DataFrame(
        {'daily_rmssd': [20.0], 'deep_rmssd': [19.0]},
        index=pd.to_datetime(['2026-07-01']),
    )
    existing.index.name = 'date'
    existing.to_csv(data_dir / 'hrv.csv')

    fake_rows([{'date': '2026-08-01', 'daily_rmssd': 30.1, 'deep_rmssd': 28.0}])
    ghf.fetch_endpoint(None, 'hrv', days=3)

    saved = pd.read_csv(data_dir / 'hrv.csv')
    assert saved['date'].tolist() == ['2026-07-01', '2026-08-01']


def test_overwrite_replaces_existing_rows(data_dir, fake_rows):
    existing = pd.DataFrame(
        {'daily_rmssd': [20.0], 'deep_rmssd': [19.0]},
        index=pd.to_datetime(['2026-07-01']),
    )
    existing.index.name = 'date'
    existing.to_csv(data_dir / 'hrv.csv')

    fake_rows([{'date': '2026-08-01', 'daily_rmssd': 30.1, 'deep_rmssd': 28.0}])
    ghf.fetch_endpoint(None, 'hrv', days=3, overwrite=True)

    saved = pd.read_csv(data_dir / 'hrv.csv')
    assert saved['date'].tolist() == ['2026-08-01']


def test_unknown_endpoint_raises():
    with pytest.raises(ValueError, match='Unknown endpoint'):
        ghf.fetch_endpoint(None, 'spo2', days=3)


def test_history_boundary_blocks_rewrite_by_default(data_dir, fake_rows):
    """境界より前を指定したら書き込まずエラーを返すこと（Issue #50 の事故防止）"""
    fake_rows([{'date': '2026-01-01', 'daily_rmssd': 99.9, 'deep_rmssd': 99.9}])
    result = ghf.fetch_endpoint(
        None, 'hrv', start_date=ghf.HISTORY_BOUNDARY - dt.timedelta(days=1)
    )
    assert result['records'] == 0
    assert '履歴境界' in result['error']
    assert not (data_dir / 'hrv.csv').exists()


def test_history_boundary_can_be_overridden(data_dir, fake_rows):
    fake_rows([{'date': '2026-01-01', 'daily_rmssd': 99.9, 'deep_rmssd': 99.9}])
    result = ghf.fetch_endpoint(
        None, 'hrv', start_date=dt.date(2026, 1, 1), allow_history_rewrite=True
    )
    assert result['records'] == 1
    assert (data_dir / 'hrv.csv').exists()


def test_negative_zero_is_not_written_to_csv(data_dir, fake_rows):
    """-0.0 が CSV に書かれないこと（既存の "0.0" と差分になるため）"""
    fake_rows([{'date': '2026-08-01', 'daily_rmssd': round(-0.04, 1) + 0.0,
                'deep_rmssd': 1.0}])
    ghf.fetch_endpoint(None, 'hrv', days=3)

    text = (data_dir / 'hrv.csv').read_text()
    assert '-0.0' not in text, f'負のゼロが出力されている: {text}'


def test_未マウントの環境ではpublic側への書き込みがエラーで止まる(tmp_path, monkeypatch, fake_rows):
    """symlink 未設定を模した環境で、0件成功ではなく FileNotFoundError で落ちること"""
    repo = tmp_path / 'dailybuild'
    (repo / 'data').mkdir(parents=True)
    monkeypatch.setattr(private_data, 'REPO_ROOT', repo)
    monkeypatch.setattr(ghf, 'DATA_DIR', repo / 'data' / 'fitbit')

    fake_rows([{'date': '2026-08-01', 'daily_rmssd': 30.1, 'deep_rmssd': 28.0}])

    with pytest.raises(FileNotFoundError):
        ghf.fetch_endpoint(None, 'hrv', days=3)


def test_num_coerces_string_values():
    """Google が数値を文字列で返すケースを float に正規化すること"""
    assert googlehealth_api._num('36.5') == 36.5
    assert googlehealth_api._num(36.5) == 36.5
    assert googlehealth_api._num(None) is None
    assert googlehealth_api._num('') is None


# =============================================================================
# sleep（期間置換・2セッション/日・efficiency算出・sleep_levels）
# =============================================================================

def _sleep_row(date_of_sleep, minutes_asleep=300, minutes_in_sleep_period=360,
              log_id='999', is_main=True):
    return {
        'dateOfSleep': date_of_sleep,
        'startTime': f'{date_of_sleep}T23:00:00.000',
        'endTime': f'{date_of_sleep}T07:00:00.000',
        'duration': 28800000,
        'timeInBed': minutes_in_sleep_period,
        'efficiency': round(minutes_asleep / minutes_in_sleep_period * 100),
        'minutesAsleep': minutes_asleep,
        'minutesAwake': minutes_in_sleep_period - minutes_asleep,
        'minutesAfterWakeup': 0,
        'minutesToFallAsleep': 0,
        'logId': log_id,
        'logType': None,
        'type': 'stages',
        'infoCode': None,
        'isMainSleep': is_main,
        'deepMinutes': 30, 'lightMinutes': 200, 'remMinutes': 60, 'wakeMinutes': 10,
        'deepCount': 3, 'lightCount': 10, 'remCount': 5, 'wakeCount': 2,
        'deepAvg30': None, 'lightAvg30': None, 'remAvg30': None, 'wakeAvg30': None,
    }


@pytest.fixture
def fake_sleep(monkeypatch):
    """FETCHERS['sleep'] を差し替えて (sleep_rows, level_rows) を返させる"""
    def install(sleep_rows, level_rows=None):
        monkeypatch.setitem(
            googlehealth_api.FETCHERS, 'sleep',
            lambda creds, s, e: (sleep_rows, level_rows or []),
        )
    return install


def test_sleep_period_replace_drops_only_in_range_rows(data_dir, fake_sleep):
    """期間置換: 対象期間の既存行は消え、期間外は残ること"""
    existing = pd.DataFrame([
        _sleep_row('2026-07-01', log_id='old-1'),  # 期間外 -> 残る
        _sleep_row('2026-08-01', log_id='old-2'),  # 期間内 -> 消える
    ])
    existing.to_csv(data_dir / 'sleep.csv', index=False)
    pd.DataFrame([], columns=['logId', 'dateOfSleep', 'dateTime', 'level', 'seconds', 'isShort']
                ).to_csv(data_dir / 'sleep_levels.csv', index=False)

    fake_sleep([_sleep_row('2026-08-01', log_id='new-1')])
    result = ghf.fetch_endpoint(
        None, 'sleep', start_date=dt.date(2026, 8, 1), end_date=dt.date(2026, 8, 1),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'sleep.csv')
    assert result['records'] == 2
    assert set(saved['logId'].astype(str)) == {'old-1', 'new-1'}


def test_sleep_two_sessions_same_day_saved_as_two_rows(data_dir, fake_sleep):
    """1日に複数セッション（昼寝）があるとき2行として保存されること"""
    fake_sleep([
        _sleep_row('2026-08-20', log_id='main', is_main=True),
        _sleep_row('2026-08-20', log_id='nap', minutes_asleep=40,
                   minutes_in_sleep_period=45, is_main=False),
    ])
    ghf.fetch_endpoint(
        None, 'sleep', start_date=dt.date(2026, 8, 20), end_date=dt.date(2026, 8, 20),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'sleep.csv')
    assert len(saved[saved['dateOfSleep'] == '2026-08-20']) == 2


def test_sleep_efficiency_is_computed(data_dir, fake_sleep):
    row = _sleep_row('2026-08-20', minutes_asleep=300, minutes_in_sleep_period=360)
    fake_sleep([row])
    ghf.fetch_endpoint(
        None, 'sleep', start_date=dt.date(2026, 8, 20), end_date=dt.date(2026, 8, 20),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'sleep.csv')
    assert saved.loc[0, 'efficiency'] == round(300 / 360 * 100)


def test_sleep_levels_has_both_short_and_normal_entries(data_dir, fake_sleep):
    levels = [
        {'logId': '1', 'dateOfSleep': '2026-08-20', 'dateTime': '2026-08-20 23:10:00',
         'level': 'light', 'seconds': 600, 'isShort': False},
        {'logId': '1', 'dateOfSleep': '2026-08-20', 'dateTime': '2026-08-20 23:30:00',
         'level': 'wake', 'seconds': 60, 'isShort': True},
    ]
    fake_sleep([_sleep_row('2026-08-20', log_id='1')], levels)
    ghf.fetch_endpoint(
        None, 'sleep', start_date=dt.date(2026, 8, 20), end_date=dt.date(2026, 8, 20),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'sleep_levels.csv')
    assert set(saved['isShort'].astype(str).str.lower()) == {'true', 'false'}


# =============================================================================
# 重なりセッションの除外（PRレビュー指摘: メイン睡眠に重なる短いセッションを
# Google が別 dataPoint として返すことがある。Issue #74）
# =============================================================================

def _raw_point(point_id: str, start: str, end: str, minutes_in_sleep_period: int,
               main_sleep: bool | None = None) -> dict:
    """生 API 相当の sleep dataPoint（UTC・オフセット0固定でテストを単純化）"""
    metadata = {'stagesStatus': 'SUCCEEDED', 'processed': True}
    if main_sleep is not None:
        metadata['mainSleep'] = main_sleep
    return {
        'name': f'users/me/dataTypes/sleep/dataPoints/{point_id}',
        'sleep': {
            'interval': {
                'startTime': start, 'startUtcOffset': '0s',
                'endTime': end, 'endUtcOffset': '0s',
            },
            'type': 'STAGES',
            'metadata': metadata,
            'summary': {
                'minutesInSleepPeriod': str(minutes_in_sleep_period),
                'minutesAsleep': str(minutes_in_sleep_period),
                'minutesAwake': '0',
                'minutesAfterWakeUp': '0',
                'minutesToFallAsleep': '0',
                'stagesSummary': [],
            },
            'stages': [],
            'shortAwakenings': [],
        },
    }


@pytest.fixture
def fake_points(monkeypatch):
    """_list_sleep_points を差し替えて任意の生 dataPoint 群を返させる"""
    def install(points):
        monkeypatch.setattr(googlehealth_api, '_list_sleep_points', lambda creds, s, e: points)
    return install


def test_overlapping_session_only_the_longer_one_survives(fake_points):
    """重なる2セッションのうち、長い方だけが残ること"""
    points = [
        _raw_point('main', '2026-08-19T23:32:00Z', '2026-08-20T06:56:00Z', 444, main_sleep=True),
        _raw_point('short', '2026-08-19T23:36:00Z', '2026-08-19T23:53:00Z', 17),
    ]
    fake_points(points)

    sleep_rows, _ = googlehealth_api.fetch_sleep_all(
        None, dt.date(2026, 8, 19), dt.date(2026, 8, 20)
    )

    log_ids = {r['logId'] for r in sleep_rows}
    assert log_ids == {'main'}


def test_overlap_winner_decided_by_length_not_mainsleep(fake_points):
    """isMainSleep=True の短いセッションより、mainSleepなしの長いセッションが残ること"""
    points = [
        _raw_point('short-main', '2026-08-19T22:00:00Z', '2026-08-19T22:30:00Z',
                   30, main_sleep=True),
        _raw_point('long-nomain', '2026-08-19T21:00:00Z', '2026-08-20T05:00:00Z', 480),
    ]
    fake_points(points)

    sleep_rows, _ = googlehealth_api.fetch_sleep_all(
        None, dt.date(2026, 8, 19), dt.date(2026, 8, 20)
    )

    log_ids = {r['logId'] for r in sleep_rows}
    assert log_ids == {'long-nomain'}


def test_non_overlapping_sessions_both_kept(fake_points):
    """重ならない2セッション（本睡眠+昼寝）は両方残ること"""
    points = [
        _raw_point('main', '2026-08-19T23:00:00Z', '2026-08-20T07:00:00Z', 480, main_sleep=True),
        _raw_point('nap', '2026-08-20T12:00:00Z', '2026-08-20T12:45:00Z', 45),
    ]
    fake_points(points)

    sleep_rows, _ = googlehealth_api.fetch_sleep_all(
        None, dt.date(2026, 8, 19), dt.date(2026, 8, 20)
    )

    log_ids = {r['logId'] for r in sleep_rows}
    assert log_ids == {'main', 'nap'}


def test_dropped_overlap_count_is_logged(fake_points, capsys):
    """落とした件数が黙って消えずログに出ること"""
    points = [
        _raw_point('main', '2026-08-19T23:32:00Z', '2026-08-20T06:56:00Z', 444, main_sleep=True),
        _raw_point('short', '2026-08-19T23:36:00Z', '2026-08-19T23:53:00Z', 17),
    ]
    fake_points(points)

    googlehealth_api.fetch_sleep_all(None, dt.date(2026, 8, 19), dt.date(2026, 8, 20))

    captured = capsys.readouterr()
    assert '1件' in captured.out
    assert '除外' in captured.out


# =============================================================================
# dailyRollUp 経路（activity / active_zone_minutes / temperature_core, Issue #75）
# =============================================================================

def _rollup_point(year, month, day, **payload):
    """rollupDataPoints の1要素相当を組み立てる（payload は {payloadKey: 値}）"""
    point = {'civilStartTime': {'date': {'year': year, 'month': month, 'day': day}}}
    point.update(payload)
    return point


@pytest.fixture
def fake_post(monkeypatch):
    """googlehealth_api._post を差し替えて呼び出しを記録しつつ任意の応答を返す"""
    def install(responder):
        calls = []

        def fake(creds, path, body):
            calls.append((path, body))
            return responder(path, body)

        monkeypatch.setattr(googlehealth_api, '_post', fake)
        return calls
    return install


def test_daily_rollup_splits_by_type_max_duration_total_calories(fake_post):
    """total-calories は14日上限。40日分の要求は3チャンクに分割されること"""
    calls = fake_post(lambda path, body: {'rollupDataPoints': []})
    googlehealth_api._daily_rollup(
        None, 'total-calories', dt.date(2026, 1, 1), dt.date(2026, 2, 9)  # 40日
    )
    assert len(calls) == 3
    for path, body in calls:
        assert 'total-calories' in path
        s = body['range']['start']['date']
        e = body['range']['end']['date']
        # range.end は排他的（実測）。raw span = end - start が maxDurationDays 以内であること
        span = (dt.date(e['year'], e['month'], e['day']) - dt.date(s['year'], s['month'], s['day'])).days
        assert span <= 14


def test_daily_rollup_splits_by_type_max_duration_steps(fake_post):
    """steps は90日上限。100日分の要求は2チャンクに分割されること"""
    calls = fake_post(lambda path, body: {'rollupDataPoints': []})
    googlehealth_api._daily_rollup(
        None, 'steps', dt.date(2026, 1, 1), dt.date(2026, 4, 10)  # 100日
    )
    assert len(calls) == 2
    for path, body in calls:
        s = body['range']['start']['date']
        e = body['range']['end']['date']
        span = (dt.date(e['year'], e['month'], e['day']) - dt.date(s['year'], s['month'], s['day'])).days
        assert span <= 90


def test_active_zone_minutes_sums_zones(fake_post):
    """activeZoneMinutes が fatBurn+cardio+peak の単純和で算出されること"""
    fake_post(lambda path, body: {'rollupDataPoints': [
        _rollup_point(2026, 8, 11, activeZoneMinutes={
            'sumInFatBurnHeartZone': '20', 'sumInCardioHeartZone': '15', 'sumInPeakHeartZone': '9',
        }),
    ]})
    rows = googlehealth_api.fetch_active_zone_minutes(None, dt.date(2026, 8, 11), dt.date(2026, 8, 11))
    assert rows == [{
        'date': '2026-08-11',
        'activeZoneMinutes': 44.0,
        'fatBurnActiveZoneMinutes': 20.0,
        'cardioActiveZoneMinutes': 15.0,
        'peakActiveZoneMinutes': 9.0,
    }]


def _fake_activity_responder(path, body):
    date = {'year': 2026, 'month': 8, 'day': 15}
    if 'dataTypes/steps' in path:
        return {'rollupDataPoints': [_rollup_point(**date, steps={'countSum': '100'})]}
    if 'dataTypes/distance' in path:
        return {'rollupDataPoints': [_rollup_point(**date, distance={'millimetersSum': '2000000'})]}
    if 'dataTypes/active-minutes' in path:
        return {'rollupDataPoints': [_rollup_point(**date, activeMinutes={
            'activeMinutesRollupByActivityLevel': [
                {'activityLevel': 'LIGHT', 'activeMinutesSum': '50'},
                {'activityLevel': 'MODERATE', 'activeMinutesSum': '10'},
                {'activityLevel': 'VIGOROUS', 'activeMinutesSum': '5'},
            ],
        })]}
    if 'dataTypes/total-calories' in path:
        return {'rollupDataPoints': [_rollup_point(**date, totalCalories={'kcalSum': 2000.5})]}
    raise AssertionError(f'unexpected path: {path}')


def test_activity_activity_calories_and_sedentary_minutes_are_none_with_warning(fake_post, capsys):
    fake_post(_fake_activity_responder)

    rows = googlehealth_api.fetch_activity(None, dt.date(2026, 8, 15), dt.date(2026, 8, 15))

    assert len(rows) == 1
    row = rows[0]
    assert row['activityCalories'] is None
    assert row['sedentaryMinutes'] is None

    captured = capsys.readouterr()
    assert 'activityCalories' in captured.out
    assert 'sedentaryMinutes' in captured.out


def test_activity_distance_converted_mm_to_km(fake_post):
    fake_post(_fake_activity_responder)
    rows = googlehealth_api.fetch_activity(None, dt.date(2026, 8, 15), dt.date(2026, 8, 15))
    assert rows[0]['distance'] == 2.0  # 2,000,000mm = 2km


def test_activity_active_minutes_levels_mapped(fake_post):
    fake_post(_fake_activity_responder)
    rows = googlehealth_api.fetch_activity(None, dt.date(2026, 8, 15), dt.date(2026, 8, 15))
    row = rows[0]
    assert row['lightlyActiveMinutes'] == 50.0
    assert row['fairlyActiveMinutes'] == 10.0
    assert row['veryActiveMinutes'] == 5.0
    assert row['caloriesOut'] == 2000.5
    assert row['steps'] == 100.0


def test_temperature_core_date_time_is_midnight(fake_post):
    fake_post(lambda path, body: {'rollupDataPoints': [
        _rollup_point(2026, 8, 20, coreBodyTemperature={
            'temperatureCelsiusAvg': 36.4, 'temperatureCelsiusMin': 36.4, 'temperatureCelsiusMax': 36.4,
        }),
    ]})
    rows = googlehealth_api.fetch_temperature_core(None, dt.date(2026, 8, 20), dt.date(2026, 8, 20))
    assert rows == [{'date_time': '2026-08-20 00:00:00', 'temperature': 36.4}]


def test_temperature_core_warns_on_multiple_measurements(fake_post, capsys):
    fake_post(lambda path, body: {'rollupDataPoints': [
        _rollup_point(2026, 8, 21, coreBodyTemperature={
            'temperatureCelsiusAvg': 36.3, 'temperatureCelsiusMin': 36.1, 'temperatureCelsiusMax': 36.5,
        }),
    ]})
    googlehealth_api.fetch_temperature_core(None, dt.date(2026, 8, 21), dt.date(2026, 8, 21))

    captured = capsys.readouterr()
    assert '2026-08-21' in captured.out
    assert '複数回測定' in captured.out


def test_temperature_core_no_warning_when_min_equals_max(fake_post, capsys):
    fake_post(lambda path, body: {'rollupDataPoints': [
        _rollup_point(2026, 8, 22, coreBodyTemperature={
            'temperatureCelsiusAvg': 36.2, 'temperatureCelsiusMin': 36.2, 'temperatureCelsiusMax': 36.2,
        }),
    ]})
    googlehealth_api.fetch_temperature_core(None, dt.date(2026, 8, 22), dt.date(2026, 8, 22))

    captured = capsys.readouterr()
    assert '複数回測定' not in captured.out
