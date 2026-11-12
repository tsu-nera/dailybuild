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
        --acquired-on 2026-11-11 --price 1980 --from '店名'  # manual は manual:<次の番号> を振る
    python scripts/homebox.py add uniqlo:2026-05-27:482300:03 --category ファッション --subcategory トップス
    python scripts/homebox.py dispose manual:12 --date 2026-11-11 --how '粗大ごみ'
    python scripts/homebox.py dispose manual:12 --mercari m72763833954   # 売却日・売値は mercari.csv から
    python scripts/homebox.py plan manual:12 売却              # 手放すと決めた印（売却・破棄。dispose で閉じる）
    python scripts/homebox.py market manual:33 7150 --source 'メルカリ SOLD（直近90日）中央値'  # 任意の中古相場
    python scripts/homebox.py market manual:33 --query 'WH-1000XM3 --min 5000'  # 検索条件を付けてその場で1回引く
    python scripts/homebox.py market --all                     # 検索条件のある物のうち30日以上調べていない物を引く（日次）
    python scripts/homebox.py market --all --every 0           # 全部引き直す
    python scripts/homebox.py move manual:12 クローゼット      # 末端の名前か経路（'メイン / 机'）
    python scripts/homebox.py find 耳栓                        # key・品名・メモの部分一致
    python scripts/homebox.py find --location 玄関 --tag 家電  # 場所は経路の部分一致、タグはカテゴリかサブカテゴリ
    python scripts/homebox.py find --all                       # 手放した物も含める

market の検索条件は custom field `相場検索`（書式は lib.inventory.market）。引いた相場は `中古相場` とメモ、
履歴は data/inventory/market.csv（手で入れた相場も count 空で積む）。--all / --query は最後に中古相場の合計を stdout に出す。
add は同じ key があれば何もせず止まる。品名・購入日・価格・購入先は key から data/purchases/ を引いて埋める。
add / dispose / move は最後に export まで行う。find は Homebox を直接読み、表を stdout に出す。ログは stderr。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import re
import datetime

from lib.clients.homebox_client import HomeboxClient
from lib.inventory.homebox import (DISPOSAL_KINDS, InventoryError, add_item, dispose_item,
                                   export_rows, find_rows, load_items, mercari_sales, move_item,
                                   market_price, market_targets, plan_disposal, purchase_lookup,
                                   set_market_price, set_market_query, write_csv)
from lib.inventory.market import append_history, due, fetch_sold, read_history
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
ITEMS_CSV = BASE_DIR / 'data' / 'inventory' / 'items.csv'
MARKET_CSV = BASE_DIR / 'data' / 'inventory' / 'market.csv'
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
                      args.acquired_on, args.note, joined, args.url,
                      price=args.price, purchase_from=args.purchase_from)
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


def cmd_plan(args, client) -> None:
    entry = plan_disposal(client, args.key, args.kind, args.date or datetime.date.today().isoformat())
    print(f'手放す予定: {args.key} {entry["name"]}（{entry["scheduledDate"]}）', file=sys.stderr)


def fetch_markets(client, keys: list[str], targets: dict, date: str) -> int:
    """keys の相場を引いて Homebox と market.csv に書く。取得に失敗した件数を返す"""
    path = require_private_path(MARKET_CSV)
    ensure_dir(path.parent)
    rows, failed = [], 0
    for key in keys:
        entity, query = targets[key]
        try:
            stats = fetch_sold(query)
        except Exception as e:  # mercapi は非公式 API。1件の失敗で他を止めない
            print(f'error: {key} {entity["name"]} の相場が取れない: {e!r}', file=sys.stderr)
            failed += 1
            continue
        rows.append({'date': date, 'key': key, 'name': entity['name'],
                     'median': f'{stats.median:.0f}' if stats.median is not None else '',
                     'count': stats.count, 'query': query})
        if stats.median is None:
            print(f'相場にならず: {key} {entity["name"]}（SOLD {stats.count}件。検索条件を見直す）', file=sys.stderr)
            continue
        set_market_price(client, key, stats.median, date, stats.source)
        print(f'相場: {key} {entity["name"]} {stats.median:,.0f}円（{stats.count}件）', file=sys.stderr)
    if rows:
        append_history(path, rows)
    return failed


def print_market_total(client) -> None:
    owned = [(k, e) for k, e in load_items(client).items() if not e.get('archived') and market_price(e)]
    print('| key | 品名 | 中古相場 |')
    print('|---|---|---:|')
    for k, e in sorted(owned, key=lambda x: -market_price(x[1])):
        print(f'| {k} | {e["name"]} | {market_price(e):,.0f} |')
    total = sum(market_price(e) for _, e in owned)
    print(f'\n合計 {total:,.0f}円（手取り目安 ×0.9 = {total * 0.9:,.0f}円、{len(owned)}件）')


def cmd_market(args, client) -> None:
    date = args.date or datetime.date.today().isoformat()
    if args.all:
        targets = market_targets(client)
        keys = due(targets, read_history(require_private_path(MARKET_CSV)),
                   datetime.date.fromisoformat(date), args.every)
        print(f'相場検索あり {len(targets)} 件、うち今回引く {len(keys)} 件', file=sys.stderr)
        failed = fetch_markets(client, keys, targets, date) if keys else 0
    elif args.query is not None:
        if not args.key:
            raise InventoryError('--query には key が要る')
        set_market_query(client, args.key, args.query)
        failed = 0
        if args.query:
            failed = fetch_markets(client, [args.key], market_targets(client), date)
    else:
        if not (args.key and args.price is not None and args.source):
            raise InventoryError('手で入れるときは key・価格・--source が要る（定期取得は --query / --all）')
        entity = set_market_price(client, args.key, args.price, date, args.source)
        path = require_private_path(MARKET_CSV)
        ensure_dir(path.parent)
        append_history(path, [{'date': date, 'key': args.key, 'name': entity['name'],
                               'median': f'{args.price:.0f}', 'count': '', 'query': args.source}])
        print(f'相場: {args.key} {entity["name"]} {args.price:,.0f}円（{date}）', file=sys.stderr)
        export(client)
        return
    export(client)
    print_market_total(client)
    if failed:
        raise InventoryError(f'{failed} 件の相場が取れなかった')


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
    p.add_argument('--price', type=float, default=0.0, help='購入価格（店頭購入など購入データに無いとき）')
    p.add_argument('--from', dest='purchase_from', default='', help='購入先（店頭購入など）')
    p.set_defaults(func=cmd_add)

    p = sub.add_parser('dispose', help='手放した印を付ける')
    p.add_argument('key')
    p.add_argument('--date', default='')
    p.add_argument('--how', default='', help='手放し方（売却・粗大ごみなど）')
    p.add_argument('--mercari', default='', metavar='ITEM_ID', help='メルカリの売却から日付・売値を埋める')
    p.set_defaults(func=cmd_dispose)

    p = sub.add_parser('plan', help='手放すと決めた印（メンテナンス記録の売却・破棄）')
    p.add_argument('key')
    p.add_argument('kind', choices=DISPOSAL_KINDS)
    p.add_argument('--date', default='', help='決めた日（既定は今日）')
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser('market', help='中古相場を入れる・引く（任意。最新値を custom field、履歴をメモへ）')
    p.add_argument('key', nargs='?', default='')
    p.add_argument('price', nargs='?', type=float)
    p.add_argument('--source', default='', help="手で入れるときの出どころ（'メルカリ SOLD（直近90日）中央値'）")
    p.add_argument('--date', default='', help='調べた日（既定は今日）')
    p.add_argument('--query', help="検索条件を付けてその場で引く（'WH-1000XM3 --min 5000'。空文字で外す）")
    p.add_argument('--all', action='store_true', help='検索条件のある物を引く')
    p.add_argument('--every', type=int, default=30, help='--all で前回から何日空いたら引くか（既定30）')
    p.set_defaults(func=cmd_market)

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
