"""items.csv → Homebox の一方向同期（#263 試用）

試用中の正本は items.csv。Homebox 側の物は custom field `key` で items.csv の行と対応させ、
再実行で二重に作らない。

- 品名・購入日・価格・購入先は data/purchases/ から join する（items.csv に写さない）
- 上書きするのは下の MANAGED の欄だけ。UI で付けた場所・写真・説明などは残す。タグは足すだけで外さない
- 品名・メモは items.csv 側が勝つ（UI で直しても次の push で戻る）。直すなら items.csv を直す
- items.csv に無い物は消さない（UI で足した物を巻き込まないため）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

KEY_FIELD = 'key'
MANAGED = ('name', 'notes', 'purchaseDate', 'purchasePrice', 'purchaseFrom',
           'archived', 'soldDate', 'tagIds')


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _date(value: str) -> str:
    return value[:10] if value else ''


NAME_MAX_BYTES = 255  # Homebox の ent schema は MaxLen(255)。len は UTF-8 のバイト数で数える


def _fit_name(name: str) -> str:
    """Amazon の商品名は 255 バイトを超えて 500 になる。文字の途中で切らずに縮める"""
    if len(name.encode()) <= NAME_MAX_BYTES:
        return name
    out = name
    while len((out + '…').encode()) > NAME_MAX_BYTES:
        out = out[:-1]
    return out + '…'


def _price(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def purchase_lookup(purchases_dir: Path) -> dict[str, dict]:
    """items.csv の key → {name, purchaseDate, purchasePrice, purchaseFrom}"""
    out: dict[str, dict] = {}

    amazon = _read(purchases_dir / 'amazon.csv')
    gmail = _read(purchases_dir / 'gmail.csv')
    # gmail.csv は開示データより新しい注文。開示データを優先する
    for df, src in ((gmail, 'Amazon'), (amazon, 'Amazon')):
        if df.empty:
            continue
        if 'shop' in df.columns:
            df = df[df['shop'].str.lower().str.contains('amazon')]
        for r in df.itertuples():
            if not r.asin:
                continue
            out[f'amazon:{r.order_id}:{r.asin}'] = {
                'name': r.item, 'purchaseDate': _date(r.order_date),
                'purchasePrice': _price(r.price), 'purchaseFrom': src}

    rakuten = _read(purchases_dir / 'rakuten.csv')
    if not rakuten.empty:
        for order_id, g in rakuten.groupby('order_id', sort=False):
            for n, r in enumerate(g.itertuples(), start=1):
                out[f'rakuten:{order_id}:{n}'] = {
                    'name': r.item, 'purchaseDate': _date(r.order_date),
                    'purchasePrice': _price(r.price), 'purchaseFrom': f'楽天 {r.shop}'}

    uniqlo = _read(purchases_dir / 'uniqlo.csv')
    for r in uniqlo.itertuples():
        code = r.color.split()[0] if r.color else ''
        out[f'uniqlo:{r.order_date}:{r.product_no}:{code}'] = {
            'name': f'{r.item}（{r.color}、{r.size}）', 'purchaseDate': _date(r.order_date),
            'purchasePrice': 0.0, 'purchaseFrom': r.store or 'ユニクロ'}

    # mercari_web.csv（Web から一回 backfill）を優先し、以後の分はメール由来
    for name in ('mercari.csv', 'mercari_web.csv'):
        df = _read(purchases_dir / name)
        if df.empty:
            continue
        for r in df[df['direction'] == 'buy'].itertuples():
            out[f'mercari:{r.item_id}'] = {
                'name': r.item, 'purchaseDate': _date(r.date),
                'purchasePrice': _price(r.price), 'purchaseFrom': 'メルカリ'}
    return out


@dataclass
class Desired:
    key: str
    values: dict
    tags: list[str] = field(default_factory=list)


def desired_entities(items: pd.DataFrame, lookup: dict[str, dict]) -> list[Desired]:
    out = []
    for r in items.itertuples():
        joined = lookup.get(r.key, {})
        values = {
            # items.csv の name は join できない行か、購入データの品名より良い名前を付けた行
            'name': _fit_name(r.name or joined.get('name') or r.key),
            'notes': r.note,
            'purchaseDate': r.acquired_on or joined.get('purchaseDate', ''),
            'purchasePrice': joined.get('purchasePrice', 0.0),
            'purchaseFrom': joined.get('purchaseFrom', ''),
            'archived': r.status == 'disposed',
            'soldDate': r.disposed_on,
        }
        tags = [t for t in (r.category, r.subcategory) if t]
        out.append(Desired(r.key, values, tags))
    return out


def _entity_key(entity: dict) -> str | None:
    for f in entity.get('fields') or []:
        if f.get('name') == KEY_FIELD:
            return f.get('textValue') or None
    return None


def _update_body(entity: dict) -> dict:
    """GET の結果を PUT の body に戻す（PUT は全欄置き換えなので管理外の欄も送り返す）"""
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


@dataclass
class PushResult:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    unmanaged: list[str] = field(default_factory=list)  # Homebox にだけある物（消さない）


def push(client, desired: list[Desired], dry_run: bool = False) -> PushResult:
    types = client.entity_types()
    item_type = next(t['id'] for t in types if not t['isLocation'] and t['name'] == 'Item')

    existing: dict[str, dict] = {}
    result = PushResult()
    for summary in client.list_entities(item_type):
        entity = client.get_entity(summary['id'])
        key = _entity_key(entity)
        if key is None:
            result.unmanaged.append(entity['name'])
        elif key in existing:
            raise RuntimeError(f'Homebox に key={key} が2件ある（手で片方を消す）')
        else:
            existing[key] = entity

    tag_ids = {t['name']: t['id'] for t in client.tags()}

    def tag_id(name: str) -> str:
        if name not in tag_ids:
            tag_ids[name] = 'dry-run' if dry_run else client.create_tag(name)['id']
        return tag_ids[name]

    for d in desired:
        ours = {tag_id(t) for t in d.tags}
        entity = existing.get(d.key)
        have = {t['id'] for t in (entity or {}).get('tags') or []}
        want = dict(d.values, tagIds=sorted(ours | have))
        if entity is None:
            result.created.append(d.key)
            if dry_run:
                continue
            entity = client.create_entity({'name': want['name'], 'entityTypeId': item_type, 'quantity': 1})
            entity = client.get_entity(entity['id'])
            body = _update_body(entity)
            body['fields'].append({'name': KEY_FIELD, 'type': 'text', 'textValue': d.key})
        else:
            body = _update_body(entity)
            current = {k: body.get(k) for k in MANAGED}
            current['tagIds'] = sorted(current['tagIds'] or [])
            if current == want:
                result.unchanged.append(d.key)
                continue
            result.updated.append(d.key)
            if dry_run:
                continue
        body.update(want)
        client.update_entity(entity['id'], body)
    return result
