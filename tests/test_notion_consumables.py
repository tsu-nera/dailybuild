"""Notion「消耗品DB」→ CSV の同期が、欠測を捏造せず・二重に入れないこと"""

import datetime as dt

import pytest

from lib.inventory.notion_consumables import SyncError, sync

TODAY = dt.date(2026, 11, 26)
HEADER = 'key,name,category,location,unit,keep,subscription,note,ended_on\n'


def page(page_id, name, key='', category='日用品', unit='個', qty=None, note='',
         edited='2026-11-25T16:30:00.000Z'):
    """Notion API の page オブジェクトの形（使う列だけ）"""
    def rich(kind, text):
        return {'type': kind, kind: [{'plain_text': text}] if text else []}
    return {
        'id': page_id, 'object': 'page', 'in_trash': False, 'last_edited_time': edited,
        'properties': {
            '品目': rich('title', name),
            'key': rich('rich_text', key),
            '分類': {'type': 'select', 'select': {'name': category} if category else None},
            '単位': {'type': 'select', 'select': {'name': unit} if unit else None},
            '量': {'type': 'number', 'number': qty},
            'メモ': rich('rich_text', note),
            '更新': {'type': 'last_edited_time', 'last_edited_time': edited},
        },
    }


class FakeNotion:
    def __init__(self, pages):
        self.pages = pages
        self.updates = []

    def query_data_source(self, data_source_id):
        return self.pages

    def set_rich_text(self, page_id, prop, text):
        self.updates.append((page_id, prop, text))


@pytest.fixture
def csvs(tmp_path):
    c = tmp_path / 'consumables.csv'
    c.write_text(HEADER
                 + 'protein,プロテイン,食料品,その他,kg,2,定期,古いメモ,\n'
                 + 'eggs,卵,食料品,冷蔵庫,個,,,,\n'
                 + 'old,昔の品,日用品,棚,個,,,,2026-01-01\n', encoding='utf-8')
    s = tmp_path / 'stocktake.csv'
    s.write_text('date,key,quantity,note\n2026-11-13,protein,1.5,半分くらい\n', encoding='utf-8')
    return c, s


def run(fake, csvs):
    sync(fake, 'ds', csvs[0], csvs[1], TODAY, log=lambda m: None)


def rows(path):
    import csv
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def base_pages():
    return [page('11111111-aaaa-bbbb-cccc-000000000001', 'プロテイン', key='protein',
                 category='食料品', unit='kg', qty=1.5, note='新しいメモ'),
            page('22222222-aaaa-bbbb-cccc-000000000002', '卵', key='eggs', category='食料品')]


def test_empty_key_gets_page_id_key_and_one_writeback(csvs):
    fake = FakeNotion(base_pages() + [page('abcd1234-ef56-7890-0000-000000000003', 'トランクス')])
    run(fake, csvs)
    assert fake.updates == [('abcd1234-ef56-7890-0000-000000000003', 'key', 'n_abcd1234')]
    new = rows(csvs[0])[-1]
    assert new['key'] == 'n_abcd1234' and new['name'] == 'トランクス'
    assert new['location'] == '' and new['ended_on'] == ''


def test_duplicate_key_writes_nothing(csvs):
    before = (csvs[0].read_bytes(), csvs[1].read_bytes())
    fake = FakeNotion(base_pages() + [page('33333333-0000-0000-0000-000000000000', '単3電池', key='battery'),
                                      page('44444444-0000-0000-0000-000000000000', '単4電池', key='battery'),
                                      page('55555555-0000-0000-0000-000000000000', 'Tシャツ')])
    with pytest.raises(SyncError, match='単3電池'):
        run(fake, csvs)
    assert (csvs[0].read_bytes(), csvs[1].read_bytes()) == before
    assert fake.updates == []


def test_zero_pages_writes_nothing(csvs):
    before = (csvs[0].read_bytes(), csvs[1].read_bytes())
    with pytest.raises(SyncError):
        run(FakeNotion([]), csvs)
    assert (csvs[0].read_bytes(), csvs[1].read_bytes()) == before


def test_notion_columns_overwrite_and_local_columns_kept(csvs):
    run(FakeNotion(base_pages()), csvs)
    protein = rows(csvs[0])[0]
    assert protein['note'] == '新しいメモ'
    assert (protein['location'], protein['keep'], protein['subscription']) == ('その他', '2', '定期')
    assert protein['ended_on'] == ''


def test_vanished_key_kept_with_ended_on_and_existing_date_untouched(csvs):
    run(FakeNotion(base_pages()[:1]), csvs)
    by_key = {r['key']: r for r in rows(csvs[0])}
    assert by_key['eggs']['ended_on'] == '2026-11-26'
    assert by_key['old']['ended_on'] == '2026-01-01'


def test_stocktake_idempotent(csvs):
    pages = base_pages()
    pages[1] = page('22222222-aaaa-bbbb-cccc-000000000002', '卵', key='eggs', qty=6)
    run(FakeNotion(pages), csvs)
    n = len(rows(csvs[1]))
    run(FakeNotion(pages), csvs)
    assert len(rows(csvs[1])) == n


def test_stocktake_only_changed_quantity_with_jst_date(csvs):
    pages = base_pages()  # protein は前回と同じ 1.5
    # 2026-11-25T16:30Z は JST で 11-26
    pages[1] = page('22222222-aaaa-bbbb-cccc-000000000002', '卵', key='eggs', qty=6)
    run(FakeNotion(pages), csvs)
    st = rows(csvs[1])
    assert len(st) == 2
    assert st[-1] == {'date': '2026-11-26', 'key': 'eggs', 'quantity': '6', 'note': ''}

    pages[0] = page('11111111-aaaa-bbbb-cccc-000000000001', 'プロテイン', key='protein', qty=0.8,
                    edited='2026-11-27T01:00:00.000Z')
    run(FakeNotion(pages), csvs)
    st = rows(csvs[1])
    assert len(st) == 3
    assert st[-1] == {'date': '2026-11-27', 'key': 'protein', 'quantity': '0.8', 'note': ''}
