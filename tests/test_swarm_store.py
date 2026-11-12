"""
Swarm チェックイン（Issue #92）の保存のテスト

取り直しで二重に入れない・API に無い行を消さない・id を数値に化けさせないことを確認する。
"""

from lib.swarm import client, store


def _checkin(cid, created_at, venue='Cafe', shout=None):
    c = {
        'id': cid, 'createdAt': created_at, 'timeZoneOffset': 540, 'type': 'checkin',
        'venue': {
            'id': 'v1', 'name': venue,
            'location': {'lat': 35.6, 'lng': 139.7, 'city': 'Tokyo', 'country': 'Japan'},
            'categories': [{'name': 'Bar', 'primary': False}, {'name': 'Café', 'primary': True}],
        },
        'photos': {'count': 0, 'items': []},
    }
    if shout is not None:
        c['shout'] = shout
    return c


def _ingest(items, tmp_path):
    raw = store.merge_raw(items, raw_path=tmp_path / 'checkins.jsonl')
    store.write_csv(raw, csv_path=tmp_path / 'checkins.csv')
    return store.load_checkins(tmp_path / 'checkins.csv')


def test_ids_that_look_numeric_survive_round_trip(tmp_path):
    # 16進の id がたまたま数字だけ・指数表記に見える形でも丸めない
    ids = ['512345678901234567890123', '5e1234567890abcdef123456', '4d627f6814963704dc28ff94']
    df = _ingest([_checkin(i, 1700000000 + n) for n, i in enumerate(ids)], tmp_path)
    assert list(df['id']) == ids


def test_refetching_overlap_does_not_duplicate_and_updates(tmp_path):
    _ingest([_checkin('a' * 24, 1700000000), _checkin('b' * 24, 1700000100)], tmp_path)
    df = _ingest([_checkin('b' * 24, 1700000100, shout='edited'), _checkin('c' * 24, 1700000200)], tmp_path)

    assert list(df['id']) == ['a' * 24, 'b' * 24, 'c' * 24]
    assert df.loc[df['id'] == 'b' * 24, 'shout'].item() == 'edited'


def test_rows_missing_from_refetch_are_kept(tmp_path):
    _ingest([_checkin('a' * 24, 1700000000), _checkin('b' * 24, 1700000100)], tmp_path)
    _ingest([], tmp_path)
    df = _ingest([_checkin('b' * 24, 1700000100)], tmp_path)
    assert len(df) == 2


def test_flatten_uses_local_offset_and_primary_category(tmp_path):
    df = _ingest([_checkin('a' * 24, 1700000000)], tmp_path)
    row = df.iloc[0]
    assert row['created_at'] == '2023-11-15T07:13:20+09:00'
    assert row['category'] == 'Café'


def test_code_from_redirect_accepts_url_or_bare_code():
    assert client.code_from_redirect('http://localhost:8765/callback?code=XYZ#_=_') == 'XYZ'
    assert client.code_from_redirect(' XYZ \n') == 'XYZ'
