"""Habitica の cron 記録のテスト

沈黙故障の再発防止だけを対象にする。cron を走らせない日は Daily の未完了が
history に残らず、走らせた日と区別できないと達成率の分母が捏造される。

- 同日再実行で行が重複しない（冪等性）
- dayStart より前の実行が前日として記録される（分母のキーがずれない）
- 429 は Retry-After に従って再試行し、失敗を握り潰さない
"""

import importlib.util
import sys
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.clients.habitica_client import HabiticaClient, HabiticaError


def _load_script():
    path = BASE_DIR / 'scripts' / 'habitica.py'
    spec = importlib.util.spec_from_file_location('habitica_script', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['habitica_script'] = module
    spec.loader.exec_module(module)
    return module


habitica = _load_script()


@pytest.fixture
def csv_path(tmp_path, monkeypatch):
    path = tmp_path / 'cron_log.csv'
    monkeypatch.setattr(habitica, 'CRON_LOG', path)
    return path


class FakeClient:
    """API を叩かずに run_cron() のロジックだけを回す"""

    def __init__(self, last_cron, needs_cron, day_start=5):
        self.last_cron = last_cron
        self.needs_cron = needs_cron
        self.day_start = day_start
        self.cron_calls = 0

    def get_user(self):
        return {
            'lastCron': self.last_cron,
            'needsCron': self.needs_cron,
            'preferences': {'dayStart': self.day_start},
            'stats': {'hp': 23.0, 'lvl': 14, 'exp': 19, 'gp': 5.0},
        }

    def run_cron(self):
        self.cron_calls += 1
        self.last_cron = '2026-08-30T05:00:00.000Z'
        return {'user': {'lastCron': self.last_cron,
                         'stats': {'hp': 21.0, 'lvl': 14, 'exp': 19, 'gp': 5.0}}}


def test_同日に2回走らせても行が重複しない(csv_path):
    client = FakeClient('2026-08-29T06:48:11.433Z', needs_cron=False)
    habitica.run_cron(client)
    habitica.run_cron(client)

    df = pd.read_csv(csv_path)
    assert len(df) == 1
    assert df['date'].nunique() == 1


def test_cronが必要なときだけPOSTする(csv_path):
    client = FakeClient('2026-08-28T06:00:00.000Z', needs_cron=True)
    row = habitica.run_cron(client)
    assert client.cron_calls == 1
    assert row['cron_posted'] is True
    assert row['last_cron_final'] == '2026-08-30T05:00:00.000Z'

    client2 = FakeClient('2026-08-29T06:48:11.433Z', needs_cron=False)
    row2 = habitica.run_cron(client2)
    assert client2.cron_calls == 0
    assert row2['cron_posted'] is False


def test_前回のlastCronを引き継いで記録する(csv_path):
    """GET だけで cron が走ったかを後から判別できるようにする"""
    first = FakeClient('2026-08-28T06:00:00.000Z', needs_cron=False)
    habitica.run_cron(first)

    df = pd.read_csv(csv_path)
    df.loc[0, 'date'] = '2026-08-28'  # 前日の記録に見せる
    df.to_csv(csv_path, index=False)

    second = FakeClient('2026-08-29T06:48:11.433Z', needs_cron=False)
    row = habitica.run_cron(second)
    assert row['last_cron_prev'] == '2026-08-28T06:00:00.000Z'
    assert row['last_cron_get'] == '2026-08-29T06:48:11.433Z'


@pytest.mark.parametrize('hour,expected', [
    (4, '2026-08-28'),   # dayStart(5時)より前は前日
    (5, '2026-08-29'),
    (23, '2026-08-29'),
])
def test_dayStartより前の実行は前日として記録する(hour, expected):
    now = dt.datetime(2026, 8, 29, hour, 30)
    assert habitica.habitica_date(now, 5).isoformat() == expected


def test_429はRetryAfterに従って再試行する(monkeypatch):
    client = HabiticaClient('u', 'k')
    calls = []
    waits = []

    def fake_raw(method, path, body):
        calls.append(path)
        if len(calls) == 1:
            err = HabiticaError('429')
            err.retry_after = 0.5
            raise err
        return {'ok': True}

    monkeypatch.setattr(client, '_raw_request', fake_raw)
    monkeypatch.setattr('lib.clients.habitica_client.time.sleep', waits.append)

    assert client.request('GET', '/user') == {'ok': True}
    assert len(calls) == 2
    assert waits == [0.5]


def test_429が2回続いたら握り潰さず落ちる(monkeypatch):
    client = HabiticaClient('u', 'k')

    def always_429(method, path, body):
        err = HabiticaError('429')
        err.retry_after = 0.1
        raise err

    monkeypatch.setattr(client, '_raw_request', always_429)
    monkeypatch.setattr('lib.clients.habitica_client.time.sleep', lambda s: None)

    with pytest.raises(HabiticaError):
        client.request('GET', '/user')


def test_待ち時間が長すぎるときは待たずに落ちる(monkeypatch):
    client = HabiticaClient('u', 'k')

    def slow_429(method, path, body):
        err = HabiticaError('429')
        err.retry_after = 3600.0
        raise err

    monkeypatch.setattr(client, '_raw_request', slow_429)
    with pytest.raises(HabiticaError, match='長すぎます'):
        client.request('GET', '/user')


def test_認証情報が無ければ落ちる(tmp_path):
    with pytest.raises(HabiticaError, match='認証情報がありません'):
        HabiticaClient.from_config(tmp_path / 'nope.json')


def test_認証情報が欠けていれば落ちる(tmp_path):
    path = tmp_path / 'creds.json'
    path.write_text('{"user_id": "u"}')
    with pytest.raises(HabiticaError, match='api_token'):
        HabiticaClient.from_config(path)
