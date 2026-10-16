"""
Google Calendar の写し（scripts/gcalendar.py / lib.gcalendar）のテスト（Issue #206）

守るもの: description を書かない・終日予定の排他端・cancelled だけが行を消す・
冪等・API 失敗で CSV を変えない・private 未マウントで API を叩く前に落ちる。
実 API は叩かない（フェイクの service を使う）。
"""

import argparse
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib import gcalendar
from lib.clients import gcalendar_client


def _load_script():
    path = BASE_DIR / 'scripts' / 'gcalendar.py'
    spec = importlib.util.spec_from_file_location('gcalendar_script', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['gcalendar_script'] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

TIME_MIN = '2026-10-10T00:00:00+09:00'
TIME_MAX = '2026-10-17T00:00:00+09:00'


def all_day_item(id_='ev1', start='2026-10-13', end='2026-10-16'):
    return {'id': id_, 'status': 'confirmed', 'summary': '宿泊', 'location': 'どこか',
            'description': '予約番号 ABC123', 'start': {'date': start}, 'end': {'date': end},
            'eventType': 'default', 'updated': '2026-10-01T00:00:00.000Z'}


def timed_item(id_='ev2'):
    return {'id': id_, 'status': 'confirmed', 'summary': '移動',
            'description': '照会番号 XYZ', 'attendees': [{'email': 'a@example.com'}],
            'start': {'dateTime': '2026-10-14T03:20:00Z'},
            'end': {'dateTime': '2026-10-14T05:00:00Z'},
            'eventType': 'default', 'updated': '2026-10-01T00:00:00.000Z'}


class FakeService:
    def __init__(self, items=None, error=None):
        self.items, self.error, self.calls = items or [], error, []

    def events(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self

    def execute(self):
        return {'items': self.items}


def run_fetch(service, csv_path):
    return script.fetch_to_csv(service, csv_path, TIME_MIN, TIME_MAX)


def test_csv_has_no_description_or_attendees(tmp_path):
    csv = tmp_path / 'events.csv'
    assert run_fetch(FakeService([all_day_item(), timed_item()]), csv) == 0
    df = pd.read_csv(csv, dtype=str)
    assert list(df.columns) == gcalendar.COLUMNS
    assert 'description' not in df.columns
    text = csv.read_text()
    assert 'ABC123' not in text and 'XYZ' not in text and 'example.com' not in text


def test_timed_event_is_stored_as_jst(tmp_path):
    csv = tmp_path / 'events.csv'
    run_fetch(FakeService([timed_item()]), csv)
    row = gcalendar.load(csv).iloc[0]
    assert row['start'] == '2026-10-14T12:20:00+09:00'
    assert row['all_day'] == 'False'


def test_all_day_end_is_exclusive():
    df, _ = gcalendar.to_rows([all_day_item()])
    row = df.iloc[0]
    covered = [d for d in range(12, 18) if gcalendar.covers(row, dt.date(2026, 10, d))]
    assert covered == [13, 14, 15]


def test_timed_event_crossing_midnight_covers_both_days():
    df, _ = gcalendar.to_rows([{
        'id': 'n', 'status': 'confirmed', 'summary': '夜',
        'start': {'dateTime': '2026-10-14T23:00:00+09:00'},
        'end': {'dateTime': '2026-10-15T01:00:00+09:00'},
    }])
    row = df.iloc[0]
    assert gcalendar.covers(row, dt.date(2026, 10, 14))
    assert gcalendar.covers(row, dt.date(2026, 10, 15))
    assert not gcalendar.covers(row, dt.date(2026, 10, 16))


def test_cancelled_removes_existing_row_and_missing_keeps_it(tmp_path):
    csv = tmp_path / 'events.csv'
    run_fetch(FakeService([all_day_item('keep'), all_day_item('gone')]), csv)

    # 応答に含まれなかった予定は残る
    run_fetch(FakeService([timed_item()]), csv)
    assert set(gcalendar.load(csv)['id']) == {'keep', 'gone', 'ev2'}

    # cancelled で返った予定だけ消える（cancelled は start 等を欠く）
    run_fetch(FakeService([{'id': 'gone', 'status': 'cancelled'}]), csv)
    assert set(gcalendar.load(csv)['id']) == {'keep', 'ev2'}


def test_fetch_twice_is_idempotent(tmp_path):
    csv = tmp_path / 'events.csv'
    items = [all_day_item(), timed_item()]
    run_fetch(FakeService(items), csv)
    first = csv.read_bytes()
    run_fetch(FakeService(items), csv)
    assert len(gcalendar.load(csv)) == 2
    assert csv.read_bytes() == first


def test_api_error_leaves_csv_untouched_and_returns_nonzero(tmp_path):
    csv = tmp_path / 'events.csv'
    run_fetch(FakeService([all_day_item()]), csv)
    before = csv.read_bytes()

    assert run_fetch(FakeService(error=RuntimeError('boom')), csv) != 0
    assert csv.read_bytes() == before


def test_api_error_does_not_create_csv(tmp_path):
    csv = tmp_path / 'sub' / 'events.csv'
    assert run_fetch(FakeService(error=RuntimeError('boom')), csv) != 0
    assert not csv.parent.exists()


def test_list_events_follows_pages():
    pages = [{'items': [{'id': 'a'}], 'nextPageToken': 't'}, {'items': [{'id': 'b'}]}]

    class Paged:
        def __init__(self):
            self.tokens = []

        def events(self):
            return self

        def list(self, **kwargs):
            self.tokens.append(kwargs['pageToken'])
            return self

        def execute(self):
            return pages[len(self.tokens) - 1]

    svc = Paged()
    items = gcalendar_client.list_events(svc, TIME_MIN, TIME_MAX)
    assert [i['id'] for i in items] == ['a', 'b']
    assert svc.tokens == [None, 't']


def test_cmd_fetch_fails_before_api_when_not_private(tmp_path, monkeypatch):
    """private に解決されない出力先なら、認可・API に到達する前に落ちる"""
    monkeypatch.setattr(script, 'CSV_FILE', tmp_path / 'data' / 'calendar' / 'events.csv')

    def fail(*args, **kwargs):
        pytest.fail('認可 / API に到達した')

    monkeypatch.setattr(gcalendar_client, 'create_service', fail)

    args = argparse.Namespace(days=2, since=None, login=False)
    with pytest.raises(FileNotFoundError):
        script.cmd_fetch(args)
    assert not (tmp_path / 'data').exists()
