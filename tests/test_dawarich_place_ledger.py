import pandas as pd

from lib.dawarich import place_ledger as pl

A, B = 'google:A', 'google:B'


def _dump(places, visit_place):
    return {'places': places, 'visit_place': {str(k): v for k, v in visit_place.items()}}


def _place(pid, ext, name, visit_id, archived=False):
    return {'place_id': pid, 'external_place_id': ext, 'name': name, 'archived': archived,
            'note': '', 'visit_id': visit_id}


def _first():
    dump = _dump([_place(1, A, '自宅', 10), _place(2, B, 'メゾン稲田堤', 20)], {10: 1, 20: 2})
    return pl.update(pd.DataFrame(columns=pl.COLUMNS), dump, '2026-11-13')


def _row(df, ext):
    return df.set_index('external_place_id').loc[ext]


def test_merge_is_inferred_from_where_the_visit_moved():
    # UI で B を A へ merge: B の Place は消え、B の Visit 20 は A の Place 1 へ移る
    dump = _dump([_place(1, A, '自宅', 10)], {10: 1, 20: 1})
    out = pl.update(_first(), dump, '2026-11-14')
    assert _row(out, B)['merged_into'] == A
    assert _row(out, B)['updated_at'] == '2026-11-14'


def test_vanished_place_whose_visit_is_gone_keeps_its_row():
    # import を消して Place も Visit も消えた。判断を捨てない
    dump = _dump([_place(1, A, '自宅', 10)], {10: 1})
    out = pl.update(_first(), dump, '2026-11-14')
    assert _row(out, B)['name'] == 'メゾン稲田堤'
    assert _row(out, B)['merged_into'] == ''


def test_recreated_place_keeps_the_previous_decision():
    merged = pl.update(_first(), _dump([_place(1, A, '自宅', 10)], {10: 1, 20: 1}), '2026-11-14')
    # 取り込み直しで B が Unknown の Place 3 として戻ってきた
    dump = _dump([_place(1, A, '自宅', 10), _place(3, B, 'Unknown', 30)], {10: 1, 30: 3})
    out = pl.update(merged, dump, '2026-11-15')
    assert _row(out, B)['merged_into'] == A
    assert _row(out, B)['place_id'] == '3'


def test_ui_rename_and_archive_on_the_same_place_are_copied():
    dump = _dump([_place(1, A, '家', 10), _place(2, B, 'メゾン稲田堤', 20, archived=True)], {10: 1, 20: 2})
    out = pl.update(_first(), dump, '2026-11-14')
    assert _row(out, A)['name'] == '家'
    assert _row(out, B)['archived'] == 'true'


def test_unknown_does_not_overwrite_a_known_name():
    dump = _dump([_place(1, A, 'Unknown', 10), _place(2, B, 'メゾン稲田堤', 20)], {10: 1, 20: 2})
    out = pl.update(_first(), dump, '2026-11-14')
    assert _row(out, A)['name'] == '自宅'
    assert _row(out, A)['updated_at'] == '2026-11-13'


def test_unchanged_run_is_idempotent():
    first = _first()
    dump = _dump([_place(1, A, '自宅', 10), _place(2, B, 'メゾン稲田堤', 20)], {10: 1, 20: 2})
    assert pl.update(first, dump, '2026-11-20').equals(first)
