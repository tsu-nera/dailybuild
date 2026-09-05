"""googlehealth_fetcher のテスト（Issue #49）

ネットワークを使わない。FETCHERS を差し替えて保存経路のみ検証する。
"""

import datetime as dt

import pandas as pd
import pytest

from lib import googlehealth_fetcher as ghf
from lib.clients import googlehealth_client, googlehealth_sessions
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
            googlehealth_client.FETCHERS, 'hrv', lambda creds, s, e: rows
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
        ghf.fetch_endpoint(None, 'nonexistent_endpoint', days=3)


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
    monkeypatch.setattr(ghf, 'DATA_DIR', repo / 'data' / 'wearable')

    fake_rows([{'date': '2026-08-01', 'daily_rmssd': 30.1, 'deep_rmssd': 28.0}])

    with pytest.raises(FileNotFoundError):
        ghf.fetch_endpoint(None, 'hrv', days=3)


def test_num_coerces_string_values():
    """Google が数値を文字列で返すケースを float に正規化すること"""
    assert googlehealth_client._num('36.5') == 36.5
    assert googlehealth_client._num(36.5) == 36.5
    assert googlehealth_client._num(None) is None
    assert googlehealth_client._num('') is None


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
            googlehealth_client.FETCHERS, 'sleep',
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


def test_sleep_period_replace_keeps_day_with_no_google_session(data_dir, fake_sleep, capsys):
    """期間内でも Google に1件もセッションが無い日は、既存行が残ること
    （replace_csv_period の意味変更、Issue #75 PR #84 レビュー）"""
    existing = pd.DataFrame([
        _sleep_row('2026-08-01', log_id='old-1'),  # Googleにセッション無し -> 残る
        _sleep_row('2026-08-02', log_id='old-2'),  # Googleにセッションあり -> 置き換わる
    ])
    existing.to_csv(data_dir / 'sleep.csv', index=False)
    pd.DataFrame([], columns=['logId', 'dateOfSleep', 'dateTime', 'level', 'seconds', 'isShort']
                ).to_csv(data_dir / 'sleep_levels.csv', index=False)

    fake_sleep([_sleep_row('2026-08-02', log_id='new-1')])
    result = ghf.fetch_endpoint(
        None, 'sleep', start_date=dt.date(2026, 8, 1), end_date=dt.date(2026, 8, 2),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'sleep.csv')
    assert result['records'] == 2
    assert set(saved['logId'].astype(str)) == {'old-1', 'new-1'}

    captured = capsys.readouterr()
    assert '既存行を残した' in captured.out


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
        monkeypatch.setattr(googlehealth_client, '_list_sleep_points', lambda creds, s, e: points)
    return install


def test_overlapping_session_only_the_longer_one_survives(fake_points):
    """重なる2セッションのうち、長い方だけが残ること"""
    points = [
        _raw_point('main', '2026-08-19T23:32:00Z', '2026-08-20T06:56:00Z', 444, main_sleep=True),
        _raw_point('short', '2026-08-19T23:36:00Z', '2026-08-19T23:53:00Z', 17),
    ]
    fake_points(points)

    sleep_rows, _ = googlehealth_client.fetch_sleep_all(
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

    sleep_rows, _ = googlehealth_client.fetch_sleep_all(
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

    sleep_rows, _ = googlehealth_client.fetch_sleep_all(
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

    googlehealth_client.fetch_sleep_all(None, dt.date(2026, 8, 19), dt.date(2026, 8, 20))

    captured = capsys.readouterr()
    assert '1件' in captured.out
    assert '除外' in captured.out


# =============================================================================
# dailyRollUp 経路（activity / active_zone_minutes, Issue #75）
# =============================================================================

def _rollup_point(year, month, day, **payload):
    """rollupDataPoints の1要素相当を組み立てる（payload は {payloadKey: 値}）"""
    point = {'civilStartTime': {'date': {'year': year, 'month': month, 'day': day}}}
    point.update(payload)
    return point


@pytest.fixture
def fake_post(monkeypatch):
    """googlehealth_client._post を差し替えて呼び出しを記録しつつ任意の応答を返す"""
    def install(responder):
        calls = []

        def fake(creds, path, body):
            calls.append((path, body))
            return responder(path, body)

        monkeypatch.setattr(googlehealth_client, '_post', fake)
        return calls
    return install


def test_daily_rollup_splits_by_type_max_duration_total_calories(fake_post):
    """total-calories は14日上限。40日分の要求は3チャンクに分割されること"""
    calls = fake_post(lambda path, body: {'rollupDataPoints': []})
    googlehealth_client._daily_rollup(
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
    googlehealth_client._daily_rollup(
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
    rows = googlehealth_client.fetch_active_zone_minutes(None, dt.date(2026, 8, 11), dt.date(2026, 8, 11))
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

    rows = googlehealth_client.fetch_activity(None, dt.date(2026, 8, 15), dt.date(2026, 8, 15))

    assert len(rows) == 1
    row = rows[0]
    assert row['activityCalories'] is None
    assert row['sedentaryMinutes'] is None

    captured = capsys.readouterr()
    assert 'activityCalories' in captured.out
    assert 'sedentaryMinutes' in captured.out


def test_activity_distance_converted_mm_to_km(fake_post):
    fake_post(_fake_activity_responder)
    rows = googlehealth_client.fetch_activity(None, dt.date(2026, 8, 15), dt.date(2026, 8, 15))
    assert rows[0]['distance'] == 2.0  # 2,000,000mm = 2km


def test_activity_active_minutes_levels_mapped(fake_post):
    fake_post(_fake_activity_responder)
    rows = googlehealth_client.fetch_activity(None, dt.date(2026, 8, 15), dt.date(2026, 8, 15))
    row = rows[0]
    assert row['lightlyActiveMinutes'] == 50.0
    assert row['fairlyActiveMinutes'] == 10.0
    assert row['veryActiveMinutes'] == 5.0
    assert row['caloriesOut'] == 2000.5
    assert row['steps'] == 100.0


# =============================================================================
# temperature_core: dailyRollUp ではなく list + civilTime を使う（PR #84 レビュー
# 指摘: 既存 CSV に実測時刻の行と00:00:00固定の行が混在しており、日次平均で
# 埋めると実測時刻行と二重になる。civilTime をそのまま使う）
# =============================================================================

def _temp_point(point_id, year, month, day, hours=None, minutes=None, seconds=None,
                temp=36.5):
    """core-body-temperature の dataPoint 1件相当。time を省略すると0時0分0秒扱い"""
    civil_time = {'date': {'year': year, 'month': month, 'day': day}}
    time = {}
    if hours is not None:
        time['hours'] = hours
    if minutes is not None:
        time['minutes'] = minutes
    if seconds is not None:
        time['seconds'] = seconds
    if time:
        civil_time['time'] = time
    return {
        'name': f'users/me/dataTypes/core-body-temperature/dataPoints/{point_id}',
        'coreBodyTemperature': {
            'sampleTime': {
                'physicalTime': f'{year}-{month:02d}-{day:02d}T00:00:00Z',
                'utcOffset': '32400s',
                'civilTime': civil_time,
            },
            'temperatureCelsius': temp,
            'id': point_id,
        },
    }


@pytest.fixture
def fake_get_pages(monkeypatch):
    """googlehealth_client._get を差し替えて、ページを順番に返す"""
    def install(pages):
        it = iter(pages)

        def fake(creds, path, params=None):
            return next(it)

        monkeypatch.setattr(googlehealth_client, '_get', fake)
    return install


def test_temperature_core_uses_civil_time(fake_get_pages):
    """civilTime をそのまま date_time にすること"""
    fake_get_pages([
        {'dataPoints': [_temp_point('1', 2026, 8, 23, hours=5, minutes=49, seconds=21, temp=36.1)]},
    ])
    rows = googlehealth_client.fetch_temperature_core(None, dt.date(2026, 8, 20), dt.date(2026, 8, 25))
    assert rows == [{'date_time': '2026-08-23 05:49:21', 'temperature': 36.1}]


def test_temperature_core_missing_time_defaults_to_zero(fake_get_pages):
    """civilTime.time が省略された（0時0分0秒）場合、00:00:00 として扱うこと"""
    fake_get_pages([
        {'dataPoints': [_temp_point('2', 2026, 8, 24, temp=36.0)]},  # time 省略
    ])
    rows = googlehealth_client.fetch_temperature_core(None, dt.date(2026, 8, 20), dt.date(2026, 8, 25))
    assert rows == [{'date_time': '2026-08-24 00:00:00', 'temperature': 36.0}]


def test_temperature_core_filters_by_date_range(fake_get_pages):
    fake_get_pages([
        {'dataPoints': [
            _temp_point('a', 2026, 8, 19, hours=6, temp=36.2),  # 範囲外
            _temp_point('b', 2026, 8, 20, hours=6, temp=36.3),  # 範囲内
        ]},
    ])
    rows = googlehealth_client.fetch_temperature_core(None, dt.date(2026, 8, 20), dt.date(2026, 8, 25))
    assert [r['date_time'][:10] for r in rows] == ['2026-08-20']


def test_temperature_core_stops_paging_when_page_older_than_start(fake_get_pages):
    """ページ内の最新日が start_date より古くなった時点で打ち切ること
    （フィクスチャに2ページしか用意していないため、打ち切らず3ページ目を
    要求すると StopIteration で失敗する）
    """
    fake_get_pages([
        {'dataPoints': [_temp_point('1', 2026, 8, 24, hours=6, temp=36.2)],
         'nextPageToken': 'tok1'},
        {'dataPoints': [_temp_point('2', 2026, 7, 1, hours=6, temp=35.9)],
         'nextPageToken': 'tok2'},
    ])
    rows = googlehealth_client.fetch_temperature_core(None, dt.date(2026, 8, 20), dt.date(2026, 8, 25))
    assert [r['date_time'][:10] for r in rows] == ['2026-08-24']


# =============================================================================
# activity: activityCalories / sedentaryMinutes の merge 挙動（PR #84 レビュー
# 指摘: 既存の日付は merge_csv の NaN フォールバックで旧値が残り、新しい日付は
# 空になる。テスト計画に「既存の日付なので旧値が残る」旨を明記する）
# =============================================================================

@pytest.fixture
def fake_activity_rows(monkeypatch):
    """FETCHERS['activity'] を差し替えて任意の行を返させる"""
    def install(rows):
        monkeypatch.setitem(
            googlehealth_client.FETCHERS, 'activity', lambda creds, s, e: rows
        )
    return install


def test_activity_existing_date_keeps_old_activity_calories_and_sedentary_minutes(
    data_dir, fake_activity_rows,
):
    """merge_csv の NaN フォールバック: 既存の日付は旧値が残ること"""
    existing = pd.DataFrame(
        {'caloriesOut': [2000.0], 'activityCalories': [700.0], 'steps': [5000.0],
         'distance': [3.5], 'sedentaryMinutes': [900.0], 'lightlyActiveMinutes': [120.0],
         'fairlyActiveMinutes': [30.0], 'veryActiveMinutes': [5.0]},
        index=pd.to_datetime(['2026-08-15']),
    )
    existing.index.name = 'date'
    existing.to_csv(data_dir / 'activity.csv')

    fake_activity_rows([{
        'date': '2026-08-15', 'caloriesOut': 1900.0, 'activityCalories': None,
        'steps': 5100.0, 'distance': 3.6, 'sedentaryMinutes': None,
        'lightlyActiveMinutes': 121.0, 'fairlyActiveMinutes': 31.0, 'veryActiveMinutes': 6.0,
    }])
    ghf.fetch_endpoint(
        None, 'activity', start_date=dt.date(2026, 8, 15), end_date=dt.date(2026, 8, 15),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'activity.csv')
    row = saved[saved['date'] == '2026-08-15'].iloc[0]
    assert row['activityCalories'] == 700.0  # 旧値が残る
    assert row['sedentaryMinutes'] == 900.0  # 旧値が残る
    assert row['caloriesOut'] == 1900.0  # 新しい値で上書きされる


def test_activity_new_date_has_empty_activity_calories_and_sedentary_minutes(
    data_dir, fake_activity_rows,
):
    """既存 CSV に無い日付では activityCalories/sedentaryMinutes が空になること"""
    fake_activity_rows([{
        'date': '2026-08-20', 'caloriesOut': 1900.0, 'activityCalories': None,
        'steps': 5100.0, 'distance': 3.6, 'sedentaryMinutes': None,
        'lightlyActiveMinutes': 121.0, 'fairlyActiveMinutes': 31.0, 'veryActiveMinutes': 6.0,
    }])
    ghf.fetch_endpoint(
        None, 'activity', start_date=dt.date(2026, 8, 20), end_date=dt.date(2026, 8, 20),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'activity.csv')
    row = saved[saved['date'] == '2026-08-20'].iloc[0]
    assert pd.isna(row['activityCalories'])
    assert pd.isna(row['sedentaryMinutes'])


def test_activity_refetch_keeps_dates_missing_from_new_data(data_dir, fake_activity_rows):
    """全期間の再取得（#120）で、取得期間に含まれていても新データに無い日付は消さない。

    Google 全再取得で Google が返さない日を欠測として捏造しないことの確認。
    """
    existing = pd.DataFrame(
        {'caloriesOut': [2000.0, 2100.0], 'activityCalories': [700.0, 710.0],
         'steps': [5000.0, 5200.0], 'distance': [3.5, 3.6],
         'sedentaryMinutes': [900.0, 910.0], 'lightlyActiveMinutes': [120.0, 122.0],
         'fairlyActiveMinutes': [30.0, 32.0], 'veryActiveMinutes': [5.0, 6.0]},
        index=pd.to_datetime(['2026-08-15', '2026-08-16']),
    )
    existing.index.name = 'date'
    existing.to_csv(data_dir / 'activity.csv')

    # Google は 2026-08-15 の1行しか返さない（2026-08-16 は欠測扱いで返ってこない）
    fake_activity_rows([{
        'date': '2026-08-15', 'caloriesOut': 1900.0, 'activityCalories': None,
        'steps': 5100.0, 'distance': 3.6, 'sedentaryMinutes': None,
        'lightlyActiveMinutes': 121.0, 'fairlyActiveMinutes': 31.0, 'veryActiveMinutes': 6.0,
    }])
    ghf.fetch_endpoint(
        None, 'activity', start_date=dt.date(2026, 8, 15), end_date=dt.date(2026, 8, 16),
        allow_history_rewrite=True,
    )

    saved = pd.read_csv(data_dir / 'activity.csv')
    assert '2026-08-16' in saved['date'].values  # 新データに無い日付の行が消えていない
    row = saved[saved['date'] == '2026-08-16'].iloc[0]
    assert row['caloriesOut'] == 2100.0  # 既存値のまま


# =============================================================================
# caffeine: nutrition-log から CAFFEINE のみ拾う（Issue #90）
# =============================================================================

def _nutrition_point(point_id: str, start_time: str, offset: str = '32400s',
                     caffeine_grams: float | None = None,
                     package_name: str = 'com.AWSoft.CaffeineClock',
                     platform: str = 'HEALTH_CONNECT') -> dict:
    """nutrition-log の dataPoint 1件相当。caffeine_grams=None なら macros のみ
    （Cronometer/Fitbit 由来の食事ログ）を模す"""
    nutrients = [{'quantity': {'grams': 12.3}, 'nutrient': 'CARBOHYDRATES'}]
    if caffeine_grams is not None:
        nutrients.append({'quantity': {'grams': caffeine_grams}, 'nutrient': 'CAFFEINE'})
    return {
        'name': f'users/me/dataTypes/nutrition-log/dataPoints/{point_id}',
        'dataSource': {
            'recordingMethod': 'UNKNOWN',
            'device': {},
            'application': {'packageName': package_name},
            'platform': platform,
        },
        'nutritionLog': {
            'interval': {'startTime': start_time, 'startUtcOffset': offset},
            'nutrients': nutrients,
        },
    }


@pytest.fixture
def caffeine_dir(tmp_path, monkeypatch):
    """ENDPOINTS['caffeine']['output'] を差し替える

    exercise 等と違い GOOGLEHEALTH_DIR は fetch_endpoint 実行時ではなく
    モジュール読み込み時に ENDPOINTS へ束縛済みなので、GOOGLEHEALTH_DIR を
    monkeypatch しても効かない。config の output を直接差し替える。
    """
    out = tmp_path / 'caffeine.csv'
    monkeypatch.setitem(ghf.ENDPOINTS['caffeine'], 'output', out)
    return out


def test_fetch_caffeine_keeps_only_caffeine_nutrient(fake_get_pages):
    """CAFFEINE を含む点だけを拾い、macros のみの食事ログは捨てること"""
    fake_get_pages([{'dataPoints': [
        _nutrition_point('cronometer-1', '2026-08-26T12:00:00Z'),  # macrosのみ
        _nutrition_point('caffeine-1', '2026-08-26T23:12:03.787Z', caffeine_grams=0.0475),
    ]}])

    rows = googlehealth_client.fetch_caffeine(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert [r['id'] for r in rows] == ['caffeine-1']


def test_fetch_caffeine_converts_grams_to_mg(fake_get_pages):
    """0.0475 g -> 47.5 mg に変換すること"""
    fake_get_pages([{'dataPoints': [
        _nutrition_point('caffeine-1', '2026-08-26T23:12:03.787Z', caffeine_grams=0.0475),
    ]}])

    rows = googlehealth_client.fetch_caffeine(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['caffeine_mg'] == 47.5
    assert rows[0]['date'] == '2026-08-27'  # startTime(UTC) + offset(+9h) でローカル日付
    assert rows[0]['package_name'] == 'com.AWSoft.CaffeineClock'
    assert rows[0]['platform'] == 'HEALTH_CONNECT'


def test_fetch_caffeine_paging_stops_by_all_datapoints_not_only_caffeine(fake_get_pages):
    """CAFFEINE を含まないページでも、dataPoint の日付で打ち切りが効くこと

    （落とし穴の再発防止: カフェイン記録は疎なので、CAFFEINE 行だけで
    打ち切り判定すると全履歴を引いてしまう）
    """
    fake_get_pages([
        {'dataPoints': [
            _nutrition_point('caffeine-1', '2026-08-26T23:12:03.787Z', caffeine_grams=0.0475),
        ], 'nextPageToken': 'tok1'},
        # CAFFEINE を1件も含まないページだが、日付は start_date より古い
        {'dataPoints': [
            _nutrition_point('cronometer-old', '2026-07-01T12:00:00Z'),
        ], 'nextPageToken': 'tok2'},
    ])

    # フィクスチャは2ページしか用意していないため、打ち切らず3ページ目を
    # 要求すると StopIteration で失敗する
    rows = googlehealth_client.fetch_caffeine(None, dt.date(2026, 8, 20), dt.date(2026, 8, 27))

    assert [r['id'] for r in rows] == ['caffeine-1']


def test_caffeine_merge_key_idempotent_across_two_saves(caffeine_dir, monkeypatch):
    """同じ id を2回保存しても行数が増えないこと（id は19桁、dtype=str 必須）"""
    row = {
        'id': '7641590239346029000', 'time': '2026-08-27 08:12:03',
        'date': '2026-08-27', 'caffeine_mg': 47.5,
        'package_name': 'com.AWSoft.CaffeineClock', 'platform': 'HEALTH_CONNECT',
        'recording_method': 'UNKNOWN',
    }
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'caffeine', lambda creds, s, e: [row])

    ghf.fetch_endpoint(None, 'caffeine', days=3)
    result = ghf.fetch_endpoint(None, 'caffeine', days=3)

    assert result['records'] == 1
    saved = pd.read_csv(caffeine_dir, dtype={'id': str})
    assert len(saved) == 1
    assert saved.loc[0, 'id'] == '7641590239346029000'


def test_caffeine_allow_empty_does_not_error(caffeine_dir, monkeypatch):
    """0件は正常でありうるためエラーにせず、CSV も作らないこと"""
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'caffeine', lambda creds, s, e: [])

    result = ghf.fetch_endpoint(None, 'caffeine', days=3)

    assert result['records'] == 0
    assert 'error' not in result
    assert not caffeine_dir.exists()


def test_allow_empty_absent_endpoint_still_errors_on_zero_rows(data_dir, fake_rows):
    """allow_empty の無いエンドポイント（hrv）では従来通り0件がエラーになること"""
    fake_rows([])
    result = ghf.fetch_endpoint(None, 'hrv', days=3)
    assert result['records'] == 0
    assert result['error']


# =============================================================================
# heart_rate: FITBIT / HEALTH_CONNECT の2系統選択（Issue #78）
# =============================================================================

def _hr_point(point_id: str, year: int, month: int, day: int, bpm: float,
             platform: str, calculation_method: str | None = None) -> dict:
    payload = {
        'date': {'year': year, 'month': month, 'day': day},
        'beatsPerMinute': str(bpm),
    }
    if calculation_method:
        payload['dailyRestingHeartRateMetadata'] = {'calculationMethod': calculation_method}
    return {
        'name': f'users/me/dataTypes/daily-resting-heart-rate/dataPoints/{point_id}',
        'dataSource': {'platform': platform},
        'dailyRestingHeartRate': payload,
    }


def test_heart_rate_prefers_fitbit_over_health_connect(fake_get_pages):
    """同じ日付に2系統届いたら FITBIT 側の値だけが行になること"""
    fake_get_pages([{'dataPoints': [
        _hr_point('hc', 2026, 8, 20, 49, 'HEALTH_CONNECT'),
        _hr_point('fb', 2026, 8, 20, 56, 'FITBIT', calculation_method='WITH_SLEEP'),
    ]}])
    rows = googlehealth_client.fetch_heart_rate(None, dt.date(2026, 8, 20), dt.date(2026, 8, 20))
    assert rows == [{'date': '2026-08-20', 'resting_heart_rate': 56.0}]


def test_heart_rate_skips_day_with_health_connect_only(fake_get_pages, capsys):
    """FITBIT 点が無く HEALTH_CONNECT のみの日は、低い値を混ぜず行を作らないこと"""
    fake_get_pages([{'dataPoints': [
        _hr_point('hc', 2026, 8, 21, 49, 'HEALTH_CONNECT'),
    ]}])
    rows = googlehealth_client.fetch_heart_rate(None, dt.date(2026, 8, 21), dt.date(2026, 8, 21))
    assert rows == []
    captured = capsys.readouterr()
    assert '1件' in captured.out


def test_heart_rate_prefers_with_sleep_among_multiple_fitbit_points(fake_get_pages):
    """FITBIT 点が複数あるとき WITH_SLEEP を持つ方が選ばれること"""
    fake_get_pages([{'dataPoints': [
        _hr_point('fb1', 2026, 8, 22, 55, 'FITBIT'),
        _hr_point('fb2', 2026, 8, 22, 57, 'FITBIT', calculation_method='WITH_SLEEP'),
    ]}])
    rows = googlehealth_client.fetch_heart_rate(None, dt.date(2026, 8, 22), dt.date(2026, 8, 22))
    assert rows == [{'date': '2026-08-22', 'resting_heart_rate': 57.0}]


def test_daily_rows_without_pick_is_unchanged(fake_get_pages):
    """pick を渡さない既存経路（hrv 等）の回帰: 1点1行のまま変わらないこと"""
    fake_get_pages([{'dataPoints': [
        {'dailyHeartRateVariability': {
            'date': {'year': 2026, 'month': 8, 'day': 20},
            'averageHeartRateVariabilityMilliseconds': '30.0',
        }},
    ]}])
    rows = googlehealth_client.fetch_hrv(None, dt.date(2026, 8, 20), dt.date(2026, 8, 20))
    assert rows == [{'date': '2026-08-20', 'daily_rmssd': 30.0, 'deep_rmssd': None}]


# =============================================================================
# spo2: 日付ラベルは「その夜が始まった暦日」。正午〜正午の窓で重なる睡眠
# セッションの dateOfSleep に解決する（Issue #78）
# =============================================================================

def _spo2_point(point_id: str, year: int, month: int, day: int,
                avg: float = 97.0, lo: float = 95.0, hi: float = 99.0) -> dict:
    return {
        'name': f'users/me/dataTypes/daily-oxygen-saturation/dataPoints/{point_id}',
        'dataSource': {'platform': 'FITBIT', 'recordingMethod': 'PASSIVELY_MEASURED'},
        'dailyOxygenSaturation': {
            'date': {'year': year, 'month': month, 'day': day},
            'averagePercentage': str(avg),
            'lowerBoundPercentage': str(lo),
            'upperBoundPercentage': str(hi),
        },
    }


def test_spo2_resolves_date_via_overlapping_sleep_session_after_midnight_start(
    fake_get_pages, fake_points,
):
    """深夜0時過ぎ就寝（セッション開始日は翌日）でも正午〜正午の窓で正しく解決すること

    素朴な「Google日付+1」規則ならこのケースでも同じ結果になりうるが、ここで
    検証したいのは機械的な+1でなく実時刻での引き当てであること。PR本文に
    記載の通り、素朴な開始日規則は別の10日で破綻することを実測済み。
    """
    fake_get_pages([{'dataPoints': [_spo2_point('p1', 2026, 8, 18, avg=97.5, lo=95.0, hi=99.0)]}])
    fake_points([
        _raw_point('s1', '2026-08-19T00:05:00Z', '2026-08-19T07:00:00Z', 415, main_sleep=True),
    ])

    rows = googlehealth_client.fetch_spo2(None, dt.date(2026, 8, 18), dt.date(2026, 8, 19))

    assert rows == [{'date': '2026-08-19', 'avg_spo2': 97.5, 'min_spo2': 95.0, 'max_spo2': 99.0}]


def test_spo2_point_without_overlapping_session_is_skipped(fake_get_pages, fake_points, capsys):
    """重なる睡眠セッションが無い点は行にならないこと（一律+1日のフォールバックはしない）"""
    fake_get_pages([{'dataPoints': [_spo2_point('p1', 2026, 8, 20)]}])
    fake_points([])

    rows = googlehealth_client.fetch_spo2(None, dt.date(2026, 8, 20), dt.date(2026, 8, 21))

    assert rows == []
    captured = capsys.readouterr()
    assert '1件' in captured.out


def _sleep_row_dict(date_of_sleep: str, start_time: str, end_time: str,
                    is_main: bool = True, time_in_bed: int = 480) -> dict:
    return {
        'startTime': start_time, 'endTime': end_time, 'dateOfSleep': date_of_sleep,
        'isMainSleep': is_main, 'timeInBed': time_in_bed,
    }


def test_spo2_filters_out_of_range_resolved_dates(fake_get_pages, monkeypatch):
    """睡眠セッションで解決した日付が要求期間の外なら返らないこと"""
    from lib.clients import googlehealth_sleep as gh_sleep

    fake_get_pages([{'dataPoints': [
        _spo2_point('out-before', 2026, 8, 9),
        _spo2_point('in-range', 2026, 8, 20),
        _spo2_point('out-after', 2026, 8, 30),
    ]}])

    def fake_fetch_sleep_all(creds, s, e):
        return [
            _sleep_row_dict('2026-08-10', '2026-08-09T23:00:00.000', '2026-08-10T07:00:00.000'),
            _sleep_row_dict('2026-08-21', '2026-08-20T23:00:00.000', '2026-08-21T07:00:00.000'),
            _sleep_row_dict('2026-08-31', '2026-08-30T23:00:00.000', '2026-08-31T07:00:00.000'),
        ], []

    monkeypatch.setattr(gh_sleep, 'fetch_sleep_all', fake_fetch_sleep_all)

    rows = googlehealth_client.fetch_spo2(None, dt.date(2026, 8, 15), dt.date(2026, 8, 25))

    assert [r['date'] for r in rows] == ['2026-08-21']


def test_spo2_sleep_window_starts_one_day_before_start_date(fake_get_pages, monkeypatch):
    """睡眠セッションを start_date-1 日から取ること

    Google 側の最も古い対象点は start_date-1 日のラベルを持つ（stop_before）。
    その窓に重なるのは dateOfSleep = start_date-1 のセッションなので、
    start_date から取ると候補が欠ける。
    """
    from lib.clients import googlehealth_sleep as gh_sleep

    fake_get_pages([{'dataPoints': [_spo2_point('p1', 2026, 9, 3)]}])
    called = {}

    def fake_fetch_sleep_all(creds, s, e):
        called['start'], called['end'] = s, e
        return [], []

    monkeypatch.setattr(gh_sleep, 'fetch_sleep_all', fake_fetch_sleep_all)
    googlehealth_client.fetch_spo2(None, dt.date(2026, 9, 3), dt.date(2026, 9, 5))

    assert called['start'] == dt.date(2026, 9, 2), '睡眠の取得が start_date から始まっている'
    assert called['end'] == dt.date(2026, 9, 5)


def test_spo2_resolution_is_independent_of_window_length(fake_get_pages, monkeypatch):
    """同じ点が、短い窓でも長い窓でも同じ日付に解決すること

    実データでの再現（2026-09-02 の点）:
      - 前夜の主睡眠 09-01 20:31 -> 09-02 12:37（timeInBed 966、正午を37分跨ぐ）
      - その夜の主睡眠 09-02 21:41 -> 09-03 10:02（timeInBed 741）
    どちらも [09-02 12:00, 09-03 12:00) に重なる。長い方（966）が採られて
    09-02 になるのが正しいが、睡眠を start_date から取ると 966 の方が
    候補に入らず 09-03 に解決し、既存の正しい行を1日ずらして上書きしていた。
    """
    from lib.clients import googlehealth_sleep as gh_sleep

    all_sessions = [
        _sleep_row_dict('2026-09-02', '2026-09-01T20:31:00.000', '2026-09-02T12:37:00.000',
                        time_in_bed=966),
        _sleep_row_dict('2026-09-03', '2026-09-02T21:41:00.000', '2026-09-03T10:02:00.000',
                        time_in_bed=741),
    ]

    def fake_fetch_sleep_all(creds, s, e):
        # 実装と同じく dateOfSleep で期間を切る
        return [r for r in all_sessions
                if s.isoformat() <= r['dateOfSleep'] <= e.isoformat()], []

    monkeypatch.setattr(gh_sleep, 'fetch_sleep_all', fake_fetch_sleep_all)

    resolved = []
    for start in (dt.date(2026, 9, 3), dt.date(2026, 8, 1)):
        fake_get_pages([{'dataPoints': [_spo2_point('p1', 2026, 9, 2, avg=96.5)]}])
        rows = googlehealth_client.fetch_spo2(None, start, dt.date(2026, 9, 5))
        resolved.append([r['date'] for r in rows])

    # 09-02 に解決するので、start=09-03 の窓では範囲外として落ちる（09-03 を捏造しない）
    assert resolved[0] == [], f'短い窓で日付がずれている: {resolved[0]}'
    assert resolved[1] == ['2026-09-02'], f'長い窓の解決が変わった: {resolved[1]}'


# =============================================================================
# weight / body_fat: Health Connect 経由の体重・体脂肪率（Issue #94）
# =============================================================================

def _body_measure_point(point_id: str, payload_key: str, value_key: str, value,
                        physical_time: str = '2026-08-26T20:37:32Z',
                        utc_offset: str = '32400s',
                        package_name: str = 'jp.healthplanet.healthplanetapp',
                        platform: str = 'HEALTH_CONNECT') -> dict:
    """weight / body-fat の dataPoint 1件相当"""
    payload_field = 'weight' if payload_key == 'weight' else 'bodyFat'
    return {
        'name': f'users/me/dataTypes/{payload_key}/dataPoints/{point_id}',
        'dataSource': {
            'recordingMethod': 'UNKNOWN',
            'device': {},
            'application': {'packageName': package_name},
            'platform': platform,
        },
        payload_field: {
            'sampleTime': {'physicalTime': physical_time, 'utcOffset': utc_offset},
            value_key: value,
        },
    }


def test_fetch_weight_converts_grams_to_kg(fake_get_pages):
    """weightGrams: 61300 が weight_kg: 61.3 になること（単位換算の回帰防止）"""
    fake_get_pages([{'dataPoints': [
        _body_measure_point('weight-1', 'weight', 'weightGrams', 61300),
    ]}])

    rows = googlehealth_client.fetch_weight(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['weight_kg'] == 61.3


def test_fetch_weight_uses_local_time_not_utc_date(fake_get_pages):
    """physicalTime(UTC) + utcOffset からローカル日付が出ること

    2026-08-26T20:37:32Z + 32400s(+9h) -> time は 2026-08-27 05:37:32、
    date は 2026-08-27。UTC の日付(08-26)のまま保存されたら FAIL
    """
    fake_get_pages([{'dataPoints': [
        _body_measure_point('weight-1', 'weight', 'weightGrams', 61300,
                            physical_time='2026-08-26T20:37:32Z', utc_offset='32400s'),
    ]}])

    rows = googlehealth_client.fetch_weight(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['time'] == '2026-08-27 05:37:32'
    assert rows[0]['date'] == '2026-08-27'


def test_fetch_body_fat_keeps_percentage_as_is(fake_get_pages):
    fake_get_pages([{'dataPoints': [
        _body_measure_point('bodyfat-1', 'body-fat', 'percentage', 18.3),
    ]}])

    rows = googlehealth_client.fetch_body_fat(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['body_fat_rate'] == 18.3
    assert rows[0]['date'] == '2026-08-27'


@pytest.fixture
def weight_dir(tmp_path, monkeypatch):
    """ENDPOINTS['weight']['output'] を tmp_path 配下に差し替える（caffeine_dir と同じ理由）"""
    out = tmp_path / 'weight.csv'
    monkeypatch.setitem(ghf.ENDPOINTS['weight'], 'output', out)
    return out


def test_weight_merge_key_idempotent_across_two_saves(weight_dir, monkeypatch):
    """同じ id を2回保存しても行数が増えないこと（id は19桁、dtype=str 必須）"""
    row = {
        'id': '2744074805234614368', 'time': '2026-08-27 05:37:32',
        'date': '2026-08-27', 'weight_kg': 61.3,
        'package_name': 'jp.healthplanet.healthplanetapp', 'platform': 'HEALTH_CONNECT',
        'recording_method': 'UNKNOWN',
    }
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'weight', lambda creds, s, e: [row])

    ghf.fetch_endpoint(None, 'weight', days=3)
    result = ghf.fetch_endpoint(None, 'weight', days=3)

    assert result['records'] == 1
    saved = pd.read_csv(weight_dir, dtype={'id': str})
    assert len(saved) == 1
    assert saved.loc[0, 'id'] == '2744074805234614368'


def test_weight_allow_empty_does_not_error(weight_dir, monkeypatch):
    """計測が疎なため0件は正常。エラーにせず CSV も作らないこと"""
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'weight', lambda creds, s, e: [])

    result = ghf.fetch_endpoint(None, 'weight', days=3)

    assert result['records'] == 0
    assert 'error' not in result
    assert not weight_dir.exists()


# =============================================================================
# nutrition / nutrition_logs: nutrition-log の個別食事ログとその合算（Issue #95）
# =============================================================================

def _nutrition_log_point(point_id: str, year: int, month: int, day: int,
                         food_name: str | None = 'ご飯(一膳)',
                         meal_type: str | None = 'DINNER',
                         amount: float = 3.0, unit_id: str = '304',
                         kcal: float = 705, protein_g: float = 10.0,
                         fat_g: float = 1.2, carbs_g: float = 150.0,
                         fiber_g: float = 0.3, sodium_g: float = 0.001,
                         food_id: str = '781681941') -> dict:
    """nutrition-log の dataPoint 1件相当。food_name=None なら
    foodDisplayName の無い点（カフェイン等、nutrition 系では捨てる対象）を模す"""
    nutrition = {
        'interval': {
            'startTime': f'{year}-{month:02d}-{day:02d}T12:00:00Z',
            'startUtcOffset': '32400s',
            'civilStartTime': {'date': {'year': year, 'month': month, 'day': day}},
        },
    }
    if food_name is not None:
        nutrition['foodDisplayName'] = food_name
        nutrition['food'] = f'users/me/dataTypes/food/dataPoints/{food_id}'
        if meal_type is not None:
            nutrition['mealType'] = meal_type
        nutrition['serving'] = {
            'amount': amount,
            'foodMeasurementUnit': f'users/me/dataTypes/food-measurement-unit/dataPoints/{unit_id}',
        }
        nutrition['energy'] = {'kcal': kcal}
        nutrition['totalFat'] = {'grams': fat_g}
        nutrition['totalCarbohydrate'] = {'grams': carbs_g}
        nutrition['nutrients'] = [
            {'nutrient': 'PROTEIN', 'quantity': {'grams': protein_g}},
            {'nutrient': 'DIETARY_FIBER', 'quantity': {'grams': fiber_g}},
            {'nutrient': 'SODIUM', 'quantity': {'grams': sodium_g}},
        ]
    else:
        nutrition['nutrients'] = [{'nutrient': 'CAFFEINE', 'quantity': {'grams': 0.05}}]

    return {
        'name': f'users/me/dataTypes/nutrition-log/dataPoints/{point_id}',
        'dataSource': {
            'recordingMethod': 'UNKNOWN', 'device': {},
            'application': {'packageName': None}, 'platform': 'FITBIT_WEB_API',
        },
        'nutritionLog': nutrition,
    }


@pytest.fixture
def fake_nutrition_pages(monkeypatch):
    """googlehealth_client._get を差し替える。nutrition-log のページングと
    food-measurement-unit の単体照会（既定 'グラム'）の両方をこの1つで賄う

    fake_get_pages は path を見ずに単純に順送りするため、ページ取得の
    合間に挟まる unit 単体照会（別の path）と共存できない。
    """
    # モジュールレベルのキャッシュを汚すと他ファイル（test_googlehealth_parity.py）の
    # 実 API 呼び出しがこのフェイクの値を読んでしまうため、退避して確実に戻す
    saved_cache = dict(googlehealth_sessions._UNIT_NAME_CACHE)
    googlehealth_sessions._UNIT_NAME_CACHE.clear()

    def install(pages):
        it = iter(pages)

        def fake(creds, path, params=None):
            if 'food-measurement-unit' in path:
                return {'foodMeasurementUnit': {'displayName': 'グラム'}}
            return next(it)

        monkeypatch.setattr(googlehealth_client, '_get', fake)

    yield install

    googlehealth_sessions._UNIT_NAME_CACHE.clear()
    googlehealth_sessions._UNIT_NAME_CACHE.update(saved_cache)


def test_fetch_nutrition_logs_excludes_points_without_food_display_name(fake_nutrition_pages):
    """foodDisplayName が無い点（カフェイン等）は食事ログとして拾われないこと"""
    fake_nutrition_pages([{'dataPoints': [
        _nutrition_log_point('caffeine-1', 2026, 8, 26, food_name=None),
        _nutrition_log_point('meal-1', 2026, 8, 26),
    ]}])

    rows = googlehealth_client.fetch_nutrition_logs(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert [r['logId'] for r in rows] == ['meal-1']


def test_fetch_nutrition_logs_converts_meal_type_to_id(fake_nutrition_pages):
    """DINNER -> 5 のように mealType を数値へ変換すること"""
    fake_nutrition_pages([{'dataPoints': [
        _nutrition_log_point('meal-1', 2026, 8, 26, meal_type='DINNER'),
    ]}])

    rows = googlehealth_client.fetch_nutrition_logs(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['mealTypeId'] == 5


def test_fetch_nutrition_logs_unknown_meal_type_becomes_empty_with_warning(
    fake_nutrition_pages, capsys,
):
    """未知の mealType は mealTypeId を空にし、警告を出すこと"""
    fake_nutrition_pages([{'dataPoints': [
        _nutrition_log_point('meal-1', 2026, 8, 26, meal_type='SNACK'),
    ]}])

    rows = googlehealth_client.fetch_nutrition_logs(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['mealTypeId'] is None
    assert '未知の mealType' in capsys.readouterr().out


def test_fetch_nutrition_logs_sodium_grams_to_mg(fake_nutrition_pages):
    """sodium が grams -> mg（×1000）に変換されること"""
    fake_nutrition_pages([{'dataPoints': [
        _nutrition_log_point('meal-1', 2026, 8, 26, sodium_g=0.2249),
    ]}])

    rows = googlehealth_client.fetch_nutrition_logs(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['sodium'] == pytest.approx(224.9)


def test_fetch_nutrition_logs_amount_rounds_float_noise(fake_nutrition_pages):
    """serving.amount の float 誤差（1.2000000476837158）が丸められること"""
    fake_nutrition_pages([{'dataPoints': [
        _nutrition_log_point('meal-1', 2026, 8, 26, amount=1.2000000476837158),
    ]}])

    rows = googlehealth_client.fetch_nutrition_logs(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['amount'] == 1.2


def test_fetch_nutrition_water_is_always_empty_not_zero(fake_nutrition_pages):
    """water は取得元のデータ型が無いので常に空欄（None）で、0 になっていないこと

    回帰防止: 0 を入れると「水を摂っていない」という嘘になる
    """
    fake_nutrition_pages([{'dataPoints': [
        _nutrition_log_point('meal-1', 2026, 8, 26),
    ]}])

    rows = googlehealth_client.fetch_nutrition(None, dt.date(2026, 8, 26), dt.date(2026, 8, 27))

    assert rows[0]['water'] is None


def test_fetch_nutrition_skips_days_with_no_logs(fake_nutrition_pages):
    """食事ログが1件も無い日の行は作られないこと（Fitbit の全項目0行とは違う挙動）"""
    fake_nutrition_pages([{'dataPoints': [
        _nutrition_log_point('meal-1', 2026, 8, 26),
    ]}])

    rows = googlehealth_client.fetch_nutrition(None, dt.date(2026, 8, 20), dt.date(2026, 8, 27))

    assert [r['date'] for r in rows] == ['2026-08-26']


@pytest.fixture
def nutrition_logs_dir(tmp_path, monkeypatch):
    """ENDPOINTS['nutrition_logs']['output'] を tmp_path 配下に差し替える（caffeine_dir と同じ理由）"""
    out = tmp_path / 'nutrition_logs.csv'
    monkeypatch.setitem(ghf.ENDPOINTS['nutrition_logs'], 'output', out)
    return out


def test_nutrition_logs_merge_key_idempotent_across_two_saves(nutrition_logs_dir, monkeypatch):
    """logId を2回保存しても行数が増えないこと（19桁の整数、dtype=str 必須）"""
    row = {
        'logId': '37999834944', 'logDate': '2026-08-19', 'foodId': '781681941',
        'foodName': 'ご飯(一膳)', 'mealTypeId': 5, 'amount': 3.0, 'unitId': '304',
        'unitName': '食分', 'calories': 705, 'protein': 10.0, 'fat': 1.2,
        'carbs': 150.0, 'fiber': 0.3, 'sodium': 1.0,
    }
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'nutrition_logs', lambda creds, s, e: [row])

    ghf.fetch_endpoint(None, 'nutrition_logs', days=3)
    result = ghf.fetch_endpoint(None, 'nutrition_logs', days=3)

    assert result['records'] == 1
    saved = pd.read_csv(nutrition_logs_dir, dtype={'logId': str})
    assert len(saved) == 1
    assert saved.loc[0, 'logId'] == '37999834944'


def test_nutrition_allow_empty_does_not_error(data_dir, monkeypatch):
    """食事記録が無い期間は0件が正常。エラーにしないこと"""
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'nutrition', lambda creds, s, e: [])

    result = ghf.fetch_endpoint(None, 'nutrition', days=3)

    assert result['records'] == 0
    assert 'error' not in result


# =============================================================================
# temperature_core: 体温計で測って Google Health に手で記録する疎な指標
# =============================================================================

def test_temperature_core_allow_empty_does_not_error(data_dir, monkeypatch):
    """測り忘れた日は0件が正常。period_replace 経路でも allow_empty を尊重すること

    allow_empty を入れる前は、測らなかった日すべてで daily-routine.sh が
    非ゼロ終了し「Google Health の取得に失敗」と毎日出ていた。実際は
    測っていないだけで、故障ではない。
    """
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'temperature_core',
                        lambda creds, s, e: [])

    result = ghf.fetch_endpoint(None, 'temperature_core', days=3)

    assert result['records'] == 0
    assert 'error' not in result
    assert not (data_dir / 'temperature_core.csv').exists(), '0件なのにCSVを書いている'


def test_period_replace_without_allow_empty_still_errors(data_dir, monkeypatch):
    """period_replace でも allow_empty が無ければ0件はエラーのままであること"""
    monkeypatch.setitem(googlehealth_client.FETCHERS, 'sleep', lambda creds, s, e: ([], []))

    result = ghf.fetch_endpoint(None, 'sleep', days=3)

    assert result['records'] == 0
    assert result['error']
