"""timer.py（start/stop の名前解決とペイロード）のテスト"""

import datetime as dt

import pytest

from lib.toggl import timer


PROJECTS = {1: '読書', 2: '読書メモ', 3: 'Deep Work', 4: '睡眠'}


def test_resolve_exact_match_wins_over_partial():
    # '読書' は '読書メモ' の部分一致でもあるが、完全一致を優先して曖昧にしない
    assert timer.resolve_project('読書', PROJECTS) == (1, '読書')


def test_resolve_case_insensitive():
    assert timer.resolve_project('deep work', PROJECTS) == (3, 'Deep Work')


def test_resolve_unique_partial():
    assert timer.resolve_project('メモ', PROJECTS) == (2, '読書メモ')


def test_resolve_ambiguous_partial_raises_with_candidates():
    with pytest.raises(timer.ProjectResolutionError) as e:
        timer.resolve_project('読', PROJECTS)
    assert '読書' in str(e.value) and '読書メモ' in str(e.value)


def test_resolve_unknown_raises():
    with pytest.raises(timer.ProjectResolutionError):
        timer.resolve_project('存在しない', PROJECTS)


def test_build_start_payload_is_running_entry():
    start = dt.datetime(2026, 8, 25, 10, 0, tzinfo=dt.timezone.utc)
    payload = timer.build_start_payload(9, 1, '読書', ('deep',), start)
    # duration が負値のときだけ計測中になる。stop を含めてはいけない
    assert payload['duration'] == -1
    assert 'stop' not in payload
    assert payload['project_id'] == 1
    assert payload['workspace_id'] == 9
    assert payload['tags'] == ['deep']


def test_build_start_payload_without_project():
    start = dt.datetime(2026, 8, 25, 10, 0, tzinfo=dt.timezone.utc)
    payload = timer.build_start_payload(9, None, 'メモ', (), start)
    assert 'project_id' not in payload


def test_project_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(timer, 'PROJECTS_CACHE_FILE', tmp_path / 'projects.json')
    timer.save_project_cache(9, PROJECTS)
    # JSON のキーは文字列になるので、読み戻しで int に戻ることを確認する
    assert timer.load_project_cache() == (9, PROJECTS)


def test_load_project_cache_broken_returns_none(tmp_path, monkeypatch):
    path = tmp_path / 'projects.json'
    path.write_text('{ broken', encoding='utf-8')
    monkeypatch.setattr(timer, 'PROJECTS_CACHE_FILE', path)
    assert timer.load_project_cache() is None


def test_elapsed_and_format():
    now = dt.datetime(2026, 8, 25, 11, 23, 45, tzinfo=dt.timezone.utc)
    entry = {'start': '2026-08-25T10:00:00+00:00'}
    assert timer.format_elapsed(timer.elapsed_seconds(entry, now)) == '1h23m45s'


def test_elapsed_accepts_z_suffix():
    now = dt.datetime(2026, 8, 25, 10, 30, tzinfo=dt.timezone.utc)
    assert timer.elapsed_seconds({'start': '2026-08-25T10:00:00Z'}, now) == 1800


def test_describe_project_unknown_id_is_not_no_project():
    # archive 済みはキャッシュに載らない。解決できないIDを「無し」と偽らない
    assert timer.describe_project(999, PROJECTS) == '(project #999)'
    assert timer.describe_project(None, PROJECTS) == '(no project)'
    assert timer.describe_project(1, PROJECTS) == '読書'
