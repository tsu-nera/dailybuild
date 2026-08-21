"""googlehealth_fetcher のテスト（Issue #49）

ネットワークを使わない。FETCHERS を差し替えて保存経路のみ検証する。
"""

import datetime as dt

import pandas as pd
import pytest

from lib import googlehealth_fetcher as ghf
from lib.clients import googlehealth_api


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
        ghf.fetch_endpoint(None, 'sleep', days=3)


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


def test_num_coerces_string_values():
    """Google が数値を文字列で返すケースを float に正規化すること"""
    assert googlehealth_api._num('36.5') == 36.5
    assert googlehealth_api._num(36.5) == 36.5
    assert googlehealth_api._num(None) is None
    assert googlehealth_api._num('') is None
