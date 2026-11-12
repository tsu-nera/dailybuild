"""お金の画面（Grafana の money/assets）の B/S: 金融資産（MoneyForward の資産推移）＋持ち物の中古相場

- 金融資産は data/mf/資産推移.csv の値をそのまま使い、列名だけ英字にする（補正しない。連携切れで構造的に過少）
- 持ち物は data/inventory/market.csv（homebox.py market が積む履歴）。その日に持っていた物について、
  その日以前の最新の中央値を合計する。中央値が空の行（相場にならなかった日）は前の値を消さない
- 相場の無い物は合計に入れない（買値でも0でも埋めない）。入った件数を goods_count に出す
- market.csv の最初の日より前は持ち物の欄と total を空にする（0にしない）
- 負債はデータが無いので列を作らない。経年劣化の補正もしない（SOLD 中央値に値下がりが入っている）
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

MF_COLUMNS = {'合計（円）': 'total_financial', '預金・現金（円）': 'cash', '投資信託（円）': 'funds',
              '暗号資産（円）': 'crypto', 'FX（円）': 'fx', 'ポイント（円）': 'points'}
ASSET_COLUMNS = ['date', *MF_COLUMNS.values(), 'goods_market', 'goods_count', 'total']
GOODS_COLUMNS = ['key', 'name', 'category', 'acquired_on', 'purchase_price', 'market_price', 'last_checked', 'diff']


def _num(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _int(value: float | None) -> int | None:
    return None if value is None else round(value)


def read_mf_assets(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, encoding='utf-8-sig')
    out = pd.DataFrame({'date': pd.to_datetime(df['日付'], format='%Y/%m/%d').dt.date})
    for src, dst in MF_COLUMNS.items():
        out[dst] = df[src].map(_num) if src in df.columns else None
    return out.sort_values('date').reset_index(drop=True)


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _prices(market: pd.DataFrame) -> dict[str, list[tuple[dt.date, float]]]:
    """key → [(日付, 中央値)]（日付順）。中央値が空の行は落とす"""
    out: dict[str, list[tuple[dt.date, float]]] = {}
    if market.empty:
        return out
    for r in market.sort_values('date').itertuples():
        price = _num(r.median)
        if price is not None:
            out.setdefault(r.key, []).append((dt.date.fromisoformat(r.date), price))
    return out


def _price_on(history: list[tuple[dt.date, float]], day: dt.date) -> float | None:
    found = None
    for d, price in history:
        if d > day:
            break
        found = price
    return found


def _held(item, day: dt.date) -> bool:
    acquired = dt.date.fromisoformat(item.acquired_on) if item.acquired_on else None
    disposed = dt.date.fromisoformat(item.disposed_on) if item.disposed_on else None
    return (acquired is None or acquired <= day) and (disposed is None or day < disposed)


def build(mf_assets_csv: Path, items_csv: Path, market_csv: Path) -> tuple[list[dict], list[dict]]:
    mf = read_mf_assets(mf_assets_csv)
    items = _read(items_csv)
    market = _read(market_csv)
    prices = _prices(market)
    first_check = min((dt.date.fromisoformat(d) for d in market['date']), default=None) if not market.empty else None

    rows = []
    for r in mf.itertuples(index=False):
        row = {'date': r.date.isoformat(), **{c: _int(getattr(r, c)) for c in MF_COLUMNS.values()},
               'goods_market': None, 'goods_count': None, 'total': None}
        if first_check is not None and r.date >= first_check:
            values = [p for it in items.itertuples() if _held(it, r.date)
                      and (p := _price_on(prices.get(it.key, []), r.date)) is not None]
            row['goods_market'] = _int(sum(values))
            row['goods_count'] = len(values)
            if row['total_financial'] is not None:
                row['total'] = row['total_financial'] + row['goods_market']
        rows.append(row)

    last_checked = {} if market.empty else market.groupby('key')['date'].max().to_dict()
    goods = []
    if not items.empty:
        for it in items[items['status'] == 'owned'].itertuples():
            history = prices.get(it.key, [])
            market_price = _int(history[-1][1]) if history else None
            purchase = _int(_num(it.purchase_price))
            goods.append({
                'key': it.key, 'name': it.name, 'category': it.category, 'acquired_on': it.acquired_on,
                'purchase_price': purchase, 'market_price': market_price,
                'last_checked': last_checked.get(it.key, ''),
                'diff': market_price - purchase if market_price is not None and purchase is not None else None,
            })
    goods.sort(key=lambda g: (g['market_price'] is None, -(g['market_price'] or 0), g['key']))
    return rows, goods
