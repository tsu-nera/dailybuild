"""
Dawarich の Unknown の Place に付ける名前（place_names）のテスト

手で決めた名前が辞書に負けないこと、引いたが名前の無かった ID を毎回 API で引き直さないこと、
キャッシュに二重に入れないことを確認する。
"""

import pandas as pd

from lib.dawarich import place_names
from lib.timeline import PLACE_COLUMNS


def _places(*rows):
    return pd.DataFrame([dict(zip(PLACE_COLUMNS, r)) for r in rows], columns=PLACE_COLUMNS)


EMPTY = _places()


def test_priority_override_home_dictionary_cache():
    places = _places(('A', '辞書A', '', 'ok', ''), ('B', '辞書B', '', 'ok', ''), ('C', '辞書C', '', 'ok', ''))
    cache = _places(('C', 'キャッシュC', '', 'ok', ''), ('D', 'キャッシュD', '', 'ok', ''))
    overrides = {'A': {'name': '手A', 'note': 'ずれている'}}

    resolved, misses = place_names.resolve(['A', 'B', 'C', 'D', 'E'], overrides, {'B'}, places, cache)

    assert {k: v['name'] for k, v in resolved.items()} == {
        'A': '手A', 'B': place_names.HOME_NAME, 'C': '辞書C', 'D': 'キャッシュD'}
    assert resolved['A']['note'] == 'ずれている'
    assert misses == ['E']


def test_not_found_is_not_looked_up_again():
    places = _places(('A', '', '', 'not_found', ''))
    cache = _places(('B', '', '', 'not_found', ''))
    resolved, misses = place_names.resolve(['A', 'B'], {}, set(), places, cache)
    assert resolved == {} and misses == []


def test_duplicate_ids_are_looked_up_once():
    _, misses = place_names.resolve(['A', 'A', 'B'], {}, set(), EMPTY, EMPTY)
    assert misses == ['A', 'B']


def test_append_cache_keeps_existing_rows(tmp_path):
    path = tmp_path / 'cache.csv'
    place_names.append_cache([{'place_id': 'A', 'display_name': '旧', 'primary_type': '',
                               'status': 'ok', 'resolved_at': 't1'}], path)
    place_names.append_cache([{'place_id': 'A', 'display_name': '新', 'primary_type': '',
                               'status': 'ok', 'resolved_at': 't2'},
                              {'place_id': 'B', 'display_name': 'B', 'primary_type': '',
                               'status': 'ok', 'resolved_at': 't2'}], path)
    cache = place_names.read_cache(path)
    assert list(cache['place_id']) == ['A', 'B']
    assert cache.loc[cache['place_id'] == 'A', 'display_name'].item() == '旧'
