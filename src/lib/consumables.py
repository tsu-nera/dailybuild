"""
消耗品（補充する物）の購入履歴と次に買う頃（Grafana の consumables 画面）

データモデルは Grocy を借りている（docs/inventory.md）。正本は data/inventory/ の2本で、書くのは agent。
計算はここに置いて CSV に出す（表示の器を Notion などに替えても同じ CSV を流せるように）。

- consumables.csv: 品目（Grocy の product）。「プロテイン」「卵」のような一般名で、1品目1行、key は変えない。
  unit は量と値段を比べる単位（重さは kg、数える物は 個）
- purchase_rules.csv: 注文の行 → 品目（Grocy の product barcode）。amazon は match が ASIN（完全一致）、
  それ以外の source は match が商品名への正規表現。size は1注文1個あたりの量（品目の unit）で、
  空なら商品名の「1KG」「500g」「1,050g」から読む（unit が kg の品目だけ）
- stocktake.csv: 棚卸し（Grocy の stock の手動補正）。date の終わりに残っていた量（品目の unit）。
  在庫は減らす操作を持たず、棚卸し2回の間の「前回の量 + その間の購入 − 今回の量」から1日の使用量を出して推定する

月額（サブスクと同じ月割り）は、定期購入＝この台帳の品目について出す。使用量が出ている品目は
1日の使用量 × 30 × 直近の購入の単価、出ていない品目は直近365日（使い始めて1年未満なら使い始めから）の購入額の月割り。
購入2回未満・終了した品目は出さない
"""

import datetime as dt
import re
from pathlib import Path

import pandas as pd

ITEM_COLUMNS = ['key', 'name', 'category', 'location', 'unit', 'keep', 'subscription',
                'last_purchase', 'last_shop', 'purchases', 'interval_days', 'next_purchase', 'total_yen',
                'ended_on', 'stock_date', 'stock_counted', 'daily_use', 'stock_now', 'runs_out',
                'monthly_yen', 'annual_yen', 'monthly_basis']
PURCHASE_COLUMNS = ['date', 'key', 'name', 'shop', 'product', 'quantity', 'unit', 'yen', 'yen_per_unit']

_SIZE = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(kg|g)(?![a-z])', re.IGNORECASE)
_KG = {'kg': 1.0, 'g': 0.001}


def parse_size_kg(product: str) -> float | None:
    """商品名の最初の重さを kg で返す。読めなければ None"""
    m = _SIZE.search(product)
    return float(m.group(1).replace(',', '')) * _KG[m.group(2).lower()] if m else None


def _orders(source: str, shop, df: pd.DataFrame, item: str, yen) -> pd.DataFrame:
    return pd.DataFrame({
        'source': source, 'shop': shop, 'date': df['order_date'].str[:10], 'order_id': df['order_id'],
        'match': df['asin'] if source == 'amazon' else df[item], 'product': df[item],
        'count': df['quantity'].astype(float), 'yen': yen,
    })


def _amazon(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    df = df[df['status'] != 'Cancelled']
    return _orders('amazon', 'Amazon', df, 'item', df['price'].astype(float))


def _myprotein(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    return _orders('myprotein', 'マイプロテイン', df, 'item',
                   df['unit_price'].astype(float) * df['quantity'].astype(float))


def _rakuten(path: Path) -> pd.DataFrame:
    # 店は「楽天市場」でまとめ、モール内のショップ名は商品名の頭に残す
    df = pd.read_csv(path, dtype=str)
    df = df.assign(product=df['shop'] + ' ' + df['item'])
    return _orders('rakuten', '楽天市場', df, 'product', df['price'].astype(float)).assign(match=df['item'])


def _store(path: Path) -> pd.DataFrame:
    # 店頭で買った分。agent がレシートから書く（date, order_id, shop, item, quantity, price）
    df = pd.read_csv(path, dtype=str).rename(columns={'date': 'order_date'})
    return _orders('store', df['shop'], df, 'item', df['price'].astype(float))


READERS = {'amazon': _amazon, 'myprotein': _myprotein, 'rakuten': _rakuten, 'store': _store}


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
        size = float(s.size) if s.size else (parse_size_kg(r.product) if unit == 'kg' else None)
        if size is None:
            raise ValueError(f'{r.product} の量が読めない（purchase_rules.csv の size に書く）')
        rows.append({'date': r.date, 'key': s.key, 'shop': r.shop, 'product': r.product,
                     'quantity': r.count * size, 'unit': unit, 'yen': r.yen})
    return pd.DataFrame(rows, columns=['date', 'key', 'shop', 'product', 'quantity', 'unit', 'yen'])


def estimate_stock(counts: pd.DataFrame, bought: pd.DataFrame, today: dt.date) -> dict:
    """1品目の棚卸し（date, quantity）と購入（date, quantity）から今の在庫を推定する。

    使用量は最初と最後の棚卸しの間で出す（2回未満なら出さない）。その間の量が増えていたら購入の書き漏れなので
    使用量を出さない（0 や負で埋めると在庫が減らない品目を捏造する）。
    """
    none = dict.fromkeys(['stock_date', 'stock_counted', 'daily_use', 'stock_now', 'runs_out'])
    if counts.empty:
        return none
    counts = counts.sort_values('date', kind='stable')
    first, last = counts.iloc[0], counts.iloc[-1]
    d0, d1 = dt.date.fromisoformat(first['date']), dt.date.fromisoformat(last['date'])

    def bought_in(a: dt.date, b: dt.date) -> float:
        dates = bought['date'].map(dt.date.fromisoformat)
        return float(bought.loc[(dates > a) & (dates <= b), 'quantity'].sum())

    used = first['quantity'] + bought_in(d0, d1) - last['quantity']
    rate = used / (d1 - d0).days if d1 > d0 and used >= 0 else None
    out = {**none, 'stock_date': d1.isoformat(), 'stock_counted': round(last['quantity'], 3),
           'daily_use': round(rate, 4) if rate is not None else None}
    if rate:
        now = max(last['quantity'] + bought_in(d1, today) - rate * (today - d1).days, 0.0)
        out['stock_now'] = round(now, 3)
        out['runs_out'] = (today + dt.timedelta(days=int(now / rate))).isoformat()
    return out


def estimate_monthly(bought: pd.DataFrame, daily_use: float | None, today: dt.date) -> dict:
    """1品目の月額。使用量があれば消費から、無ければ直近365日の購入実額から出す"""
    none = dict.fromkeys(['monthly_yen', 'annual_yen', 'monthly_basis'])
    if daily_use is not None and len(bought):
        last = bought.iloc[-1]
        if last['quantity']:
            monthly, basis = daily_use * 30 * last['yen'] / last['quantity'], '使用量'
        else:
            return none
    else:
        # 購入1回では間隔が無く、今日買った品を12で割ると月数十円の捏造になる。使い始めて1年未満なら経過月数で割る
        if bought['date'].nunique() < 2:
            return none
        days = min(365, (today - dt.date.fromisoformat(bought['date'].min())).days)
        recent = bought[bought['date'] >= (today - dt.timedelta(days=days)).isoformat()]
        if recent.empty or days <= 0:
            return none
        monthly, basis = recent['yen'].sum() / days * 365 / 12, '購入実績'
    return {'monthly_yen': round(monthly), 'annual_yen': round(monthly * 12), 'monthly_basis': basis}


def build(items_csv: Path, rules_csv: Path, purchase_csvs: dict[str, Path], stocktake_csv: Path,
          today: dt.date) -> tuple[list[dict], list[dict]]:
    items = pd.read_csv(items_csv, dtype=str).fillna('')
    stocktake = pd.read_csv(stocktake_csv, dtype={'date': str, 'key': str, 'quantity': float})
    rules = pd.read_csv(rules_csv, dtype=str).fillna('')
    raw = pd.concat([READERS[name](path) for name, path in purchase_csvs.items()], ignore_index=True)
    bought = match_purchases(raw, rules, items).sort_values('date', kind='stable')
    name_of = items.set_index('key')['name'].to_dict()

    purchases = [{'date': r.date, 'key': r.key, 'name': name_of[r.key], 'shop': r.shop, 'product': r.product,
                  'quantity': round(r.quantity, 3), 'unit': r.unit, 'yen': round(r.yen),
                  'yen_per_unit': round(r.yen / r.quantity) if r.quantity else None}
                 for r in bought.itertuples()]

    rows = []
    for it in items.itertuples():
        mine = bought[bought['key'] == it.key]
        days = sorted({dt.date.fromisoformat(d) for d in mine['date']})
        # 次に買う頃 = 最後の購入日 + 購入間隔の中央値（同じ日の複数注文は1回）。2回未満・終了した品目は出さない
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        interval = int(pd.Series(gaps).median()) if gaps else None
        ended = it.ended_on or None
        rows.append({'key': it.key, 'name': it.name, 'category': it.category, 'location': it.location,
                     'unit': it.unit, 'keep': it.keep or None, 'subscription': it.subscription or None,
                     'last_purchase': days[-1].isoformat() if days else None,
                     'last_shop': mine['shop'].iloc[-1] if len(mine) else None,
                     'purchases': len(days), 'interval_days': interval,
                     'next_purchase': (days[-1] + dt.timedelta(days=interval)).isoformat()
                     if interval and not ended else None,
                     'total_yen': round(mine['yen'].sum()) if len(mine) else None, 'ended_on': ended,
                     **(stock := estimate_stock(stocktake[stocktake['key'] == it.key], mine, today)),
                     **(estimate_monthly(mine, stock['daily_use'], today) if not ended
                        else dict.fromkeys(['monthly_yen', 'annual_yen', 'monthly_basis']))})
    rows.sort(key=lambda r: (r['ended_on'] is not None, r['next_purchase'] or '9999', r['name']))
    return rows, purchases
