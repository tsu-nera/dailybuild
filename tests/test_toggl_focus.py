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


# --- 書き込み系（実測した API の形。ネットワークは叩かない） ---

WS = focus.Workspace('tok', 'org', '42')


def test_fetch_projects_pages_until_short_page(monkeypatch):
    calls = []
    pages = [[{'id': i, 'name': f'p{i}'} for i in range(focus.PAGE_SIZE)],
             [{'id': 1000, 'name': 'last'}]]

    def fake_get(api_token, path, params):
        calls.append((path, dict(params)))
        return FakeResponse(pages[params['page'] - 1])

    monkeypatch.setattr(focus, '_get', fake_get)

    projects = focus.fetch_projects(WS)

    assert len(projects) == focus.PAGE_SIZE + 1 and projects[1000] == 'last'
    assert [c[0] for c in calls] == ['/organizations/org/workspaces/42/projects'] * 2
    assert all(c[1]['per_page'] == 100 for c in calls)


def test_create_start_stop_use_measured_endpoints(monkeypatch):
    posted = []

    def fake_post(api_token, path, body):
        posted.append((path, body))
        return FakeResponse({'id': 7})

    monkeypatch.setattr(focus, '_post', fake_post)

    focus.create_time_entry(WS, {'type': 'activity'})
    focus.start_tracking(WS, {'type': 'activity'})
    jst = dt.timezone(dt.timedelta(hours=9))
    focus.stop_tracking(WS, dt.datetime(2026, 11, 2, 19, 0, 5, 999, tzinfo=jst))

    base = '/organizations/org/workspaces/42'
    assert [p for p, _ in posted] == [f'{base}/time-entries', f'{base}/tracking/start',
                                       f'{base}/tracking/stop']
    # 終了時刻は UTC の RFC3339、秒未満なし
    assert posted[2][1] == {'end': '2026-11-02T10:00:05Z'}


def test_fetch_current_returns_none_on_204(monkeypatch):
    class NoContent:
        status_code = 204

        def json(self):
            raise ValueError('no body')

    monkeypatch.setattr(focus, '_get', lambda *a, **k: NoContent())
    assert focus.fetch_current(WS) is None


def test_fetch_current_returns_entry(monkeypatch):
    class Ok:
        status_code = 200

        def json(self):
            return {'id': 5}

    monkeypatch.setattr(focus, '_get', lambda *a, **k: Ok())
    assert focus.fetch_current(WS) == {'id': 5}


def test_tags_are_collected_and_never_shrink(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, 'TAGS_FILE', tmp_path / 'focus_tags.json')
    found = focus.collect_tags([_entry(1, '2026-10-28T00:00:00Z'),
                                _entry(2, '2026-10-28T01:00:00Z', tags=[])])
    assert found == {'deep': 1, 'book': 2}

    focus.save_tags(found)
    # 取得窓にタグが出なかった回でも既存の対応は失わない
    focus.save_tags({})
    focus.save_tags({'auto': 908186})

    assert focus.load_tags() == {'deep': 1, 'book': 2, 'auto': 908186}


def test_load_tags_broken_file_is_empty(tmp_path, monkeypatch):
    path = tmp_path / 'focus_tags.json'
    path.write_text('{ broken', encoding='utf-8')
    monkeypatch.setattr(focus, 'TAGS_FILE', path)
    assert focus.load_tags() == {}


def test_save_merged_without_window_only_appends(tmp_path):
    csv = tmp_path / 'focus_entries.csv'
    focus.save_merged(focus.build_dataframe([_entry(1, '2026-10-28T00:00:00Z')], workspace_id=42),
                      (dt.date(2026, 10, 28), dt.date(2026, 10, 28)), csv_path=csv)

    focus.save_merged(focus.build_dataframe([_entry(2, '2026-10-28T01:00:00Z')], workspace_id=42),
                      csv_path=csv)

    assert sorted(pd.read_csv(csv)['id'].tolist()) == [1, 2]
