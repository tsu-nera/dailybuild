"""持ち物の正本（Homebox）への書き込みが二重にならないこと・items.csv を空で潰さないこと"""

import copy
import uuid

import pytest

from lib.inventory.homebox import (InventoryError, add_item, dispose_item, export_rows,
                                   find_rows, fit_name, mercari_sales, move_item, notes_with_link,
                                   write_csv)

NIL = '00000000-0000-0000-0000-000000000000'
ITEM_TYPE = {'id': 't-item', 'name': 'Item', 'isLocation': False}
LOC_TYPE = {'id': 't-loc', 'name': 'Location', 'isLocation': True}


class FakeHomebox:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.tag_list: list[dict] = []

    def entity_types(self):
        return [ITEM_TYPE, LOC_TYPE]

    def get_entity(self, entity_id):
        return copy.deepcopy(self.entities[entity_id])

    def add_location(self, name, parent=None):
        eid = str(uuid.uuid4())
        self.entities[eid] = {'id': eid, 'name': name, 'entityType': LOC_TYPE,
                              'parent': {'id': parent} if parent else None}
        return eid

    def list_entities(self, entity_type_id):
        return [{'id': e['id'], 'name': e['name'], 'parent': e.get('parent')}
                for e in self.entities.values() if e['entityType']['id'] == entity_type_id]

    def create_entity(self, body):
        eid = str(uuid.uuid4())
        self.entities[eid] = {'id': eid, 'name': body['name'], 'entityType': ITEM_TYPE,
                              'tags': [], 'fields': [], 'notes': '', 'purchaseDate': '',
                              'purchasePrice': 0, 'purchaseFrom': '', 'archived': False,
                              'soldDate': '', 'soldNotes': '', 'parent': None}
        return {'id': eid, 'name': body['name']}

    def update_entity(self, entity_id, body):
        e = self.entities[entity_id]
        for k, v in body.items():
            if k == 'tagIds':
                # 本物と同じく、物に埋め込むタグには親を載せない
                e['tags'] = [dict(t, parentId=NIL) for t in self.tag_list if t['id'] in v]
            elif k == 'parentId':
                e['parent'] = {'id': v, 'name': self.entities[v]['name']}
            elif k == 'fields':
                e['fields'] = [dict(f, id=f.get('id') or str(uuid.uuid4())) for f in v]
            else:
                e[k] = v
        return copy.deepcopy(e)

    def tags(self):
        return copy.deepcopy(self.tag_list)

    def create_tag(self, name):
        tag = {'id': str(uuid.uuid4()), 'name': name, 'parentId': NIL}
        self.tag_list.append(tag)
        return tag

    def create_tag_under(self, name, parent_id):
        tag = self.create_tag(name)
        tag['parentId'] = parent_id
        return tag

    def entity_path(self, entity_id):
        chain, e = [], self.entities[entity_id]
        while e:
            chain.insert(0, {'name': e['name']})
            parent = e.get('parent')
            e = self.entities[parent['id']] if parent else None
        return chain


JOINED = {'name': '耳栓', 'purchaseDate': '2026-01-02', 'purchasePrice': 3000.0, 'purchaseFrom': 'Amazon',
          'url': 'https://www.amazon.co.jp/dp/B0'}


def test_add_twice_does_not_duplicate():
    hb = FakeHomebox()
    add_item(hb, 'amazon:1-2:B0', '日用品', joined=JOINED, alive=lambda u: True)

    with pytest.raises(InventoryError):
        add_item(hb, 'amazon:1-2:B0', '日用品', joined=JOINED, alive=lambda u: True)

    assert len(hb.entities) == 1


def test_tags_are_reused_and_categories_roundtrip():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', 'ファッション', 'トップス', name='Tシャツ')
    add_item(hb, 'manual:2', 'ファッション', 'トップス', name='長袖')
    add_item(hb, 'manual:3', 'ファッション', name='帽子')

    assert sorted(t['name'] for t in hb.tag_list) == ['トップス', 'ファッション']
    rows = {r['key']: r for r in export_rows(hb)}
    assert (rows['manual:1']['category'], rows['manual:1']['subcategory']) == ('ファッション', 'トップス')
    assert (rows['manual:3']['category'], rows['manual:3']['subcategory']) == ('ファッション', '')


def test_joined_purchase_fills_name_date_price():
    hb = FakeHomebox()
    add_item(hb, 'amazon:1-2:B0', '日用品', joined=JOINED, alive=lambda u: True)

    row = export_rows(hb)[0]
    assert (row['name'], row['acquired_on'], row['purchase_price'], row['purchase_from']) == \
        ('耳栓', '2026-01-02', '3000', 'Amazon')


def test_add_without_name_anywhere_refuses():
    hb = FakeHomebox()
    with pytest.raises(InventoryError):
        add_item(hb, 'amazon:9-9:B9', '日用品')
    assert hb.entities == {}


def test_dispose_is_exported_and_kept():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '家電', name='古い鍋')

    dispose_item(hb, 'manual:1', '2026-11-11', '粗大ごみ')

    row = export_rows(hb)[0]
    assert (row['status'], row['disposed_on']) == ('disposed', '2026-11-11')
    assert '粗大ごみ' in row['note']


def test_ui_added_item_without_key_is_exported():
    hb = FakeHomebox()
    created = hb.create_entity({'name': 'UI で足した物'})

    assert export_rows(hb)[0]['key'] == f'homebox:{created["id"]}'


def test_empty_export_does_not_overwrite(tmp_path):
    path = tmp_path / 'items.csv'
    path.write_text('key,name\nmanual:1,PC\n', encoding='utf-8')

    with pytest.raises(InventoryError):
        write_csv(export_rows(FakeHomebox()), path)

    assert path.read_text(encoding='utf-8') == 'key,name\nmanual:1,PC\n'


def test_long_name_is_cut_to_255_bytes():
    name = fit_name('耳栓' * 200)
    assert len(name.encode()) <= 255 and name.endswith('…')


def _home():
    hb = FakeHomebox()
    main = hb.add_location('メイン')
    hb.add_location('机', main)
    hb.add_location('クローゼット', main)
    entrance = hb.add_location('玄関・キッチン')
    hb.add_location('棚', main)
    hb.add_location('棚', entrance)
    add_item(hb, 'manual:1', 'PC', 'ノート', name='ノートPC')
    return hb


def test_move_by_leaf_name_and_export_path():
    hb = _home()

    move_item(hb, 'manual:1', '机')

    assert export_rows(hb)[0]['location'] == 'メイン / 机'


def test_move_refuses_ambiguous_and_unknown_location():
    hb = _home()

    with pytest.raises(InventoryError, match='複数'):
        move_item(hb, 'manual:1', '棚')
    with pytest.raises(InventoryError, match='無い'):
        move_item(hb, 'manual:1', '押し入れ')
    move_item(hb, 'manual:1', '玄関・キッチン / 棚')

    assert export_rows(hb)[0]['location'] == '玄関・キッチン / 棚'


def test_find_filters():
    rows = [
        {'key': 'manual:1', 'name': 'ノートPC', 'category': 'PC', 'subcategory': 'ノート',
         'location': 'メイン / 机', 'status': 'owned', 'note': ''},
        {'key': 'manual:2', 'name': '電子レンジ', 'category': '家電', 'subcategory': 'キッチン家電',
         'location': '玄関・キッチン / キッチン', 'status': 'owned', 'note': ''},
        {'key': 'manual:3', 'name': '古いPC', 'category': 'PC', 'subcategory': '',
         'location': '', 'status': 'disposed', 'note': ''},
    ]

    assert [r['key'] for r in find_rows(rows, 'pc')] == ['manual:1']
    assert [r['key'] for r in find_rows(rows, 'pc', include_disposed=True)] == ['manual:1', 'manual:3']
    assert [r['key'] for r in find_rows(rows, location='キッチン')] == ['manual:2']
    assert [r['key'] for r in find_rows(rows, tag='ノート')] == ['manual:1']


def test_mercari_sales_prefers_web_date(tmp_path):
    (tmp_path / 'mercari.csv').write_text(
        'date,direction,item_id,item,counterparty,price,status,message_id\n'
        '2021-02-27T08:00:00+09:00,sell,m1,HHKB,x,18000,,a\n'
        '2021-03-01T08:00:00+09:00,buy,m2,本,x,500,,b\n', encoding='utf-8')
    (tmp_path / 'mercari_web.csv').write_text(
        'date,direction,item_id,item,price,paid_price,seller_shipping_fee,status\n'
        '2021-02-26T08:36:41+09:00,sell,m1,HHKB,18000,,,done\n', encoding='utf-8')

    sales = mercari_sales(tmp_path)

    assert sales == {'m1': {'date': '2021-02-26', 'price': 18000.0}}


def test_dispose_with_sale_keeps_price_and_buyer():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', 'PC', name='HHKB')

    dispose_item(hb, 'manual:1', '2021-02-26', 'メルカリで売却（m1）', 18000.0, 'メルカリ')

    e = next(iter(hb.entities.values()))
    assert (e['archived'], e['soldPrice'], e['soldTo']) == (True, 18000.0, 'メルカリ')


def test_product_page_link_goes_into_notes():
    hb = FakeHomebox()
    add_item(hb, 'amazon:1-2:B0', '日用品', note='寝室用', joined=JOINED, alive=lambda u: True)
    add_item(hb, 'manual:1', '家電', name='鍋')
    add_item(hb, 'mercari:m1', '家電', joined=dict(JOINED, name='消えた出品', url='https://x/m1'),
             alive=lambda u: False)

    notes = {e['name']: e['notes'] for e in hb.entities.values()}
    assert notes['耳栓'] == '寝室用\n\n[商品ページ（Amazon）](https://www.amazon.co.jp/dp/B0)'
    assert notes['鍋'] == ''
    assert notes['消えた出品'] == ''
    assert notes_with_link('', 'https://x', '') == '[商品ページ（リンク）](https://x)'
