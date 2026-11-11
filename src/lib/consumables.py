"""
消耗品の在庫と購入履歴（Grafana の consumables 画面）

正本は data/consumables/ の2本で、書くのは agent（本人は Grafana で見るだけ）。

- items.csv: 品目。stock は checked_on の日に確かめた在庫、daily_use は1日に使う量（品目の unit）
- sources.csv: 購入データの行を品目に結びつける規則。amazon は key が ASIN（完全一致）、
  それ以外の source は key が商品名への正規表現。size は1注文1個あたりの量（品目の unit）で、
  空なら商品名の「1KG」「500g」から読む

在庫は数えずに推定する: stock + checked_on より後の購入 − daily_use × 経過日数。
daily_use が空の品目は減らさない（「使った」は agent が stock と checked_on を書き直す）。
"""

import datetime as dt
import re
from pathlib import Path

import pandas as pd

ITEM_COLUMNS = ['item_id', 'name', 'category', 'location', 'shop', 'unit', 'stock_est', 'min_stock',
                'daily_use', 'days_left', 'status', 'checked_on', 'last_purchase', 'purchases', 'total_yen']
PURCHASE_COLUMNS = ['date', 'item_id', 'name', 'shop', 'product', 'quantity', 'unit', 'yen', 'yen_per_kg']

SHOP = {'amazon': 'Amazon', 'myprotein': 'マイプロテイン'}
_SIZE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|g)(?![a-z])', re.IGNORECASE)
_TO_KG = {'kg': 1.0, 'g': 0.001}


def parse_size(product: str, unit: str) -> float | None:
    """商品名の最初の重さを品目の unit（kg / g）で返す。読めなければ None"""
    m = _SIZE.search(product)
    if not m or unit not in _TO_KG:
        return None
    kg = float(m.group(1)) * _TO_KG[m.group(2).lower()]
    return kg / _TO_KG[unit]


def _amazon(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df = df[df['status'] != 'Cancelled']
    return pd.DataFrame({
        'source': 'amazon', 'date': df['order_date'].str[:10], 'order_id': df['order_id'],
        'match_key': df['asin'], 'product': df['item'],
        'count': df['quantity'].astype(float), 'yen': df['price'].astype(float),
    })


def _myprotein(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    return pd.DataFrame({
        'source': 'myprotein', 'date': df['order_date'].str[:10], 'order_id': df['order_id'],
        'match_key': df['item'], 'product': df['item'],
        'count': df['quantity'].astype(float),
        'yen': df['unit_price'].astype(float) * df['quantity'].astype(float),
    })


READERS = {'amazon': _amazon, 'myprotein': _myprotein}


def match_purchases(raw: pd.DataFrame, sources: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """購入の行を品目に結びつける。1行が2つの規則に当たったら例外（二重に数えない）"""
    unit_of = items.set_index('item_id')['unit'].to_dict()
    rows = []
    for r in raw.itertuples():
        hits = []
        for s in sources[sources['source'] == r.source].itertuples():
            hit = r.match_key == s.key if r.source == 'amazon' else re.search(s.key, r.match_key)
            if hit:
                hits.append(s)
        if len(hits) > 1:
            raise ValueError(f'{r.source} {r.order_id} {r.product} が複数の品目に当たる: {[h.item_id for h in hits]}')
        if not hits:
            continue
        s = hits[0]
        unit = unit_of[s.item_id]
        size = float(s.size) if pd.notna(s.size) and s.size != '' else parse_size(r.product, unit)
        if size is None:
            raise ValueError(f'{r.product} の量が読めない（sources.csv の size に書く）')
        rows.append({'date': r.date, 'item_id': s.item_id, 'shop': SHOP.get(r.source, r.source),
                     'product': r.product, 'quantity': r.count * size, 'unit': unit, 'yen': r.yen})
    return pd.DataFrame(rows, columns=['date', 'item_id', 'shop', 'product', 'quantity', 'unit', 'yen'])


def _num(v) -> float | None:
    return None if v is None or v == '' or pd.isna(v) else float(v)


def build(items_csv: Path, sources_csv: Path, purchase_csvs: dict[str, Path],
          today: dt.date) -> tuple[list[dict], list[dict]]:
    items = pd.read_csv(items_csv, dtype=str).fillna('')
    sources = pd.read_csv(sources_csv, dtype=str).fillna('')
    raw = pd.concat([READERS[name](path) for name, path in purchase_csvs.items()], ignore_index=True)
    bought = match_purchases(raw, sources, items).sort_values('date')
    name_of = items.set_index('item_id')['name'].to_dict()

    purchases = []
    for r in bought.itertuples():
        per_kg = r.yen / (r.quantity * _TO_KG[r.unit]) if r.unit in _TO_KG and r.quantity else None
        purchases.append({'date': r.date, 'item_id': r.item_id, 'name': name_of[r.item_id], 'shop': r.shop,
                          'product': r.product, 'quantity': round(r.quantity, 3), 'unit': r.unit,
                          'yen': round(r.yen), 'yen_per_kg': round(per_kg) if per_kg else None})

    rows = []
    for it in items.itertuples():
        mine = bought[bought['item_id'] == it.item_id]
        stock, use, min_stock = _num(it.stock), _num(it.daily_use), _num(it.min_stock)
        est = days_left = None
        if stock is not None and it.checked_on:
            checked = dt.date.fromisoformat(it.checked_on)
            est = stock + mine[mine['date'] > it.checked_on]['quantity'].sum()
            if use:
                est = max(est - use * (today - checked).days, 0.0)
                days_left = round(est / use, 1)
            est = round(est, 3)
        if est is None:
            status = '未確認'
        elif min_stock is not None and est < min_stock:
            status = '要補充'
        else:
            status = ''
        rows.append({'item_id': it.item_id, 'name': it.name, 'category': it.category, 'location': it.location,
                     'shop': it.shop, 'unit': it.unit, 'stock_est': est, 'min_stock': min_stock,
                     'daily_use': use, 'days_left': days_left, 'status': status,
                     'checked_on': it.checked_on or None,
                     'last_purchase': mine['date'].max() if len(mine) else None,
                     'purchases': len(mine), 'total_yen': round(mine['yen'].sum()) if len(mine) else None})
    order = {'要補充': 0, '未確認': 2, '': 1}
    rows.sort(key=lambda r: (order[r['status']], r['days_left'] if r['days_left'] is not None else 1e9, r['name']))
    return rows, purchases
