"""items.csv → Homebox の push が二重に作らないこと・UI 側の物と欄を消さないこと"""

import copy
import uuid

import pandas as pd

from lib.inventory.homebox_sync import desired_entities, push

ITEM_TYPE = {'id': 't-item', 'name': 'Item', 'isLocation': False}
LOC_TYPE = {'id': 't-loc', 'name': 'Location', 'isLocation': True}


class FakeHomebox:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.tag_list: list[dict] = []

    def entity_types(self):
        return [ITEM_TYPE, LOC_TYPE]

    def list_entities(self, entity_type_id):
        # 本物は includeArchived を付けないと archived を返さない。クライアントが付ける前提で全件
        return [{'id': e['id'], 'name': e['name']} for e in self.entities.values()
                if e['entityType']['id'] == entity_type_id]

    def get_entity(self, entity_id):
        return copy.deepcopy(self.entities[entity_id])

    def create_entity(self, body):
        eid = str(uuid.uuid4())
        self.entities[eid] = {'id': eid, 'name': body['name'], 'entityType': ITEM_TYPE,
                              'tags': [], 'fields': [], 'notes': '', 'purchaseDate': '',
                              'purchasePrice': 0, 'purchaseFrom': '', 'archived': False,
                              'soldDate': '', 'quantity': body.get('quantity', 0)}
        return {'id': eid, 'name': body['name']}

    def update_entity(self, entity_id, body):
        e = self.entities[entity_id]
        for k, v in body.items():
            if k == 'tagIds':
                e['tags'] = [t for t in self.tag_list if t['id'] in v]
            elif k == 'fields':
                e['fields'] = [dict(f, id=f.get('id') or str(uuid.uuid4())) for f in v]
            elif k == 'locationId':
                e['location'] = {'id': v}
            else:
                e[k] = v
        return e

    def tags(self):
        return list(self.tag_list)

    def create_tag(self, name):
        tag = {'id': str(uuid.uuid4()), 'name': name}
        self.tag_list.append(tag)
        return tag


def _items():
    return pd.DataFrame([
        {'key': 'manual:1', 'name': 'ノートPC', 'category': 'PC', 'subcategory': 'ノート',
         'status': 'owned', 'location': '', 'acquired_on': '2024-10-18', 'disposed_on': '', 'note': ''},
        {'key': 'amazon:1-2:B0', 'name': '', 'category': '日用品', 'subcategory': '',
         'status': 'owned', 'location': '', 'acquired_on': '', 'disposed_on': '', 'note': ''},
        {'key': 'manual:2', 'name': '古い鍋', 'category': '家電', 'subcategory': '',
         'status': 'disposed', 'location': '', 'acquired_on': '', 'disposed_on': '2026-11-01', 'note': '捨てた'},
    ])


LOOKUP = {'amazon:1-2:B0': {'name': '耳栓', 'purchaseDate': '2026-01-02',
                            'purchasePrice': 3000.0, 'purchaseFrom': 'Amazon'}}


def test_second_push_creates_nothing():
    hb = FakeHomebox()
    desired = desired_entities(_items(), LOOKUP)

    first = push(hb, desired)
    second = push(hb, desired)

    assert len(first.created) == 3
    assert second.created == [] and second.updated == []
    assert len(hb.entities) == 3
    assert sorted(t['name'] for t in hb.tag_list) == ['PC', 'ノート', '家電', '日用品']


def test_joined_name_and_disposed_state():
    hb = FakeHomebox()
    push(hb, desired_entities(_items(), LOOKUP))

    by_name = {e['name']: e for e in hb.entities.values()}
    assert by_name['耳栓']['purchasePrice'] == 3000.0
    assert by_name['古い鍋']['archived'] is True
    assert by_name['古い鍋']['soldDate'] == '2026-11-01'


def test_ui_side_edits_and_items_survive():
    hb = FakeHomebox()
    desired = desired_entities(_items(), LOOKUP)
    push(hb, desired)

    pc = next(e for e in hb.entities.values() if e['name'] == 'ノートPC')
    ui_tag = hb.create_tag('お気に入り')
    pc['tags'].append(ui_tag)
    pc['location'] = {'id': 'loc-desk'}
    hb.create_entity({'name': 'UI で足した物'})

    result = push(hb, desired)

    assert result.created == [] and result.updated == []
    assert result.unmanaged == ['UI で足した物']
    assert len(hb.entities) == 4
    assert pc['location'] == {'id': 'loc-desk'}
    assert 'お気に入り' in [t['name'] for t in hb.entities[pc['id']]['tags']]


def test_csv_change_updates_in_place():
    hb = FakeHomebox()
    push(hb, desired_entities(_items(), LOOKUP))

    items = _items()
    items.loc[0, 'status'] = 'disposed'
    items.loc[0, 'disposed_on'] = '2026-11-10'
    result = push(hb, desired_entities(items, LOOKUP))

    assert result.updated == ['manual:1'] and result.created == []
    pc = next(e for e in hb.entities.values() if e['name'] == 'ノートPC')
    assert pc['archived'] is True


def test_long_amazon_name_is_cut_to_255_bytes():
    items = _items().iloc[[1]]
    lookup = {'amazon:1-2:B0': dict(LOOKUP['amazon:1-2:B0'], name='耳栓' * 200)}

    name = desired_entities(items, lookup)[0].values['name']

    assert len(name.encode()) <= 255 and name.endswith('…')
