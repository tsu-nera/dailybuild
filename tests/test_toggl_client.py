"""
Toggl client の取得窓（Issue #127）のテスト

fetch_time_entries に date のまま start_date/end_date を渡すと Toggl は
UTC として解釈し、JST では取得窓が意図から9時間ずれる（例: JST 00:00〜09:00の
エントリを取り逃す）。ここでは _get を monkeypatch して、実際に投げる params が
tz オフセット付きの RFC3339 になっていることだけを見る（ネットワーク不要）。
"""

import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.toggl import client as toggl_client

JST = ZoneInfo('Asia/Tokyo')


class FakeResponse:
    def json(self):
        return []


def test_fetch_time_entries_sends_tz_aware_rfc3339(monkeypatch):
    captured = {}

    def fake_get(api_token, path, params):
        captured['params'] = params
        return FakeResponse()

    monkeypatch.setattr(toggl_client, '_get', fake_get)

    toggl_client.fetch_time_entries(
        'token', dt.date(2026, 9, 4), dt.date(2026, 9, 6), JST,
    )

    start_date = captured['params']['start_date']
    end_date = captured['params']['end_date']

    # tz オフセットが付いていること（date のまま渡すと UTC 扱いになるバグの回帰）
    assert start_date.endswith('+09:00')
    assert end_date.endswith('+09:00')

    # end は排他的なので end + 1日 の 00:00 になっていること
    assert end_date == '2026-09-07T00:00:00+09:00'


def test_jst_0030_start_is_inside_the_window(monkeypatch):
    """JST 00:30 開始のエントリが窓の内側に入ることの回帰テスト

    UTC 解釈だと start_date=2026-09-04（UTC 00:00）は JST 09:00 相当になり、
    JST 00:30 のエントリは窓の外に落ちる。tz-aware にすると
    start_date は JST 2026-09-04T00:00:00+09:00 になるので、
    00:30 のエントリは窓の内側に入る。
    """
    captured = {}

    def fake_get(api_token, path, params):
        captured['params'] = params
        return FakeResponse()

    monkeypatch.setattr(toggl_client, '_get', fake_get)

    toggl_client.fetch_time_entries(
        'token', dt.date(2026, 9, 4), dt.date(2026, 9, 4), JST,
    )

    start_date = captured['params']['start_date']
    assert start_date == '2026-09-04T00:00:00+09:00'

    entry_start = dt.datetime.fromisoformat('2026-09-04T00:30:00+09:00')
    window_start = dt.datetime.fromisoformat(start_date)
    assert window_start <= entry_start


def _fake_response(status_code, body):
    class Resp:
        headers = {}

        def __init__(self):
            self.status_code = status_code

        def json(self):
            return body

        def raise_for_status(self):
            pass

    return Resp()


def test_fetch_time_entry_returns_none_on_404(monkeypatch):
    def fake_request(method, url, **kwargs):
        return _fake_response(404, None)

    monkeypatch.setattr(toggl_client.requests, 'request', fake_request)

    assert toggl_client.fetch_time_entry('token', '123') is None


def test_fetch_time_entry_returns_none_when_server_deleted_at(monkeypatch):
    def fake_request(method, url, **kwargs):
        return _fake_response(200, {'id': 123, 'server_deleted_at': '2026-09-01T00:00:00Z'})

    monkeypatch.setattr(toggl_client.requests, 'request', fake_request)

    assert toggl_client.fetch_time_entry('token', '123') is None


def test_fetch_time_entry_returns_dict_when_present(monkeypatch):
    def fake_request(method, url, **kwargs):
        return _fake_response(200, {'id': 123})

    monkeypatch.setattr(toggl_client.requests, 'request', fake_request)

    assert toggl_client.fetch_time_entry('token', '123') == {'id': 123}
