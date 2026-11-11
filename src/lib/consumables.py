"""
消耗品（補充する物）の購入履歴と次に買う頃（Grafana の consumables 画面）

正本は data/inventory/ の2本で、書くのは agent。表示は Grafana だが、計算はここに置いて
CSV に出す（表示の器を Notion などに替えても同じ CSV を流せるように）。

- consumables.csv: 補充する品目（1品目1行、key は変えない）。keep は持っておく数、subscription は定期購入の頻度、ended_on はもう買わないと決めた日（行は消さず、次に買う頃を出さない）
- purchase_rules.csv: 店の注文の行を品目に結びつける規則。amazon は match が ASIN（完全一致）、
  それ以外の source は match が商品名への正規表現。size は1注文1個あたりの量（品目の unit）で、
  空なら商品名の「1KG」「500g」から読む

所持品（買い替える物）は同じディレクトリの items.csv（Homebox の写し）で、ここでは扱わない。
"""

import datetime as dt
import re
from pathlib import Path

import pandas as pd

ITEM_COLUMNS = ['key', 'name', 'category', 'location', 'shop', 'unit', 'keep', 'subscription',
                'last_purchase', 'purchases', 'interval_days', 'next_purchase', 'total_yen', 'ended_on']
PURCHASE_COLUMNS = ['date', 'key', 'name', 'shop', 'product', 'quantity', 'unit', 'yen', 'yen_per_kg']

SHOP = {'amazon': 'Amazon', 'myprotein': 'マイプロテイン'}
_SIZE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|g)(?![a-z])', re.IGNORECASE)
_TO_KG = {'kg': 1.0, 'g': 0.001}


def parse_size(product: str, unit: str) -> float | None:
    """商品名の最初の重さを品目の unit（kg / g）で返す。読めなければ None"""
    m = _SIZE.search(product)
    if not m or unit not in _TO_KG:
        return None
    return float(m.group(1)) * _TO_KG[m.group(2).lower()] / _TO_KG[unit]


def _amazon(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df = df[df['status'] != 'Cancelled']
    return pd.DataFrame({
        'source': 'amazon', 'date': df['order_date'].str[:10], 'order_id': df['order_id'],
        'match': df['asin'], 'product': df['item'],
        'count': df['quantity'].astype(float), 'yen': df['price'].astype(float),
    })


def _myprotein(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    return pd.DataFrame({
        'source': 'myprotein', 'date': df['order_date'].str[:10], 'order_id': df['order_id'],
        'match': df['item'], 'product': df['item'],
        'count': df['quantity'].astype(float),
        'yen': df['unit_price'].astype(float) * df['quantity'].astype(float),
    })


READERS = {'amazon': _amazon, 'myprotein': _myprotein}


def match_purchases(raw: pd.DataFrame, rules: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """注文の行を品目に結びつける。1行が2つの規則に当たったら例外（二重に数えない）"""
    unit_of = items.set_index('key')['unit'].to_dict()
    rows = []
    for r in raw.itertuples():
        hits = [s for s in rules[rules['source'] == r.source].itertuples()
                if (r.match == s.match if r.source == 'amazon' else re.search(s.match, r.match))]
        if len(hits) > 1:
            raise ValueError(f'{r.source} {r.order_id} {r.product} が複数の品目に当たる: {[h.key for h in hits]}')
        if not hits:
            continue
        s = hits[0]
        unit = unit_of[s.key]
        size = float(s.size) if s.size else parse_size(r.product, unit)
        if size is None:
            raise ValueError(f'{r.product} の量が読めない（purchase_rules.csv の size に書く）')
        rows.append({'date': r.date, 'key': s.key, 'shop': SHOP.get(r.source, r.source),
                     'product': r.product, 'quantity': r.count * size, 'unit': unit, 'yen': r.yen})
    return pd.DataFrame(rows, columns=['date', 'key', 'shop', 'product', 'quantity', 'unit', 'yen'])


def build(items_csv: Path, rules_csv: Path, purchase_csvs: dict[str, Path]) -> tuple[list[dict], list[dict]]:
    items = pd.read_csv(items_csv, dtype=str).fillna('')
    rules = pd.read_csv(rules_csv, dtype=str).fillna('')
    raw = pd.concat([READERS[name](path) for name, path in purchase_csvs.items()], ignore_index=True)
    bought = match_purchases(raw, rules, items).sort_values('date')
    name_of = items.set_index('key')['name'].to_dict()

    purchases = []
    for r in bought.itertuples():
        per_kg = r.yen / (r.quantity * _TO_KG[r.unit]) if r.unit in _TO_KG and r.quantity else None
        purchases.append({'date': r.date, 'key': r.key, 'name': name_of[r.key], 'shop': r.shop,
                          'product': r.product, 'quantity': round(r.quantity, 3), 'unit': r.unit,
                          'yen': round(r.yen), 'yen_per_kg': round(per_kg) if per_kg else None})

    rows = []
    for it in items.itertuples():
        mine = bought[bought['key'] == it.key]
        days = sorted({dt.date.fromisoformat(d) for d in mine['date']})
        # 次に買う頃 = 最後の購入日 + 購入間隔の中央値（同じ日の複数注文は1回）。2回未満は出さない
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        interval = int(pd.Series(gaps).median()) if gaps else None
        ended = getattr(it, 'ended_on', '') or None
        rows.append({'key': it.key, 'name': it.name, 'category': it.category, 'location': it.location,
                     'shop': it.shop, 'unit': it.unit, 'keep': it.keep or None,
                     'subscription': it.subscription or None,
                     'last_purchase': days[-1].isoformat() if days else None, 'purchases': len(days),
                     'interval_days': interval,
                     'next_purchase': (days[-1] + dt.timedelta(days=interval)).isoformat()
                     if interval and not ended else None,
                     'total_yen': round(mine['yen'].sum()) if len(mine) else None, 'ended_on': ended})
    rows.sort(key=lambda r: (r['ended_on'] is not None, r['next_purchase'] or '9999', r['name']))
    return rows, purchases
