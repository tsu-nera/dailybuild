"""持ち物の正本（Homebox）への書き込みが二重にならないこと・items.csv を空で潰さないこと"""

import copy
import uuid

import pytest

from lib.inventory.homebox import (InventoryError, add_item, dispose_item, export_rows,
                                   fit_name, write_csv)

NIL = '00000000-0000-0000-0000-000000000000'
ITEM_TYPE = {'id': 't-item', 'name': 'Item', 'isLocation': False}
LOC_TYPE = {'id': 't-loc', 'name': 'Location', 'isLocation': True}


class FakeHomebox:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.tag_list: list[dict] = []

    def entity_types(self):
        return [ITEM_TYPE, LOC_TYPE]

    def list_entities(self, entity_type_id):
        return [{'id': e['id'], 'name': e['name']} for e in self.entities.values()
                if e['entityType']['id'] == entity_type_id]

    def get_entity(self, entity_id):
        return copy.deepcopy(self.entities[entity_id])

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
        return [{'name': 'self'}]


JOINED = {'name': '耳栓', 'purchaseDate': '2026-01-02', 'purchasePrice': 3000.0, 'purchaseFrom': 'Amazon'}


def test_add_twice_does_not_duplicate():
    hb = FakeHomebox()
    add_item(hb, 'amazon:1-2:B0', '日用品', joined=JOINED)

    with pytest.raises(InventoryError):
        add_item(hb, 'amazon:1-2:B0', '日用品', joined=JOINED)

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
    add_item(hb, 'amazon:1-2:B0', '日用品', joined=JOINED)

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
