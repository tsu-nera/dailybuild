#!/usr/bin/env python
# coding: utf-8
"""購入履歴

fetch: Gmail の注文確認（Amazon・楽天市場）を data/purchases/gmail.csv へマージする。
同じ message_id の行は差し替え、取得窓に無い既存行は残す。書式が合わないメールは
行を作らず警告だけ出す（終了コードは 0 のまま）。

import-amazon: Amazon の個人データ開示で届く `Your Orders.zip` を data/purchases/amazon.csv へ取り込む。
申請は https://www.amazon.co.jp/hz/privacy-central/data-requests/preview.html
（アカウントサービスのメニューからはたどれない）。

export は全期間を含むので、取り込みは毎回の全置き換え。既存の注文 ID が新しい
export に1件でも無ければ書き込まない（欠けた export で正本を潰さない）。

Usage:
    python scripts/purchases.py fetch --login --since 2025-10-01  # 初回認可（ブラウザが開く）
    python scripts/purchases.py fetch              # 直近 --days 日（既定7）
    python scripts/purchases.py import-amazon ~/Downloads/"Your Orders.zip"
    python scripts/purchases.py import-amazon <Order History.csv> --force
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import logging

import pandas as pd

from lib.clients import gmail_client
from lib.purchases import amazon_export, gmail
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
AMAZON_CSV = BASE_DIR / 'data' / 'purchases' / 'amazon.csv'
GMAIL_CSV = BASE_DIR / 'data' / 'purchases' / 'gmail.csv'

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


def fetch_to_csv(service, csv_path: Path, since: dt.datetime) -> int:
    """注文確認を取得して csv_path にマージする。API が失敗したら CSV に触れず 1"""
    rows, skipped = [], []
    try:
        for message_id in gmail_client.list_message_ids(service, gmail.search_query(since)):
            message = gmail_client.get_message(service, message_id)
            text = gmail_client.body_parts(message['payload']).get('text/plain', '')
            parsed = gmail.to_rows(message, text)
            if parsed is None:
                skipped.append(message_id)
            else:
                rows.extend(parsed)
        merged = gmail.merge(csv_path, rows)
    except Exception as e:  # noqa: BLE001 - どんな失敗でも CSV を変えない
        logger.error('Gmail の取得に失敗: %s', e)
        return 1

    if skipped:
        logger.warning('書式が合わず行を作らなかったメール %d 通: %s',
                       len(skipped), ', '.join(skipped[:10]))

    ensure_dir(csv_path.parent)
    tmp = csv_path.with_name(csv_path.name + '.tmp')
    merged.to_csv(tmp, index=False)
    tmp.replace(csv_path)
    logger.info('取得 %d 行（%d 通）/ 合計 %d 行 -> %s', len(rows),
                len({r['message_id'] for r in rows}), len(merged), csv_path)
    return 0


def cmd_fetch(args) -> int:
    csv_path = require_private_path(GMAIL_CSV)
    if args.since:
        start = dt.date.fromisoformat(args.since)
    else:
        start = dt.datetime.now(gmail.JST).date() - dt.timedelta(days=args.days)
    since = dt.datetime.combine(start, dt.time(), gmail.JST)

    try:
        service = gmail_client.create_service(interactive=args.login)
    except Exception as e:  # noqa: BLE001
        logger.error('認可に失敗: %s', e)
        return 1
    return fetch_to_csv(service, csv_path, since)


def main():
    parser = argparse.ArgumentParser(description='購入履歴を取り込む')
    sub = parser.add_subparsers(dest='command', required=True)

    p_fetch = sub.add_parser('fetch', help='Gmail の注文確認を data/purchases/gmail.csv へマージする')
    p_fetch.add_argument('--days', type=int, default=7, help='今日から何日前まで取るか（既定 7）')
    p_fetch.add_argument('--since', help='開始日 YYYY-MM-DD（過去分の一括取得。--days より優先）')
    p_fetch.add_argument('--login', action='store_true',
                         help='初回認可（ブラウザが開く）。無ければ非対話で、トークンが無いと失敗する')

    p_amazon = sub.add_parser('import-amazon', help='Amazon の開示データを取り込む')
    p_amazon.add_argument('path', type=Path, help='Your Orders.zip か Order History.csv')
    p_amazon.add_argument('--force', action='store_true',
                          help='既存の注文が export に無くても置き換える')

    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format='%(levelname)s: %(message)s')

    if args.command == 'fetch':
        return cmd_fetch(args)
    if args.command == 'import-amazon':
        return import_amazon(args.path, require_private_path(AMAZON_CSV), args.force)
    return 1


if __name__ == '__main__':
    sys.exit(main())
