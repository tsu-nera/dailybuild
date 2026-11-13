"""
XOSS の FIT・rides.csv（Issue #253）の保存のテスト

同じ FIT の再取り込みで行が増えない・入力に無い既存行を消さない・
保存済みの FIT を上書きしないことを確認する。
"""

import pandas as pd

from lib.xoss import fit_summary, store


def _row(name, start, distance='1000.0'):
    row = dict.fromkeys(fit_summary.COLUMNS, '')
    row.update(file=name, start=start, distance_m=distance)
    return row


def _load(csv):
    return pd.read_csv(csv, dtype=str, keep_default_na=False)


def test_reimporting_same_file_does_not_add_rows(tmp_path):
    csv = tmp_path / 'rides.csv'
    store.upsert_rides([_row('a.fit', '2026-10-01T10:00:00+09:00')], csv)
    store.upsert_rides([_row('a.fit', '2026-10-01T10:00:00+09:00')], csv)

    assert list(_load(csv)['file']) == ['a.fit']


def test_rows_absent_from_input_are_kept_and_sorted_by_start(tmp_path):
    csv = tmp_path / 'rides.csv'
    store.upsert_rides([_row('b.fit', '2026-10-02T10:00:00+09:00')], csv)
    store.upsert_rides([_row('a.fit', '2026-10-01T10:00:00+09:00')], csv)

    assert list(_load(csv)['file']) == ['a.fit', 'b.fit']


def test_new_row_replaces_same_key(tmp_path):
    csv = tmp_path / 'rides.csv'
    store.upsert_rides([_row('a.fit', '2026-10-01T10:00:00+09:00', '1000.0')], csv)
    store.upsert_rides([_row('a.fit', '2026-10-01T10:00:00+09:00', '2000.0')], csv)

    assert list(_load(csv)['distance_m']) == ['2000.0']


def test_existing_fit_is_not_overwritten(tmp_path):
    fit_dir = tmp_path / 'fit'
    fit_dir.mkdir()
    (fit_dir / 'a.fit').write_bytes(b'original')
    src = tmp_path / 'a.fit'
    src.write_bytes(b'new')

    assert store.save_fit(src, fit_dir) is False
    assert (fit_dir / 'a.fit').read_bytes() == b'original'


def test_new_fit_is_saved(tmp_path):
    fit_dir = tmp_path / 'fit'
    src = tmp_path / 'b.fit'
    src.write_bytes(b'data')

    assert store.save_fit(src, fit_dir) is True
    assert store.existing_fit_names(fit_dir) == {'b.fit'}
