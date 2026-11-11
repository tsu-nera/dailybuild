#!/usr/bin/env python
# coding: utf-8
"""
Grocy（消耗品の補充管理の試用、#264）へ購入履歴を流し込む

data/purchases/amazon.csv から、2回以上買った物のうち消耗品と判定した ASIN（CONSUMABLES）を
商品として登録し、注文ごとに入庫する。キーは商品が userfield `asin`、入庫が stock_log の note
（`amazon:<注文番号>:<ASIN>`）で、同じ投入を何度流しても増えない。

入庫した分は同じ実行の中ですぐ消費する。過去の購入をそのまま在庫に残すと 2017 年の MCT オイルが
27本ある状態になる（在庫の捏造）。今の在庫は分からないので 0 から始め、本人が UI の棚卸しで付ける。
再実行で消費するのは新しく入庫した行だけなので、棚卸しで付けた在庫は消えない。

Usage:
    python scripts/grocy.py load              # 投入（冪等）
    python scripts/grocy.py load --dry-run    # 何を入れるかだけ出す

接続先は .env の GROCY_URL / GROCY_API_KEY（API キーは Grocy の 設定 → API キーの管理 で発行）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
from dataclasses import dataclass

import pandas as pd
import requests

from lib.utils.env import require_env
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).parent.parent
AMAZON_CSV = BASE_DIR / 'data' / 'purchases' / 'amazon.csv'

LOCATION = '自宅'
SHOPPING_LOCATION = 'Amazon'
QUANTITY_UNIT_ID = 2  # 初期データの「ピース」
NEVER_DUE = '2999-12-31'  # Grocy の「期限なし」

# ASIN -> (商品名, 1注文1個あたりの入数)。2回以上買った 35 品目から、使えば無くなる物だけを人手で選んだ。
# 本・ソフト・電子機器・服・自転車部品の取り付け物は外した（買い替えであって補充ではない）
CONSUMABLES: dict[str, tuple[str, int]] = {
    'B00AA57WDI': ('MCTオイル 450g', 1),
    'B00L8IZ1E8': ('グラスフェッドバター 無塩 250g', 1),
    'B01EW50RNS': ('グラスフェッドバター 無塩 250g ×2', 1),
    'B01C5JMVYQ': ('インスタントコーヒー（マウントハーゲン）100g', 1),
    'B001EHK01M': ('ワイプオール X70（50枚）', 1),
    'B00260NNDI': ('重曹 2kg', 1),
    'B001NMTIEI': ('ブレーキシュー M70T4', 1),
    'B00BWZXIAQ': ('チェーンディグリーザー 500ml', 1),
    'B000H83Q4W': ('洗顔（ラボシリーズ）93g', 1),
    'B00E95CD4S': ('BCAA（Xtend）マンゴー', 1),
    'B00IJT841G': ('アイブロウペンシル', 1),
    'B0798GNT1T': ('除毛クリーム（Veet Men）105g', 1),
}


@dataclass(frozen=True)
class Purchase:
    key: str
    asin: str
    date: str
    amount: int
    unit_price: float


def load_purchases(path: Path) -> list[Purchase]:
    df = pd.read_csv(path, dtype=str)
    df = df[(df['status'] != 'Cancelled') & df['asin'].isin(CONSUMABLES)]
    rows = []
    for r in df.itertuples():
        quantity = int(r.quantity) * CONSUMABLES[r.asin][1]
        rows.append(Purchase(
            key=f'amazon:{r.order_id}:{r.asin}',
            asin=r.asin,
            date=r.order_date[:10],
            amount=quantity,
            unit_price=float(r.price) / quantity,
        ))
    # 同じ注文に同じ ASIN が2行あると key が衝突し、2行目を入庫済みと誤認する
    keys = [p.key for p in rows]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise ValueError(f'注文番号+ASIN が重複しています: {sorted(dup)}')
    return sorted(rows, key=lambda p: p.date)


class Grocy:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/') + '/api'
        self.session = requests.Session()
        self.session.headers['GROCY-API-KEY'] = api_key

    def request(self, method: str, path: str, **kwargs):
        res = self.session.request(method, self.url + path, timeout=30, **kwargs)
        if not res.ok:
            raise RuntimeError(f'{method} {path}: {res.status_code} {res.text[:300]}')
        return res.json() if res.content else None

    def objects(self, entity: str) -> list[dict]:
        return self.request('GET', f'/objects/{entity}')

    def ensure_object(self, entity: str, name: str, **fields) -> int:
        for obj in self.objects(entity):
            if obj['name'] == name:
                return int(obj['id'])
        return int(self.request('POST', f'/objects/{entity}', json={'name': name, **fields})['created_object_id'])

    def ensure_asin_userfield(self) -> None:
        if not any(u['entity'] == 'products' and u['name'] == 'asin' for u in self.objects('userfields')):
            self.request('POST', '/objects/userfields', json={
                'entity': 'products', 'name': 'asin', 'caption': 'ASIN',
                'type': 'text-single-line', 'show_as_column_in_tables': 1,
            })

    def products_by_asin(self) -> dict[str, int]:
        result = {}
        for p in self.objects('products'):
            asin = (self.request('GET', f'/userfields/products/{p["id"]}') or {}).get('asin')
            if asin:
                result[asin] = int(p['id'])
        return result

    def purchased_keys(self) -> set[str]:
        return {
            row['note'] for row in self.objects('stock_log')
            if row['transaction_type'] == 'purchase' and not int(row['undone']) and row.get('note')
        }


def cmd_load(args) -> int:
    purchases = load_purchases(require_private_path(AMAZON_CSV))
    print(f'{len(purchases)} 件の購入（{len({p.asin for p in purchases})} 商品）', file=sys.stderr)
    if args.dry_run:
        for p in purchases:
            print(f'{p.date}  {CONSUMABLES[p.asin][0]}  x{p.amount}  {p.key}')
        return 0

    g = Grocy(require_env('GROCY_URL'), require_env('GROCY_API_KEY'))
    location_id = g.ensure_object('locations', LOCATION)
    shop_id = g.ensure_object('shopping_locations', SHOPPING_LOCATION)
    g.ensure_asin_userfield()

    products = g.products_by_asin()
    for asin, (name, _) in CONSUMABLES.items():
        if asin in products:
            continue
        pid = g.ensure_object(
            'products', name,
            location_id=location_id, shopping_location_id=shop_id,
            qu_id_purchase=QUANTITY_UNIT_ID, qu_id_stock=QUANTITY_UNIT_ID,
            qu_id_consume=QUANTITY_UNIT_ID, qu_id_price=QUANTITY_UNIT_ID,
            default_best_before_days=-1,
        )
        g.request('PUT', f'/userfields/products/{pid}', json={'asin': asin})
        products[asin] = pid
        print(f'商品を追加: {name}', file=sys.stderr)

    done = g.purchased_keys()
    added = 0
    for p in purchases:
        if p.key in done:
            continue
        pid = products[p.asin]
        log = g.request('POST', f'/stock/products/{pid}/add', json={
            'amount': p.amount, 'best_before_date': NEVER_DUE, 'purchased_date': p.date,
            'price': p.unit_price, 'location_id': location_id, 'shopping_location_id': shop_id,
            'note': p.key,
        })
        # 入庫した行そのものを消費する（FIFO に任せると棚卸しで付けた在庫を食う）
        stock_id = log[0]['stock_id']
        g.request('POST', f'/stock/products/{pid}/consume', json={
            'amount': p.amount, 'stock_entry_id': stock_id, 'transaction_type': 'consume',
        })
        added += 1
    print(f'入庫: {added} 件追加 / {len(purchases) - added} 件は投入済み', file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('load', help='購入履歴を Grocy へ投入する（冪等）')
    p.add_argument('--dry-run', action='store_true')
    p.set_defaults(func=cmd_load)
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
