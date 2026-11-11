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
    python scripts/homebox.py dispose manual:12 --date 2026-11-11 --how 'メルカリで売却'

add は同じ key があれば何もせず止まる。品名・購入日・価格・購入先は key から data/purchases/ を引いて埋める。
どれも最後に export まで行う。ログは stderr。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import re

from lib.clients.homebox_client import HomeboxClient
from lib.inventory.homebox import (InventoryError, add_item, dispose_item, export_rows,
                                   load_items, purchase_lookup, write_csv)
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
                      args.acquired_on, args.note, joined)
    print(f'追加: {key} {entity["name"]}', file=sys.stderr)
    export(client)


def cmd_dispose(args, client) -> None:
    entity = dispose_item(client, args.key, args.date, args.how)
    print(f'手放した: {args.key} {entity["name"]}', file=sys.stderr)
    export(client)


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
    p.set_defaults(func=cmd_add)

    p = sub.add_parser('dispose', help='手放した印を付ける')
    p.add_argument('key')
    p.add_argument('--date', required=True)
    p.add_argument('--how', default='', help='手放し方（売却・粗大ごみなど）')
    p.set_defaults(func=cmd_dispose)

    args = parser.parse_args()
    try:
        args.func(args, HomeboxClient.from_env())
    except InventoryError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
