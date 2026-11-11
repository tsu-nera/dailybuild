#!/usr/bin/env python
# coding: utf-8
"""
Homebox（持ち物の器の試用、#263）へ items.csv を流し込む

試用中の正本は data/inventory/items.csv のまま。Homebox は vaio の scripts/ops/homebox で動く。
接続先と API key は .env の HOMEBOX_URL / HOMEBOX_API_KEY。

Usage:
    python scripts/homebox.py push --dry-run   # 作る・直す件数だけ見る
    python scripts/homebox.py push             # items.csv の全行を反映（何度流しても増えない）

結果のログは stderr。Homebox にだけある物（UI で足した物）は消さずに名前を出す。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse

import pandas as pd

from lib.clients.homebox_client import HomeboxClient
from lib.inventory.homebox_sync import desired_entities, purchase_lookup, push
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).parent.parent
ITEMS_CSV = BASE_DIR / 'data' / 'inventory' / 'items.csv'
PURCHASES_DIR = BASE_DIR / 'data' / 'purchases'


def cmd_push(args) -> int:
    items = pd.read_csv(require_private_path(ITEMS_CSV), dtype=str, keep_default_na=False)
    desired = desired_entities(items, purchase_lookup(require_private_path(PURCHASES_DIR)))
    result = push(HomeboxClient.from_env(), desired, dry_run=args.dry_run)
    prefix = '[dry-run] ' if args.dry_run else ''
    print(f'{prefix}作成 {len(result.created)} / 更新 {len(result.updated)} / '
          f'変化なし {len(result.unchanged)}', file=sys.stderr)
    for key in result.updated:
        print(f'  更新: {key}', file=sys.stderr)
    if result.unmanaged:
        print(f'Homebox にだけある物（消していない）: {", ".join(result.unmanaged)}', file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('push', help='items.csv を Homebox へ反映')
    p.add_argument('--dry-run', action='store_true')
    p.set_defaults(func=cmd_push)
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
