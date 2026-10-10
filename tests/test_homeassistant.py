"""Home Assistant statistics・state 履歴の取得・保存（月分割・冪等性・故障検出）

実 API は叩かない。接続はフェイク、保存は tmp_path。
"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from lib import homeassistant_state_store as state_store
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


# --- state 履歴 ---------------------------------------------------------------
# フェイクの形は実 HA の history/history_during_period 応答（2026-10-10 に確認）に合わせる:
# {entity_id: [{'s': state, 'a': attributes, 'lu': epoch秒(float)}]}。先頭行は開始時点の state で
# lu が start に丸められている。存在しない entity はキーごと無い。

TRACKER = 'device_tracker.x'
GEO = ['latitude', 'longitude', 'gps_accuracy']
S0 = T0.timestamp()


def _st(state, epoch_s, **attrs):
    return {'s': state, 'a': attrs, 'lu': epoch_s}


def _sdf(result, start=T0, keys=None):
    return state_store.to_dataframe(result, keys or {}, start)


def _read_states(base, month):
    return pd.read_csv(base / 'data' / 'homeassistant' / 'states' / f'{month}.csv',
                       dtype=str, keep_default_na=False)


def test_state_resave_is_idempotent(tmp_path):
    df = _sdf({EID: [_st('on', S0 + 10), _st('off', S0 + 20)]})
    state_store.save(df, tmp_path)
    state_store.save(df, tmp_path)
    assert len(_read_states(tmp_path, '2026-10')) == 2


def test_state_overlap_replaces_rows(tmp_path):
    state_store.save(_sdf({EID: [_st('on', S0 + 10), _st('off', S0 + 20)]}), tmp_path)
    state_store.save(_sdf({EID: [_st('idle', S0 + 20), _st('on', S0 + 30)]}), tmp_path)
    assert list(_read_states(tmp_path, '2026-10')['state']) == ['on', 'idle', 'on']


def test_state_new_month_does_not_touch_old_month(tmp_path):
    state_store.save(_sdf({EID: [_st('on', S0 + 10)]}), tmp_path)
    old = tmp_path / 'data' / 'homeassistant' / 'states' / '2026-10.csv'
    before, mtime = old.read_bytes(), old.stat().st_mtime_ns
    nov = dt.datetime(2026, 11, 1, tzinfo=store.JST)
    state_store.save(_sdf({EID: [_st('off', nov.timestamp() + 5)]}, start=nov), tmp_path)
    assert old.read_bytes() == before
    assert old.stat().st_mtime_ns == mtime
    assert len(_read_states(tmp_path, '2026-11')) == 1


def test_state_month_split_is_jst():
    # 2026-10-31 15:00 UTC = 2026-11-01 00:00 JST
    t = dt.datetime(2026, 10, 31, 15, tzinfo=dt.timezone.utc).timestamp()
    df = _sdf({EID: [_st('on', t - 1), _st('off', t)]})
    assert list(df['time']) == ['2026-10-31 23:59:59.000000', '2026-11-01 00:00:00.000000']


def test_state_same_second_rows_both_kept(tmp_path):
    df = _sdf({EID: [_st('home', S0 + 100.123456), _st('home', S0 + 100.654321)]})
    state_store.save(df, tmp_path)
    out = _read_states(tmp_path, '2026-10')
    assert list(out['time']) == ['2026-10-05 00:01:40.123456', '2026-10-05 00:01:40.654321']


def test_state_unavailable_and_unknown_are_kept(tmp_path):
    state_store.save(_sdf({EID: [_st('unavailable', S0 + 1), _st('unknown', S0 + 2)]}), tmp_path)
    assert list(_read_states(tmp_path, '2026-10')['state']) == ['unavailable', 'unknown']


def test_state_free_text_survives_merge(tmp_path):
    # 既定の read_csv だと None / NA / 空欄が NaN に化けて書き戻される
    state_store.save(_sdf({EID: [_st('None', S0 + 1), _st('NA', S0 + 2), _st('', S0 + 3)]}),
                     tmp_path)
    state_store.save(_sdf({EID: [_st('x', S0 + 4)]}), tmp_path)
    assert list(_read_states(tmp_path, '2026-10')['state']) == ['None', 'NA', '', 'x']


def test_state_only_configured_attributes_are_saved():
    st = _st('home', S0 + 1, longitude=139.5, latitude=35.6, gps_accuracy=100.0,
             speed=0, friendly_name='x')
    df = _sdf({TRACKER: [st], EID: [_st('on', S0 + 2, friendly_name='y')]},
              keys={TRACKER: GEO})
    attrs = dict(zip(df['entity_id'], df['attributes']))
    # キー順は yaml の指定順で固定
    assert attrs[TRACKER] == '{"latitude": 35.6, "longitude": 139.5, "gps_accuracy": 100.0}'
    assert attrs[EID] == ''


def test_state_start_time_row_is_not_saved():
    # 先頭行の lu は start に丸められた開始時点の state。実際の更新ではない
    df = _sdf({EID: [_st('on', S0), _st('off', S0 + 10), _st('on', S0 + 20)]})
    assert list(df['state']) == ['off', 'on']


def test_state_non_first_row_at_start_is_kept():
    df = _sdf({EID: [_st('on', S0 - 5), _st('off', S0)]})
    assert list(df['state']) == ['on', 'off']


class FakeHistory:
    def __init__(self, result_fn):
        self.result_fn = result_fn
        self.calls = []

    def history_during_period(self, start, end, ids, attributes=False):
        assert attributes
        self.calls.append((start, end))
        return self.result_fn(start, end, ids)


def test_run_states_missing_entity_returns_nonzero(tmp_path):
    script = _load_script()
    fake = FakeHistory(lambda s, e, ids: {
        'sensor.a': [_st('on', s.timestamp()), _st('off', s.timestamp() + 60)]})
    code = script.run_states(fake, tmp_path, {'sensor.a': [], 'sensor.b': []}, T0, T1)
    assert code == 1
    # 取れた分は保存されている
    assert list(_read_states(tmp_path, '2026-10')['state']) == ['off']


def test_run_states_start_state_only_is_ok_and_writes_nothing(tmp_path):
    script = _load_script()
    fake = FakeHistory(lambda s, e, ids: {i: [_st('home', s.timestamp())] for i in ids})
    assert script.run_states(fake, tmp_path, {TRACKER: GEO}, T0, T1) == 0
    assert not (tmp_path / 'data' / 'homeassistant' / 'states').exists()


def test_run_states_different_starts_do_not_accumulate(tmp_path):
    # 日次実行で窓の開始がずれても、開始時点の行が偽の更新として溜まらない
    script = _load_script()
    real = S0 + 600

    def result(s, e, ids):
        rows = [_st('home', s.timestamp())]
        if s.timestamp() < real < e.timestamp():
            rows.append(_st('not_home', real))
        return {i: rows for i in ids}

    script.run_states(FakeHistory(result), tmp_path, {TRACKER: []}, T0, T1)
    script.run_states(FakeHistory(result), tmp_path, {TRACKER: []},
                      T0 + dt.timedelta(minutes=5), T1 + dt.timedelta(minutes=5))
    assert list(_read_states(tmp_path, '2026-10')['state']) == ['not_home']


def test_run_states_chunks_long_window(tmp_path):
    script = _load_script()
    fake = FakeHistory(lambda s, e, ids: {i: [_st('on', s.timestamp())] for i in ids})
    script.run_states(fake, tmp_path, {EID: []}, T0, T0 + dt.timedelta(days=10))
    assert [(e - s).days for s, e in fake.calls] == [7, 3]


def test_yaml_entity_line_is_enough():
    script = _load_script()
    assert script.parse_entities(['sensor.a', {'entity_id': TRACKER, 'attributes': GEO}]) == {
        'sensor.a': [], TRACKER: GEO}
    entities = script.parse_entities(script.load_config()['entities'])
    assert entities['device_tracker.xiaomi'] == GEO


def test_client_history_request_and_tz_guard():
    ws = FakeWS([{'type': 'auth_required'}, {'type': 'auth_ok'},
                 {'id': 1, 'type': 'result', 'success': True, 'result': {EID: []}}])
    c = HomeAssistantClient('http://h:8123', 'tok', connect=lambda url: ws)
    assert c.history_during_period(T0, T1, [EID], attributes=True) == {EID: []}
    req = ws.sent[1]
    assert req['type'] == 'history/history_during_period'
    assert req['start_time'].endswith('+09:00')
    assert req['include_start_time_state'] is True
    assert req['significant_changes_only'] is False
    assert req['no_attributes'] is False
    assert req['minimal_response'] is False
    with pytest.raises(ValueError):
        c.history_during_period(T0.replace(tzinfo=None), T1, [EID], attributes=True)
