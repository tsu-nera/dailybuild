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
