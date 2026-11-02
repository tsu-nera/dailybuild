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


def test_build_start_payload_uses_type_and_tag_ids():
    payload = timer.build_start_payload(1, '読書', [908186])
    # type: "activity" が無いと 400。タグは tag_ids でしか付かない
    assert payload == {'type': 'activity', 'description': '読書',
                       'project_id': 1, 'tag_ids': [908186]}
    assert 'tags' not in payload and 'start' not in payload


def test_build_start_payload_without_project_or_tags():
    payload = timer.build_start_payload(None, 'メモ', [])
    assert 'project_id' not in payload and 'tag_ids' not in payload


def test_resolve_tags_maps_names_to_ids():
    assert timer.resolve_tags(('auto', 'deep'), {'auto': 1, 'deep': 2}) == [1, 2]


def test_resolve_tags_unknown_lists_known_names():
    with pytest.raises(timer.TagResolutionError) as e:
        timer.resolve_tags(('nope',), {'auto': 1, 'deep': 2})
    assert 'nope' in str(e.value) and 'auto' in str(e.value) and 'deep' in str(e.value)


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


def test_describe_entry_accepts_tag_objects():
    now = dt.datetime(2026, 8, 25, 10, 30, tzinfo=dt.timezone.utc)
    entry = {'start': '2026-08-25T10:00:00Z', 'project_id': 1, 'description': 'x',
             'tags': [{'id': 1, 'name': 'deep'}]}
    assert timer.describe_entry(entry, PROJECTS, now) == '[読書] x [deep] (0h30m00s 経過)'


def test_describe_project_unknown_id_is_not_no_project():
    # archive 済みはキャッシュに載らない。解決できないIDを「無し」と偽らない
    assert timer.describe_project(999, PROJECTS) == '(project #999)'
    assert timer.describe_project(None, PROJECTS) == '(no project)'
    assert timer.describe_project(1, PROJECTS) == '読書'
