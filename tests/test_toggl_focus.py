"""
Toggl 2.0（Focus API）取得（Issue #236）のテスト

_get を monkeypatch したフェイク応答で、ページ送り・リクエストのパラメータ・
CSV 用の変換・focus_entries.csv への冪等なマージを確認する（ネットワーク不要）。
"""

import datetime as dt

import pandas as pd

from lib.toggl import focus


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _entry(entry_id, start, duration=1800, **extra):
    entry = {
        'id': entry_id,
        'start': start,
        'duration': duration,
        'description': f'entry {entry_id}',
        'project_id': 10,
        'project': {'id': 10, 'name': '読書'},
        'tags': [{'id': 1, 'name': 'deep'}, {'id': 2, 'name': 'book'}],
        'type': 'activity',
    }
    entry.update(extra)
    return entry


def _fake_pages(monkeypatch, pages):
    calls = []

    def fake_get(api_token, path, params):
        calls.append((path, dict(params)))
        data = pages[params['page'] - 1] if params['page'] <= len(pages) else []
        return FakeResponse({'page': params['page'], 'per_page': params['per_page'], 'data': data})

    monkeypatch.setattr(focus, '_get', fake_get)
    return calls


def test_fetch_concatenates_all_pages(monkeypatch):
    page1 = [_entry(i, '2026-10-28T00:00:00Z') for i in range(focus.PAGE_SIZE)]
    page2 = [_entry(1000, '2026-10-28T01:00:00Z')]
    calls = _fake_pages(monkeypatch, [page1, page2])

    entries = focus.fetch_time_entries('tok', 'org', '42', dt.date(2026, 10, 28), dt.date(2026, 10, 28))

    assert len(entries) == focus.PAGE_SIZE + 1
    assert [params['page'] for _, params in calls] == [1, 2]


def test_fetch_sends_taskless_and_utc_range(monkeypatch):
    calls = _fake_pages(monkeypatch, [[]])

    focus.fetch_time_entries('tok', 'org', '42', dt.date(2026, 10, 27), dt.date(2026, 10, 28))

    path, params = calls[0]
    assert path == '/organizations/org/workspaces/42/time-entries'
    assert params['include_taskless'] == 'true'
    # JST 2026-10-27 00:00 〜 2026-10-28 23:59:59 を UTC で
    assert params['date_from'] == '2026-10-26T15:00:00Z'
    assert params['date_to'] == '2026-10-28T14:59:59Z'


def test_build_dataframe_computes_stop_and_fields():
    df = focus.build_dataframe([_entry(1, '2026-10-28T00:30:00Z', duration=5400)], workspace_id=42)

    row = df.iloc[0]
    assert row['start'] == '2026-10-28 09:30:00'
    assert row['stop'] == '2026-10-28 11:00:00'
    assert row['duration_sec'] == 5400
    assert row['description'] == 'entry 1'
    assert row['project_name'] == '読書'
    assert row['tags'] == 'deep,book'
    assert row['workspace_id'] == 42
    assert row['type'] == 'activity'


def test_build_dataframe_excludes_running_entries():
    df = focus.build_dataframe([
        _entry(1, '2026-10-28T00:00:00Z', duration=None),
        _entry(2, '2026-10-28T01:00:00Z', duration=-1),
        _entry(3, '2026-10-28T02:00:00Z', duration=60),
    ])

    assert df['id'].tolist() == [3]


def test_save_merged_is_idempotent(tmp_path):
    csv = tmp_path / 'focus_entries.csv'
    window = (dt.date(2026, 10, 28), dt.date(2026, 10, 28))
    entries = [
        _entry(1, '2026-10-28T00:00:00Z'),
        _entry(2, '2026-10-28T01:00:00Z', project_id=None, project=None),
    ]

    focus.save_merged(focus.build_dataframe(entries, workspace_id=42), window, csv_path=csv)
    first = pd.read_csv(csv, dtype=str)
    focus.save_merged(focus.build_dataframe(entries, workspace_id=42), window, csv_path=csv)
    second = pd.read_csv(csv, dtype=str)

    assert len(second) == 2
    pd.testing.assert_frame_equal(first, second)
    # project_id の欠損で float 化して 10.0 にならないこと
    assert second['project_id'].tolist()[0] == '10'


def test_save_merged_replaces_only_inside_window(tmp_path):
    csv = tmp_path / 'focus_entries.csv'
    focus.save_merged(focus.build_dataframe([
        _entry(1, '2026-10-20T00:00:00Z'),   # 窓外（JST 10-20）
        _entry(2, '2026-10-28T00:00:00Z'),   # 窓内。次の取得で消える
        _entry(3, '2026-10-28T01:00:00Z'),
    ], workspace_id=42), (dt.date(2026, 10, 20), dt.date(2026, 10, 28)), csv_path=csv)

    df = focus.save_merged(focus.build_dataframe([
        _entry(3, '2026-10-28T01:00:00Z'),
    ], workspace_id=42), (dt.date(2026, 10, 27), dt.date(2026, 10, 28)), csv_path=csv)

    assert sorted(df['id'].tolist()) == [1, 3]
    assert sorted(pd.read_csv(csv)['id'].tolist()) == [1, 3]
