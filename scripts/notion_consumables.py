#!/usr/bin/env python3
"""
消耗品の正本（Notion「消耗品DB」）を data/inventory/consumables.csv・stocktake.csv へ写す（日次）

key が空の品目には同期が `n_` + ページ ID 先頭8桁を振り、Notion の key 列へ書き戻す。
key の重複・Notion が0行のときは CSV を書かずに exit 1。規則は lib/inventory/notion_consumables.py と docs/inventory.md。
.env の NOTION_API_TOKEN（integration token。消耗品DB に接続しておく）と NOTION_CONSUMABLES_DATA_SOURCE_ID を読む。
ログは stderr。

Usage:
    uv run python scripts/notion_consumables.py fetch
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.clients.notion_client import NotionClient  # noqa: E402
from lib.inventory.notion_consumables import JST, SyncError, sync  # noqa: E402
from lib.utils.env import MissingEnvError, require_env  # noqa: E402
from lib.utils.private_data import ensure_dir, require_private_path  # noqa: E402

CONSUMABLES_CSV = project_root / 'data' / 'inventory' / 'consumables.csv'
STOCKTAKE_CSV = project_root / 'data' / 'inventory' / 'stocktake.csv'


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def cmd_fetch(args) -> int:
    consumables = require_private_path(CONSUMABLES_CSV)
    stocktake = require_private_path(STOCKTAKE_CSV)
    ensure_dir(consumables.parent)
    try:
        client = NotionClient(require_env('NOTION_API_TOKEN'))
        data_source_id = require_env('NOTION_CONSUMABLES_DATA_SOURCE_ID').removeprefix('collection://')
        sync(client, data_source_id, consumables, stocktake, dt.datetime.now(JST).date(), log=log)
    except (SyncError, MissingEnvError) as e:
        log(str(e))
        return 1
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    sub.add_parser('fetch', help='Notion → consumables.csv・stocktake.csv').set_defaults(func=cmd_fetch)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
