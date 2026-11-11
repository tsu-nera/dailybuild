"""持ち物の正本は Homebox（#263 で採用）。items.csv はここから書き出す生成物

- 物と items.csv の行は custom field `key` で対応する（`amazon:<注文番号>:<ASIN>` など）。
  UI で足して key の無い物は `homebox:<id>` として書き出す
- カテゴリは親タグ、サブカテゴリはその子タグ
- 手放した物は archived + soldDate
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd

KEY_FIELD = 'key'
NAME_MAX_BYTES = 255  # ent schema の MaxLen(255)。len は UTF-8 のバイト数で数える
NIL_ID = '00000000-0000-0000-0000-000000000000'
COLUMNS = ['key', 'name', 'category', 'subcategory', 'status', 'location',
           'acquired_on', 'disposed_on', 'purchase_price', 'purchase_from', 'note']


class InventoryError(RuntimeError):
    pass


def fit_name(name: str) -> str:
    """Amazon の商品名は 255 バイトを超える。文字の途中で切らずに縮める"""
    if len(name.encode()) <= NAME_MAX_BYTES:
        return name
    out = name
    while len((out + '…').encode()) > NAME_MAX_BYTES:
        out = out[:-1]
    return out + '…'


# ---- 購入データからの補完（add で使う） ----

def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _price(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def purchase_lookup(purchases_dir: Path) -> dict[str, dict]:
    """key → {name, purchaseDate, purchasePrice, purchaseFrom}"""
    out: dict[str, dict] = {}

    # gmail.csv は開示データより新しい注文。同じ key なら開示データを優先する
    for name in ('gmail.csv', 'amazon.csv'):
        df = _read(purchases_dir / name)
        if df.empty:
            continue
        if 'shop' in df.columns:
            df = df[df['shop'].str.lower().str.contains('amazon')]
        for r in df.itertuples():
            if r.asin:
                out[f'amazon:{r.order_id}:{r.asin}'] = {
                    'name': r.item, 'purchaseDate': r.order_date[:10],
                    'purchasePrice': _price(r.price), 'purchaseFrom': 'Amazon'}

    rakuten = _read(purchases_dir / 'rakuten.csv')
    if not rakuten.empty:
        for order_id, g in rakuten.groupby('order_id', sort=False):
            for n, r in enumerate(g.itertuples(), start=1):
                out[f'rakuten:{order_id}:{n}'] = {
                    'name': r.item, 'purchaseDate': r.order_date[:10],
                    'purchasePrice': _price(r.price), 'purchaseFrom': f'楽天 {r.shop}'}

    for r in _read(purchases_dir / 'uniqlo.csv').itertuples():
        code = r.color.split()[0] if r.color else ''
        out[f'uniqlo:{r.order_date}:{r.product_no}:{code}'] = {
            'name': f'{r.item}（{r.color}、{r.size}）', 'purchaseDate': r.order_date[:10],
            'purchasePrice': 0.0, 'purchaseFrom': r.store or 'ユニクロ'}

    # mercari_web.csv（一回 backfill）を優先し、以後の分はメール由来
    for name in ('mercari.csv', 'mercari_web.csv'):
        df = _read(purchases_dir / name)
        if df.empty:
            continue
        for r in df[df['direction'] == 'buy'].itertuples():
            out[f'mercari:{r.item_id}'] = {
                'name': r.item, 'purchaseDate': r.date[:10],
                'purchasePrice': _price(r.price), 'purchaseFrom': 'メルカリ'}
    return out


# ---- Homebox 側の読み書き ----

def entity_key(entity: dict) -> str | None:
    for f in entity.get('fields') or []:
        if f.get('name') == KEY_FIELD and f.get('textValue'):
            return f['textValue']
    return None


def _update_body(entity: dict) -> dict:
    """GET の結果を PUT の body に戻す（PUT は全欄置き換えなので触らない欄も送り返す）"""
    keep = ('name', 'description', 'quantity', 'insured', 'archived', 'assetId',
            'serialNumber', 'modelNumber', 'manufacturer', 'lifetimeWarranty',
            'warrantyExpires', 'warrantyDetails', 'purchaseDate', 'purchaseFrom',
            'purchasePrice', 'soldDate', 'soldTo', 'soldPrice', 'soldNotes', 'notes',
            'syncChildEntityLocations')
    body = {k: entity.get(k) for k in keep if k in entity}
    body['id'] = entity['id']
    body['entityTypeId'] = (entity.get('entityType') or {}).get('id')
    if entity.get('parent'):
        body['parentId'] = entity['parent']['id']
    if entity.get('location'):
        body['locationId'] = entity['location']['id']
    body['tagIds'] = [t['id'] for t in entity.get('tags') or []]
    body['fields'] = [
        {k: f[k] for k in ('id', 'name', 'type', 'textValue', 'numberValue', 'booleanValue') if k in f}
        for f in entity.get('fields') or []]
    return body


def _item_type_id(client) -> str:
    return next(t['id'] for t in client.entity_types() if not t['isLocation'] and t['name'] == 'Item')


def load_items(client) -> dict[str, dict]:
    """key → entity（詳細）。archived も含む。key の重複は止める"""
    out: dict[str, dict] = {}
    for summary in client.list_entities(_item_type_id(client)):
        entity = client.get_entity(summary['id'])
        key = entity_key(entity) or f'homebox:{entity["id"]}'
        if key in out:
            raise InventoryError(f'Homebox に key={key} が2件ある（UI で片方を消す）')
        out[key] = entity
    return out


def _tag_ids(client, category: str, subcategory: str) -> list[str]:
    tags = client.tags()
    top = {t['name']: t for t in tags if t.get('parentId') in (None, '', NIL_ID)}
    ids = []
    if category:
        parent = top.get(category) or client.create_tag(category)
        ids.append(parent['id'])
        if subcategory:
            child = next((t for t in tags if t['name'] == subcategory
                          and t.get('parentId') == parent['id']), None)
            child = child or client.create_tag_under(subcategory, parent['id'])
            ids.append(child['id'])
    return ids


def add_item(client, key: str, category: str, subcategory: str = '', name: str = '',
             acquired_on: str = '', note: str = '', joined: dict | None = None) -> dict:
    """物を1つ足す。同じ key が既にあれば何もせず止める（二重登録しない）"""
    if key in load_items(client):
        raise InventoryError(f'{key} は登録済み')
    joined = joined or {}
    name = name or joined.get('name')
    if not name:
        raise InventoryError(f'{key} の品名が購入データに無い（--name で渡す）')
    created = client.create_entity({'name': fit_name(name), 'entityTypeId': _item_type_id(client),
                                    'quantity': 1})
    body = _update_body(client.get_entity(created['id']))
    body.update({
        'notes': note,
        'purchaseDate': acquired_on or joined.get('purchaseDate', ''),
        'purchasePrice': joined.get('purchasePrice', 0.0),
        'purchaseFrom': joined.get('purchaseFrom', ''),
        'tagIds': _tag_ids(client, category, subcategory),
    })
    body['fields'].append({'name': KEY_FIELD, 'type': 'text', 'textValue': key})
    return client.update_entity(created['id'], body)


def dispose_item(client, key: str, date: str, how: str = '') -> dict:
    """手放した印（archived + soldDate）。手放し方は soldNotes"""
    entity = load_items(client).get(key)
    if entity is None:
        raise InventoryError(f'{key} が Homebox に無い')
    body = _update_body(entity)
    body.update({'archived': True, 'soldDate': date, 'soldNotes': how or body.get('soldNotes', '')})
    return client.update_entity(entity['id'], body)


def _location(client, entity: dict) -> str:
    if not entity.get('parent'):
        return ''
    path = client.entity_path(entity['id'])
    return ' / '.join(p['name'] for p in path[:-1])


def _categories(entity: dict, parent_of: dict[str, str]) -> tuple[str, str]:
    """物に埋め込まれたタグには親が載らないので、タグ一覧から引いた parent_of（id → 親 id）で判定する"""
    names = {t['id']: t['name'] for t in entity.get('tags') or []}
    child = next((i for i in names if parent_of.get(i) in names), None)
    if child:
        return names[parent_of[child]], names[child]
    return ';'.join(sorted(names[i] for i in names if not parent_of.get(i))), ''


def export_rows(client) -> list[dict]:
    parent_of = {t['id']: t['parentId'] for t in client.tags()
                 if t.get('parentId') not in (None, '', NIL_ID)}
    rows = []
    for key, e in load_items(client).items():
        category, subcategory = _categories(e, parent_of)
        notes = e.get('notes') or ''
        if e.get('soldNotes'):
            notes = f'{notes} 手放し方: {e["soldNotes"]}'.strip()
        price = e.get('purchasePrice') or 0
        rows.append({
            'key': key, 'name': e['name'], 'category': category, 'subcategory': subcategory,
            'status': 'disposed' if e.get('archived') else 'owned',
            'location': _location(client, e),
            'acquired_on': e.get('purchaseDate') or '',
            'disposed_on': e.get('soldDate') or '',
            'purchase_price': f'{price:g}' if price else '',
            'purchase_from': e.get('purchaseFrom') or '',
            'note': notes,
        })
    return sorted(rows, key=lambda r: r['key'])


def write_csv(rows: list[dict], path: Path) -> None:
    """全上書き。0件は Homebox 側の故障として書かない（既存の台帳を空で潰さない）"""
    if not rows:
        raise InventoryError('Homebox から1件も取れなかった。items.csv は書き換えない')
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    tmp = path.with_suffix('.csv.tmp')
    tmp.write_text(buf.getvalue(), encoding='utf-8')
    tmp.replace(path)
