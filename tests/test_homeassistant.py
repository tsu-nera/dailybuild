"""Home Assistant statistics の取得・保存（月分割・冪等性・故障検出）

実 API は叩かない。接続はフェイク、保存は tmp_path。
"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from lib import homeassistant_store as store
from lib.clients.homeassistant_client import (
    DEFAULT_URL,
    HomeAssistantClient,
    HomeAssistantError,
    load_settings,
)

BASE_DIR = Path(__file__).parent.parent
EID = 'sensor.t'


def _load_script():
    path = BASE_DIR / 'scripts' / 'fetch_homeassistant.py'
    spec = importlib.util.spec_from_file_location('fetch_homeassistant', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['fetch_homeassistant'] = module
    spec.loader.exec_module(module)
    return module


def _ms(iso_utc: str) -> int:
    return int(dt.datetime.fromisoformat(iso_utc).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def _df(points, eid=EID):
    return store.to_dataframe({eid: [{'start': _ms(t), 'mean': m, 'min': m, 'max': m}
                                     for t, m in points]})


def _read(base, month):
    return pd.read_csv(base / 'data' / 'homeassistant' / 'statistics_5min' / f'{month}.csv')


class FakeWS:
    def __init__(self, replies):
        self.replies = [json.dumps(r) for r in replies]
        self.sent = []

    def recv(self):
        return self.replies.pop(0)

    def send(self, data):
        self.sent.append(json.loads(data))

    def close(self):
        pass


def _client(replies):
    return HomeAssistantClient('http://localhost:8123', 'tok', connect=lambda url: FakeWS(replies))


T0 = dt.datetime(2026, 10, 5, tzinfo=store.JST)
T1 = T0 + dt.timedelta(hours=1)


def test_epoch_ms_to_jst_month_boundary(tmp_path):
    # 2026-10-31 15:00 UTC = 2026-11-01 00:00 JST
    df = _df([('2026-10-31T14:55:00', 1.0), ('2026-10-31T15:00:00', 2.0)])
    assert list(df['start']) == ['2026-10-31 23:55:00', '2026-11-01 00:00:00']
    store.save(df, tmp_path)
    assert list(_read(tmp_path, '2026-10')['mean']) == [1.0]
    assert list(_read(tmp_path, '2026-11')['mean']) == [2.0]


def test_resave_is_idempotent(tmp_path):
    df = _df([('2026-10-05T00:00:00', 1.0), ('2026-10-05T00:05:00', 2.0)])
    store.save(df, tmp_path)
    store.save(df, tmp_path)
    assert len(_read(tmp_path, '2026-10')) == 2


def test_overlap_replaces_values(tmp_path):
    store.save(_df([('2026-10-05T00:00:00', 1.0), ('2026-10-05T00:05:00', 2.0)]), tmp_path)
    store.save(_df([('2026-10-05T00:05:00', 9.0), ('2026-10-05T00:10:00', 3.0)]), tmp_path)
    out = _read(tmp_path, '2026-10')
    assert list(out['mean']) == [1.0, 9.0, 3.0]


def test_new_month_does_not_touch_old_month(tmp_path):
    store.save(_df([('2026-10-05T00:00:00', 1.0)]), tmp_path)
    old = tmp_path / 'data' / 'homeassistant' / 'statistics_5min' / '2026-10.csv'
    before = old.read_bytes()
    mtime = old.stat().st_mtime_ns
    store.save(_df([('2026-11-05T00:00:00', 2.0)]), tmp_path)
    assert old.read_bytes() == before
    assert old.stat().st_mtime_ns == mtime


def test_empty_entity_returns_nonzero(tmp_path):
    script = _load_script()

    class Fake:
        def statistics_during_period(self, start, end, ids):
            return {'sensor.a': [{'start': _ms('2026-10-04T15:00:00'), 'mean': 1, 'min': 1, 'max': 1}],
                    'sensor.b': []}

    code = script.run(Fake(), tmp_path, ['sensor.a', 'sensor.b'], T0, T1)
    assert code == 1
    # 取れた分は保存されている
    assert len(_read(tmp_path, '2026-10')) == 1


def test_all_entities_present_returns_zero(tmp_path):
    script = _load_script()

    class Fake:
        def statistics_during_period(self, start, end, ids):
            return {i: [{'start': _ms('2026-10-04T15:00:00'), 'mean': 1, 'min': 1, 'max': 1}]
                    for i in ids}

    assert script.run(Fake(), tmp_path, ['sensor.a', 'sensor.b'], T0, T1) == 0


def test_client_raises_on_auth_invalid():
    c = _client([{'type': 'auth_required'}, {'type': 'auth_invalid', 'message': 'bad'}])
    with pytest.raises(HomeAssistantError):
        c.statistics_during_period(T0, T1, [EID])


def test_client_raises_on_failure_result():
    c = _client([{'type': 'auth_required'}, {'type': 'auth_ok'},
                 {'id': 1, 'type': 'result', 'success': False, 'error': {'code': 'x'}}])
    with pytest.raises(HomeAssistantError):
        c.statistics_during_period(T0, T1, [EID])


def test_client_returns_result_and_sends_tz_aware_times():
    ws = FakeWS([{'type': 'auth_required'}, {'type': 'auth_ok'},
                 {'id': 1, 'type': 'result', 'success': True, 'result': {EID: []}}])
    c = HomeAssistantClient('http://h:8123', 'tok', connect=lambda url: ws)
    assert c.statistics_during_period(T0, T1, [EID]) == {EID: []}
    assert ws.sent[1]['start_time'].endswith('+09:00')


def test_settings_defaults_url_and_wraps_missing_token(tmp_path):
    p = tmp_path / '.env'
    p.write_text('HA_TOKEN=abc\n')
    assert load_settings(env_file=p, environ={}) == (DEFAULT_URL, 'abc')
    with pytest.raises(HomeAssistantError):
        load_settings(env_file=tmp_path / 'none', environ={})
