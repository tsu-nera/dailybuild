#!/usr/bin/env python
# coding: utf-8
"""購入履歴

Amazon の個人データ開示で届く `Your Orders.zip` を data/purchases/amazon.csv へ取り込む。
申請は https://www.amazon.co.jp/hz/privacy-central/data-requests/preview.html
（アカウントサービスのメニューからはたどれない）。

export は全期間を含むので、取り込みは毎回の全置き換え。既存の注文 ID が新しい
export に1件でも無ければ書き込まない（欠けた export で正本を潰さない）。

Usage:
    python scripts/purchases.py import-amazon ~/Downloads/"Your Orders.zip"
    python scripts/purchases.py import-amazon <Order History.csv> --force
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import logging

import pandas as pd

from lib.purchases import amazon_export
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
AMAZON_CSV = BASE_DIR / 'data' / 'purchases' / 'amazon.csv'

logger = logging.getLogger('purchases')


def import_amazon(src: Path, dest: Path, force: bool = False) -> int:
    """export を正規化して dest を置き換える。書かなかったら 1"""
    new = amazon_export.read_export(src)

    if dest.exists():
        existing = pd.read_csv(dest, dtype=str)
        lost = amazon_export.lost_orders(existing, new)
        if lost and not force:
            logger.error(
                '既存の注文 %d 件が新しい export に無いので書き込まない（例: %s）。'
                '意図した置き換えなら --force を付ける',
                len(lost), ', '.join(sorted(lost)[:3]))
            return 1
        before = len(existing)
    else:
        before = 0

    ensure_dir(dest.parent)
    tmp = dest.with_name(dest.name + '.tmp')
    new.to_csv(tmp, index=False)
    tmp.replace(dest)
    logger.info('%s を更新した（%d → %d 行、%s 〜 %s）', dest.name, before, len(new),
                new['order_date'].iloc[0][:10], new['order_date'].iloc[-1][:10])
    return 0


def main():
    parser = argparse.ArgumentParser(description='購入履歴を取り込む')
    sub = parser.add_subparsers(dest='command', required=True)

    p_amazon = sub.add_parser('import-amazon', help='Amazon の開示データを取り込む')
    p_amazon.add_argument('path', type=Path, help='Your Orders.zip か Order History.csv')
    p_amazon.add_argument('--force', action='store_true',
                          help='既存の注文が export に無くても置き換える')

    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format='%(levelname)s: %(message)s')

    if args.command == 'import-amazon':
        return import_amazon(args.path, require_private_path(AMAZON_CSV), args.force)
    return 1


if __name__ == '__main__':
    sys.exit(main())
