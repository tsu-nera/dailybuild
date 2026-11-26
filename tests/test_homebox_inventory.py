"""持ち物の正本（Homebox）への書き込みが二重にならないこと・items.csv を空で潰さないこと"""

import copy
import uuid

import pytest

from lib.inventory.buyback import BuybackError, fetch_buybacks, parse_buyback
from lib.inventory.homebox import (InventoryError, add_item, dispose_item, export_rows, field_text,
                                   find_rows, fit_name, load_items, mercari_sales, move_item, normalize_isbn,
                                   notes_with_link, plan_disposal, set_market_price, set_market_query,
                                   market_targets, write_csv)
from lib.inventory.market import read_history

NIL = '00000000-0000-0000-0000-000000000000'
ITEM_TYPE = {'id': 't-item', 'name': 'Item', 'isLocation': False}
LOC_TYPE = {'id': 't-loc', 'name': 'Location', 'isLocation': True}


class FakeHomebox:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.tag_list: list[dict] = []
        self.maint: dict[str, dict] = {}

    def maintenance(self, entity_id):
        return [copy.deepcopy(m) for m in self.maint.values() if m['itemID'] == entity_id]

    def create_maintenance(self, entity_id, body):
        mid = str(uuid.uuid4())
        self.maint[mid] = {'completedDate': '', **body, 'id': mid, 'itemID': entity_id}
        return copy.deepcopy(self.maint[mid])

    def update_maintenance(self, entry_id, body):
        # 本物の PUT も全欄置き換え
        self.maint[entry_id] = {**body, 'id': entry_id, 'itemID': self.maint[entry_id]['itemID']}
        return copy.deepcopy(self.maint[entry_id])

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


def test_plan_twice_does_not_duplicate():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', 'スポーツ用品', name='ストレッチポール')

    plan_disposal(hb, 'manual:1', '売却', '2026-11-11')
    plan_disposal(hb, 'manual:1', '売却', '2026-11-12')

    assert [m['scheduledDate'] for m in hb.maint.values()] == ['2026-11-11']


def test_dispose_closes_only_open_disposal_entries():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', 'スポーツ用品', name='ストレッチポール')
    eid = next(iter(hb.entities))
    plan_disposal(hb, 'manual:1', '売却', '2026-11-11')
    hb.create_maintenance(eid, {'name': '修理', 'scheduledDate': '2026-11-01', 'cost': '0'})
    hb.create_maintenance(eid, {'name': '破棄', 'scheduledDate': '2025-01-01',
                                'completedDate': '2025-02-01', 'cost': '0'})

    dispose_item(hb, 'manual:1', '2026-11-20', 'メルカリで売却（m1）', 7000.0, 'メルカリ')

    done = {m['name']: m['completedDate'] for m in hb.maint.values()}
    assert done == {'売却': '2026-11-20', '修理': '', '破棄': '2025-02-01'}
    sale = next(m for m in hb.maint.values() if m['name'] == '売却')
    assert (sale['scheduledDate'], sale['cost']) == ('2026-11-11', '0')


def test_plan_refuses_unknown_kind():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '家電', name='鍋')
    with pytest.raises(InventoryError):
        plan_disposal(hb, 'manual:1', '修理', '2026-11-11')


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


def test_market_price_overwrites_field_and_appends_history():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '家電', name='ヘッドホン', note='中古', price=16000, purchase_from='ソフマップ')
    set_market_price(hb, 'manual:1', 7000, '2026-11-01', 'メルカリ SOLD 中央値')
    set_market_price(hb, 'manual:1', 7150, '2026-11-12', 'メルカリ SOLD 中央値')
    (row,) = export_rows(hb)
    assert row['market_price'] == '7150'
    assert row['purchase_price'] == '16000' and row['purchase_from'] == 'ソフマップ'
    assert row['note'] == '中古\n\n相場 2026-11-01: メルカリ SOLD 中央値 7,000円\n\n相場 2026-11-12: メルカリ SOLD 中央値 7,150円'
    e = next(iter(hb.entities.values()))
    assert [f['name'] for f in e['fields']] == ['key', '中古相場']


def test_market_price_is_optional():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '家電', name='ヘッドホン')
    assert export_rows(hb)[0]['market_price'] == ''


def test_market_price_same_day_rerun_replaces_history_line():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '家電', name='ヘッドホン', note='中古')
    set_market_price(hb, 'manual:1', 7000, '2026-11-12', 'メルカリ SOLD 中央値')
    set_market_price(hb, 'manual:1', 7150, '2026-11-12', 'メルカリ SOLD 中央値')
    assert export_rows(hb)[0]['note'] == '中古\n\n相場 2026-11-12: メルカリ SOLD 中央値 7,150円'


def test_market_targets_skip_disposed_and_bad_query_is_rejected():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '家電', name='ヘッドホン')
    add_item(hb, 'manual:2', '家電', name='売った時計')
    add_item(hb, 'manual:3', '家電', name='条件なし')
    set_market_query(hb, 'manual:1', 'WH-1000XM3 --min 5000')
    set_market_query(hb, 'manual:2', 'Charge 6')
    dispose_item(hb, 'manual:2', '2026-11-12')

    with pytest.raises(InventoryError):
        set_market_query(hb, 'manual:3', 'Charge 6 --min abc')

    assert {k: q for k, (_, q) in market_targets(hb).items()} == {'manual:1': 'WH-1000XM3 --min 5000'}


ISBN = '9784300108819'


def test_isbn_goes_into_custom_field_as_text():
    hb = FakeHomebox()
    entity = add_item(hb, 'manual:1', '本', name='電験三種 理論', isbn='978-4-300-10881-9')

    assert field_text(entity, 'ISBN') == ISBN


def test_same_isbn_owned_refuses_without_creating():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '本', name='電験三種 理論', isbn=ISBN)

    with pytest.raises(InventoryError):
        add_item(hb, 'manual:2', '本', name='電験三種 理論 第3版', isbn=ISBN)

    assert len(hb.entities) == 1


def test_same_isbn_disposed_can_be_added_again():
    hb = FakeHomebox()
    add_item(hb, 'manual:1', '本', name='電験三種 理論', isbn=ISBN)
    dispose_item(hb, 'manual:1', '2026-11-20', how='売却')

    add_item(hb, 'manual:2', '本', name='電験三種 理論', isbn=ISBN)

    assert len(hb.entities) == 2


@pytest.mark.parametrize('isbn', ['9784300108818', '1234567890128', '4300108819', '97843001088X9'])
def test_bad_isbn_refuses_before_touching_homebox(isbn):
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f'Homebox に触れた: {name}')

    with pytest.raises(InventoryError):
        normalize_isbn(isbn)
    with pytest.raises(InventoryError):
        add_item(Untouchable(), 'manual:1', '本', name='x', isbn=isbn)


# ---- 買取価格（lib.inventory.buyback）。参照元はフェイクにする ----

def _books(hb):
    add_item(hb, 'manual:1', '本', name='電験三種 理論', isbn=ISBN)
    add_item(hb, 'manual:2', '本', name='電験三種 電力', isbn='9784300108826')
    add_item(hb, 'manual:3', '日用品', name='フライパン')


def _fake(prices):
    calls = []

    def fetch(isbn):
        calls.append(isbn)
        v = prices[isbn]
        if isinstance(v, Exception):
            raise v
        return v
    return fetch, calls


def test_buyback_new_item_is_fetched_and_written(tmp_path):
    hb = FakeHomebox()
    _books(hb)
    path = tmp_path / 'buyback.csv'
    fetch, calls = _fake({ISBN: 300, '9784300108826': 250})

    assert fetch_buybacks(hb, path, '2026-11-26', 30, fetch=fetch) == 0

    assert sorted(calls) == sorted([ISBN, '9784300108826'])  # ISBN の無い物は引かない
    rows = {r['key']: r for r in read_history(path)}
    assert rows['manual:1'] == {'date': '2026-11-26', 'key': 'manual:1', 'name': '電験三種 理論',
                                'isbn': ISBN, 'price': '300', 'source': '駿河屋 買取'}
    owned = load_items(hb)
    assert field_text(owned['manual:1'], '買取価格') == '300'
    assert '買取' not in owned['manual:1']['notes']  # メモには書かない


def test_buyback_recent_item_is_not_fetched_again(tmp_path):
    hb = FakeHomebox()
    _books(hb)
    path = tmp_path / 'buyback.csv'
    fetch, calls = _fake({ISBN: 300, '9784300108826': 250})
    fetch_buybacks(hb, path, '2026-11-01', 30, fetch=fetch)
    calls.clear()

    fetch_buybacks(hb, path, '2026-11-30', 30, fetch=fetch)
    assert calls == []
    fetch_buybacks(hb, path, '2026-12-01', 30, fetch=fetch)
    assert sorted(calls) == sorted([ISBN, '9784300108826'])


def test_buyback_failure_leaves_no_row_and_others_continue(tmp_path):
    hb = FakeHomebox()
    _books(hb)
    path = tmp_path / 'buyback.csv'
    fetch, _ = _fake({ISBN: RuntimeError('503'), '9784300108826': 250})

    assert fetch_buybacks(hb, path, '2026-11-26', 30, fetch=fetch) == 1

    assert [r['key'] for r in read_history(path)] == ['manual:2']
    assert field_text(load_items(hb)['manual:1'], '買取価格') == ''


def test_buyback_not_buyable_keeps_previous_price(tmp_path):
    hb = FakeHomebox()
    _books(hb)
    path = tmp_path / 'buyback.csv'
    fetch_buybacks(hb, path, '2026-10-01', 30, fetch=_fake({ISBN: 300, '9784300108826': 250})[0])

    fetch_buybacks(hb, path, '2026-11-26', 30, fetch=_fake({ISBN: None, '9784300108826': 250})[0])

    latest = [r for r in read_history(path) if r['date'] == '2026-11-26' and r['key'] == 'manual:1']
    assert latest[0]['price'] == ''
    assert field_text(load_items(hb)['manual:1'], '買取価格') == '300'


def test_buyback_skips_disposed(tmp_path):
    hb = FakeHomebox()
    _books(hb)
    dispose_item(hb, 'manual:1', '2026-11-20', how='売却')
    fetch, calls = _fake({ISBN: 300, '9784300108826': 250})

    fetch_buybacks(hb, tmp_path / 'buyback.csv', '2026-11-26', 30, fetch=fetch)

    assert calls == ['9784300108826']


def _page(rows_html):
    return f'<html><table class="result">{rows_html}</table></html>'


def _row(isbn, kakaku):
    return (f'<tr class="listap"><td><input data-product="{{&quot;shinaban&quot;:&quot;BO1&quot;,'
            f'&quot;kakaku&quot;:{kakaku}}}"></td><td>{isbn}<br>BO1</td></tr>')


def test_parse_buyback_price_and_not_buyable():
    assert parse_buyback(_page(_row(ISBN, 300)), ISBN) == 300
    assert parse_buyback(_page(_row(ISBN, -1)), ISBN) is None  # メールにてお見積
    assert parse_buyback(_page(_row('9784300108826', 500)), ISBN) is None  # 別の本しか出ない
    assert parse_buyback('<p>検索結果は０件です。条件を変更して下さい。</p>', ISBN) is None


def test_parse_buyback_changed_page_raises():
    with pytest.raises(BuybackError):
        parse_buyback('<html>メンテナンス中</html>', ISBN)
