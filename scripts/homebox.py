#!/usr/bin/env python
# coding: utf-8
"""
持ち物（正本は Homebox、#263）の書き込みと items.csv への書き出し

Homebox は vaio の scripts/ops/homebox で動く。接続先と API key は .env の HOMEBOX_URL / HOMEBOX_API_KEY。
data/inventory/items.csv は export の生成物なので直接書かない。

Usage:
    python scripts/homebox.py export                     # Homebox → items.csv（全上書き、日次）
    python scripts/homebox.py add amazon:250-...:B0XXXX --category 日用品
    python scripts/homebox.py add manual --name 'フライパン' --category 日用品 \\
        --acquired-on 2026-11-11 --note '店名・価格'      # manual は manual:<次の番号> を振る
    python scripts/homebox.py add uniqlo:2026-05-27:482300:03 --category ファッション --subcategory トップス
    python scripts/homebox.py dispose manual:12 --date 2026-11-11 --how '粗大ごみ'
    python scripts/homebox.py dispose manual:12 --mercari m72763833954   # 売却日・売値は mercari.csv から
    python scripts/homebox.py move manual:12 クローゼット       # 末端の名前か経路（'メイン / 机'）
    python scripts/homebox.py find 耳栓                        # key・品名・メモの部分一致
    python scripts/homebox.py find --location 玄関 --tag 家電  # 場所は経路の部分一致、タグはカテゴリかサブカテゴリ
    python scripts/homebox.py find --all                       # 手放した物も含める

add は同じ key があれば何もせず止まる。品名・購入日・価格・購入先は key から data/purchases/ を引いて埋める。
add / dispose / move は最後に export まで行う。find は Homebox を直接読み、表を stdout に出す。ログは stderr。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import re

from lib.clients.homebox_client import HomeboxClient
from lib.inventory.homebox import (InventoryError, add_item, dispose_item, export_rows,
                                   find_rows, load_items, mercari_sales, move_item, purchase_lookup,
                                   write_csv)
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
ITEMS_CSV = BASE_DIR / 'data' / 'inventory' / 'items.csv'
PURCHASES_DIR = BASE_DIR / 'data' / 'purchases'


def export(client) -> None:
    path = require_private_path(ITEMS_CSV)
    ensure_dir(path.parent)
    rows = export_rows(client)
    write_csv(rows, path)
    print(f'items.csv に {len(rows)} 件（うち手放した物 '
          f'{sum(r["status"] == "disposed" for r in rows)}）', file=sys.stderr)


def next_manual_key(client) -> str:
    numbers = [int(m.group(1)) for k in load_items(client) if (m := re.fullmatch(r'manual:(\d+)', k))]
    return f'manual:{max(numbers, default=0) + 1}'


def cmd_export(args, client) -> None:
    export(client)


def cmd_add(args, client) -> None:
    key = next_manual_key(client) if args.key == 'manual' else args.key
    joined = purchase_lookup(require_private_path(PURCHASES_DIR)).get(key)
    if joined is None and not key.startswith('manual:'):
        print(f'warning: {key} は data/purchases/ に無い（先に purchases.py fetch するか key を確かめる）',
              file=sys.stderr)
    entity = add_item(client, key, args.category, args.subcategory, args.name,
                      args.acquired_on, args.note, joined, args.url)
    print(f'追加: {key} {entity["name"]}', file=sys.stderr)
    export(client)


def cmd_dispose(args, client) -> None:
    date, how, price, sold_to = args.date, args.how, 0.0, ''
    if args.mercari:
        sale = mercari_sales(require_private_path(PURCHASES_DIR)).get(args.mercari)
        if sale is None:
            raise InventoryError(f'{args.mercari} の売却が mercari.csv に無い（先に purchases.py fetch-mercari）')
        date = date or sale['date']
        price, sold_to = sale['price'], 'メルカリ'
        how = how or f'メルカリで売却（{args.mercari}）'
    if not date:
        raise InventoryError('--date か --mercari が要る')
    entity = dispose_item(client, args.key, date, how, price, sold_to)
    print(f'手放した: {args.key} {entity["name"]}', file=sys.stderr)
    export(client)


def cmd_move(args, client) -> None:
    entity = move_item(client, args.key, args.location)
    print(f'移した: {args.key} {entity["name"]} → {args.location}', file=sys.stderr)
    export(client)


def cmd_find(args, client) -> None:
    rows = find_rows(export_rows(client), args.query, args.location, args.tag, args.all)
    print('| key | 品名 | カテゴリ | 場所 | 状態 |')
    print('|---|---|---|---|---|')
    for r in rows:
        category = '/'.join(c for c in (r['category'], r['subcategory']) if c)
        status = '手放した' if r['status'] == 'disposed' else ''
        print(f"| {r['key']} | {r['name']} | {category} | {r['location'] or '-'} | {status} |")
    print(f'{len(rows)} 件', file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('export', help='Homebox → items.csv').set_defaults(func=cmd_export)

    p = sub.add_parser('add', help='物を1つ足す')
    p.add_argument('key', help="amazon:/rakuten:/uniqlo:/mercari: の key か 'manual'")
    p.add_argument('--category', required=True)
    p.add_argument('--subcategory', default='')
    p.add_argument('--name', default='')
    p.add_argument('--acquired-on', default='')
    p.add_argument('--note', default='')
    p.add_argument('--url', default='', help='商品ページ（Amazon・楽天・メルカリは key から作り、開けるときだけ付ける。ユニクロ・店頭は手で渡す）')
    p.set_defaults(func=cmd_add)

    p = sub.add_parser('dispose', help='手放した印を付ける')
    p.add_argument('key')
    p.add_argument('--date', default='')
    p.add_argument('--how', default='', help='手放し方（売却・粗大ごみなど）')
    p.add_argument('--mercari', default='', metavar='ITEM_ID', help='メルカリの売却から日付・売値を埋める')
    p.set_defaults(func=cmd_dispose)

    p = sub.add_parser('move', help='場所を変える')
    p.add_argument('key')
    p.add_argument('location', help="末端の名前（'机'）か経路（'メイン / 机'）")
    p.set_defaults(func=cmd_move)

    p = sub.add_parser('find', help='探す（Homebox を直接読む）')
    p.add_argument('query', nargs='?', default='')
    p.add_argument('--location', default='')
    p.add_argument('--tag', default='')
    p.add_argument('--all', action='store_true', help='手放した物も含める')
    p.set_defaults(func=cmd_find)

    args = parser.parse_args()
    try:
        args.func(args, HomeboxClient.from_env())
    except InventoryError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
