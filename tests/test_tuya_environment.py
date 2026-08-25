"""Tuya 室内環境クライアントの変換ロジック（Issue #42）

実機を叩かずに、ログJSON → CSV行 への変換と境界計算だけを検証する。
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

from lib.clients.tuya_client import (
    RATE_LIMIT_CODE,
    TuyaEnvironmentClient,
    TuyaError,
    TuyaRateLimitError,
    _check,
    load_credentials,
)

BASE_DIR = Path(__file__).parent.parent


def _load_script():
    """scripts/ 配下はパッケージではないのでファイルから直接ロードする"""
    path = BASE_DIR / 'scripts' / 'fetch_environment.py'
    spec = importlib.util.spec_from_file_location('fetch_environment', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['fetch_environment'] = module
    spec.loader.exec_module(module)
    return module


class _FakeClient(TuyaEnvironmentClient):
    """__init__ を飛ばして変換ロジックだけを試す"""

    def __init__(self, logs, scales=None):
        self._logs = logs
        self._scales = scales or {'co2_value': 0, 'temp_current': 0, 'humidity_value': 0}
        self.device_id = 'dummy'

    def fetch_window(self, start, width_sec=60, codes=None):
        return self._logs


def _log(code, value, ms=0):
    return {'code': code, 'value': value, 'event_time': 1_700_000_000_000 + ms}


def test_window_is_averaged_into_one_row():
    client = _FakeClient([
        _log('co2_value', '1000'), _log('co2_value', '1010'),
        _log('temp_current', '26'), _log('humidity_value', '60'),
        _log('humidity_value', '62'),
    ])
    row = client.sample_window(dt.datetime(2026, 8, 25, 3, 0))
    assert row['datetime'] == dt.datetime(2026, 8, 25, 3, 0)
    assert row['co2_ppm'] == 1005.0
    assert row['temperature'] == 26.0
    assert row['humidity'] == 61.0


def test_empty_window_is_missing_not_zero():
    """欠測は None。0 で埋めると測っていない時間帯を「CO2 0ppm」と偽ることになる"""
    assert _FakeClient([]).sample_window(dt.datetime(2026, 8, 25, 3, 0)) is None


def test_scale_is_applied():
    """spec の scale が 1 なら ×10 で返る値を割り戻す"""
    client = _FakeClient([_log('temp_current', '265')],
                         scales={'co2_value': 0, 'temp_current': 1, 'humidity_value': 0})
    row = client.sample_window(dt.datetime(2026, 8, 25, 3, 0))
    assert row['temperature'] == 26.5


def test_unknown_codes_are_ignored():
    client = _FakeClient([_log('co2_value', '900'), _log('battery_percentage', '80')])
    row = client.sample_window(dt.datetime(2026, 8, 25, 3, 0))
    assert row['co2_ppm'] == 900.0
    assert 'battery_percentage' not in row


def test_non_numeric_values_do_not_crash():
    client = _FakeClient([_log('co2_value', 'N/A'), _log('co2_value', '900')])
    row = client.sample_window(dt.datetime(2026, 8, 25, 3, 0))
    assert row['co2_ppm'] == 900.0


def test_partial_window_leaves_column_empty():
    """窓にCO2しか無ければ温湿度は None。前後から埋めない"""
    row = _FakeClient([_log('co2_value', '900')]).sample_window(dt.datetime(2026, 8, 25, 3, 0))
    assert row['co2_ppm'] == 900.0
    assert row['temperature'] is None
    assert row['humidity'] is None


def test_rate_limit_is_a_distinct_exception():
    """レート制限はリトライ可能なので他のエラーと区別する"""
    with pytest.raises(TuyaRateLimitError):
        _check({'success': False, 'code': RATE_LIMIT_CODE, 'msg': 'too frequent'})
    with pytest.raises(TuyaError):
        _check({'success': False, 'code': 1109, 'msg': 'permission denied'})


def test_api_failure_is_not_silently_empty():
    """success=False を素通しすると「0件取得」として欠測を捏造する"""
    with pytest.raises(TuyaError):
        _check({'success': False, 'code': 28841101, 'msg': 'not subscribed'})


def test_missing_credentials_explains_setup(tmp_path):
    with pytest.raises(TuyaError, match='iot.tuya.com'):
        load_credentials(tmp_path / 'nope.json')


def test_incomplete_credentials_are_rejected(tmp_path):
    path = tmp_path / 'tuya_creds.json'
    path.write_text('{"api_region": "us", "api_key": "k"}')
    with pytest.raises(TuyaError, match='api_secret'):
        load_credentials(path)


def test_boundaries_are_aligned_to_the_interval():
    mod = _load_script()
    points = mod.boundaries(dt.datetime(2026, 8, 25, 3, 2),
                            dt.datetime(2026, 8, 25, 3, 21), 5)
    assert points == [dt.datetime(2026, 8, 25, 3, 5),
                      dt.datetime(2026, 8, 25, 3, 10),
                      dt.datetime(2026, 8, 25, 3, 15),
                      dt.datetime(2026, 8, 25, 3, 20)]
