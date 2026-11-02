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
