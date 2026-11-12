"""持ち物の正本は Homebox（#263 で採用）。items.csv はここから書き出す生成物

- 物と items.csv の行は custom field `key` で対応する（`amazon:<注文番号>:<ASIN>` など）。
  UI で足して key の無い物は `homebox:<id>` として書き出す
- カテゴリは親タグ、サブカテゴリはその子タグ
- 手放した物は archived + soldDate
- 手放すと決めた物はメンテナンス記録「売却」「破棄」（予定日＝決めた日。期日は Todoist が持つ）。
  手放したら完了日を入れて閉じる。売値はメンテナンスの費用でなく soldPrice（費用は合計されるため）
- 中古相場は任意の custom field `中古相場`（最新の1つ）。number 型は PUT が 500 になるので text に円の整数を入れる。履歴はメモ末尾の「相場 YYYY-MM-DD: …」行に積む。
  全部には付けない実験（2026-11-12〜）。定期取得の検索条件は custom field `相場検索`（書式は lib.inventory.market）
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pandas as pd
import requests

KEY_FIELD = 'key'
MARKET_FIELD = '中古相場'
QUERY_FIELD = '相場検索'
DISPOSAL_KINDS = ('売却', '破棄')
NAME_MAX_BYTES = 255  # ent schema の MaxLen(255)。len は UTF-8 のバイト数で数える
NIL_ID = '00000000-0000-0000-0000-000000000000'
COLUMNS = ['key', 'name', 'category', 'subcategory', 'status', 'location',
           'acquired_on', 'disposed_on', 'purchase_price', 'purchase_from', 'market_price', 'note']


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
                    'purchasePrice': _price(r.price), 'purchaseFrom': 'Amazon',
                    'url': f'https://www.amazon.co.jp/dp/{r.asin}'}

    rakuten = _read(purchases_dir / 'rakuten.csv')
    if not rakuten.empty:
        for order_id, g in rakuten.groupby('order_id', sort=False):
            for n, r in enumerate(g.itertuples(), start=1):
                out[f'rakuten:{order_id}:{n}'] = {
                    'name': r.item, 'purchaseDate': r.order_date[:10],
                    'purchasePrice': _price(r.price), 'purchaseFrom': f'楽天 {r.shop}',
                    'url': r.item_url}

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
                'purchasePrice': _price(r.price), 'purchaseFrom': 'メルカリ',
                'url': f'https://jp.mercari.com/item/{r.item_id}'}
    return out


# ---- Homebox 側の読み書き ----

def entity_key(entity: dict) -> str | None:
    for f in entity.get('fields') or []:
        if f.get('name') == KEY_FIELD and f.get('textValue'):
            return f['textValue']
    return None


def field_text(entity: dict, name: str) -> str:
    for f in entity.get('fields') or []:
        if f.get('name') == name:
            return f.get('textValue') or ''
    return ''


def market_price(entity: dict) -> float:
    return _price(field_text(entity, MARKET_FIELD))


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


def url_alive(url: str) -> bool:
    """商品ページが開けるか。楽天は店が下げると、メルカリは出品者が取引後に消すと 404 になる
    （2026-11-11: 2019〜2020 の購入で楽天1件・メルカリ1件が 404、2021 のメルカリは生きていた）"""
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15, allow_redirects=True)
    except requests.RequestException:
        return False
    return r.status_code == 200


def notes_with_link(note: str, url: str, source: str) -> str:
    """Homebox のメモは markdown で描画されるので、商品ページはリンクの1行で足す"""
    if not url:
        return note
    link = f'[商品ページ（{source or "リンク"}）]({url})'
    return f'{note}\n\n{link}' if note else link


def add_item(client, key: str, category: str, subcategory: str = '', name: str = '',
             acquired_on: str = '', note: str = '', joined: dict | None = None,
             url: str = '', alive=url_alive, price: float = 0.0, purchase_from: str = '') -> dict:
    """物を1つ足す。同じ key が既にあれば何もせず止める（二重登録しない）"""
    if key in load_items(client):
        raise InventoryError(f'{key} は登録済み')
    joined = joined or {}
    name = name or joined.get('name')
    if not name:
        raise InventoryError(f'{key} の品名が購入データに無い（--name で渡す）')
    # 渡された url は本人が確かめたものとして信じる。購入データから作った url は開けるときだけ付ける
    link = url or (joined.get('url', '') if joined.get('url') and alive(joined['url']) else '')
    created = client.create_entity({'name': fit_name(name), 'entityTypeId': _item_type_id(client),
                                    'quantity': 1})
    body = _update_body(client.get_entity(created['id']))
    body.update({
        'notes': notes_with_link(note, link, joined.get('purchaseFrom', '')),
        'purchaseDate': acquired_on or joined.get('purchaseDate', ''),
        'purchasePrice': price or joined.get('purchasePrice', 0.0),
        'purchaseFrom': purchase_from or joined.get('purchaseFrom', ''),
        'tagIds': _tag_ids(client, category, subcategory),
    })
    body['fields'].append({'name': KEY_FIELD, 'type': 'text', 'textValue': key})
    return client.update_entity(created['id'], body)


def _set_field(body: dict, name: str, text: str) -> None:
    field = next((f for f in body['fields'] if f['name'] == name), None)
    if field is None:
        field = {'name': name, 'type': 'text'}
        body['fields'].append(field)
    field['textValue'] = text


def _owned(client, key: str) -> dict:
    entity = load_items(client).get(key)
    if entity is None:
        raise InventoryError(f'{key} が Homebox に無い')
    return entity


def set_market_price(client, key: str, price: float, date: str, source: str) -> dict:
    """中古相場を custom field に入れ（上書き）、メモ末尾に履歴の1行を積む。同じ日の行は差し替える（再実行で積まない）"""
    entity = _owned(client, key)
    body = _update_body(entity)
    _set_field(body, MARKET_FIELD, f'{price:.0f}')
    prefix = f'相場 {date}: '
    kept = [b for b in (body.get('notes') or '').split('\n\n') if b and not b.startswith(prefix)]
    body['notes'] = '\n\n'.join(kept + [f'{prefix}{source} {price:,.0f}円'])
    return client.update_entity(entity['id'], body)


def set_market_query(client, key: str, query: str) -> dict:
    """定期取得の検索条件（custom field `相場検索`）。空文字で外す"""
    from lib.inventory.market import parse_query
    if query:
        try:
            parse_query(query)  # 書式が壊れていれば取得の日でなくここで止める
        except ValueError as e:
            raise InventoryError(f'相場検索の書式: {e}') from e
    entity = _owned(client, key)
    body = _update_body(entity)
    _set_field(body, QUERY_FIELD, query)
    return client.update_entity(entity['id'], body)


def market_targets(client) -> dict[str, tuple[dict, str]]:
    """key → (entity, 検索条件)。手放した物は除く"""
    return {k: (e, q) for k, e in load_items(client).items()
            if not e.get('archived') and (q := field_text(e, QUERY_FIELD))}


def mercari_sales(purchases_dir: Path) -> dict[str, dict]:
    """item_id → {date, price}。取引日時を持つ mercari_web.csv を優先し、以後の分はメール由来"""
    out: dict[str, dict] = {}
    for name in ('mercari.csv', 'mercari_web.csv'):
        df = _read(purchases_dir / name)
        if df.empty:
            continue
        for r in df[df['direction'] == 'sell'].itertuples():
            out[r.item_id] = {'date': r.date[:10], 'price': _price(r.price)}
    return out


def dispose_item(client, key: str, date: str, how: str = '',
                 sold_price: float = 0.0, sold_to: str = '') -> dict:
    """手放した印（archived + soldDate）。手放し方は soldNotes、売ったなら売値と売り先も"""
    entity = load_items(client).get(key)
    if entity is None:
        raise InventoryError(f'{key} が Homebox に無い')
    body = _update_body(entity)
    body.update({'archived': True, 'soldDate': date, 'soldNotes': how or body.get('soldNotes', '')})
    if sold_price:
        body['soldPrice'] = sold_price
    if sold_to:
        body['soldTo'] = sold_to
    updated = client.update_entity(entity['id'], body)
    for m in client.maintenance(entity['id']):
        if m['name'] in DISPOSAL_KINDS and not m.get('completedDate'):
            client.update_maintenance(m['id'], {
                k: m.get(k, '') for k in ('name', 'description', 'cost', 'scheduledDate')
            } | {'completedDate': date})
    return updated


def plan_disposal(client, key: str, kind: str, decided_on: str) -> dict:
    """手放すと決めた印。同じ種類の未完了があれば作らない"""
    if kind not in DISPOSAL_KINDS:
        raise InventoryError(f'種類は {"・".join(DISPOSAL_KINDS)} のどれか')
    entity = load_items(client).get(key)
    if entity is None:
        raise InventoryError(f'{key} が Homebox に無い')
    for m in client.maintenance(entity['id']):
        if m['name'] == kind and not m.get('completedDate'):
            return m
    return client.create_maintenance(entity['id'], {
        'name': kind, 'scheduledDate': decided_on, 'description': '', 'cost': '0'})


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
        market = market_price(e)
        rows.append({
            'key': key, 'name': e['name'], 'category': category, 'subcategory': subcategory,
            'status': 'disposed' if e.get('archived') else 'owned',
            'location': _location(client, e),
            'acquired_on': e.get('purchaseDate') or '',
            'disposed_on': e.get('soldDate') or '',
            'purchase_price': f'{price:g}' if price else '',
            'purchase_from': e.get('purchaseFrom') or '',
            'market_price': f'{market:g}' if market else '',
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


# ---- 場所の解決と移動・検索 ----

def location_paths(client) -> dict[str, str]:
    """場所の id → 根からの経路（'メイン / 机'）"""
    loc_type = next(t['id'] for t in client.entity_types() if t['isLocation'])
    summaries = {s['id']: s for s in client.list_entities(loc_type)}

    def path(sid: str) -> str:
        s = summaries[sid]
        parent = (s.get('parent') or {}).get('id')
        return f'{path(parent)} / {s["name"]}' if parent in summaries else s['name']

    return {sid: path(sid) for sid in summaries}


def resolve_location(client, name: str) -> str:
    """経路（'メイン / 机'）か末端の名前（'机'）から場所の id を引く。曖昧・不在は止める"""
    paths = location_paths(client)
    hits = [sid for sid, p in paths.items() if p == name] or \
           [sid for sid, p in paths.items() if p.split(' / ')[-1] == name]
    if not hits:
        raise InventoryError(f'場所「{name}」が無い。ある場所: {", ".join(sorted(paths.values()))}')
    if len(hits) > 1:
        raise InventoryError(f'場所「{name}」が複数ある（経路で指定する）: {", ".join(paths[h] for h in hits)}')
    return hits[0]


def move_item(client, key: str, location: str) -> dict:
    entity = load_items(client).get(key)
    if entity is None:
        raise InventoryError(f'{key} が Homebox に無い')
    body = _update_body(entity)
    body['parentId'] = resolve_location(client, location)
    return client.update_entity(entity['id'], body)


def find_rows(rows: list[dict], query: str = '', location: str = '', tag: str = '',
              include_disposed: bool = False) -> list[dict]:
    """export_rows の結果を絞る。query は key・品名・メモの部分一致、location は経路の部分一致"""
    out = []
    for r in rows:
        if r['status'] == 'disposed' and not include_disposed:
            continue
        if query and not any(query.lower() in r[c].lower() for c in ('key', 'name', 'note')):
            continue
        if location and location not in r['location']:
            continue
        if tag and tag not in (r['category'].split(';') + [r['subcategory']]):
            continue
        out.append(r)
    return out
