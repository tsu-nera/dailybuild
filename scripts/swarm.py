#!/usr/bin/env python
# coding: utf-8
"""
Swarm（Foursquare）CLI（fetch）

自分のチェックインを v2 API で取得し、data/swarm/（dailybuild-private への symlink）に積む。
checkins.jsonl が API の生の checkin（id で upsert）、checkins.csv はそこから作り直す平らな写し。

Usage:
    python scripts/swarm.py fetch --login   # 初回のみ。表示された URL を同じマシンのブラウザで開いて許可する
    python scripts/swarm.py fetch           # 手元の最新から LOOKBACK_DAYS 遡って取り直す（手元が空なら全期間）
    python scripts/swarm.py fetch --full    # 全期間を取り直す

Client ID・Client Secret は .env（FOURSQUARE_CLIENT_ID / FOURSQUARE_CLIENT_SECRET。
redirect URI を既定から変えたら FOURSQUARE_REDIRECT_URI）。
access token は config/swarm_token.json（--login が書く。vaio へはコピーする）。
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.swarm import client, store
from lib.utils.env import MissingEnvError

# 後から付けた写真・コメントの変更を拾うため、手元の最新から遡って取り直す
LOOKBACK_DAYS = 7

log = logging.getLogger('swarm')


def login() -> str:
    try:
        client_id, client_secret, redirect_uri = client.load_credentials()
    except MissingEnvError as exc:
        sys.exit(f'⚠️ {exc}')
    print('次の URL をブラウザで開いて許可する（10分待つ）:', file=sys.stderr)
    print(client.authorize_url(client_id, redirect_uri), file=sys.stderr)
    code = client.wait_for_code(redirect_uri)
    token = client.exchange_code(client_id, client_secret, redirect_uri, code)
    store.TOKEN_FILE.write_text(json.dumps({'access_token': token}, indent=2) + '\n', encoding='utf-8')
    store.TOKEN_FILE.chmod(0o600)
    log.info('token を保存: %s', store.TOKEN_FILE)
    return token


def load_token() -> str:
    if not store.TOKEN_FILE.exists():
        sys.exit(f'⚠️ {store.TOKEN_FILE} が無い。初回は fetch --login で作る'
                 '（vaio では作らず、mouse で作ったものをコピーする）')
    return json.loads(store.TOKEN_FILE.read_text(encoding='utf-8'))['access_token']


def cmd_fetch(args) -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    token = login() if args.login else load_token()

    last = None if args.full else store.last_created_at()
    after = None if last is None else last - LOOKBACK_DAYS * 86400
    log.info('Swarm チェックイン取得: %s', '全期間' if after is None else f'{after} 以降')

    started = time.monotonic()
    items = client.fetch_checkins(token, after_timestamp=after)
    log.info('取得件数: %d件（%.0f秒）', len(items), time.monotonic() - started)
    if not items:
        log.info('期間内のチェックインは0件')
        return
    raw = store.merge_raw(items)
    df = store.write_csv(raw)
    log.info('保存完了: %s / %s (総件数 %d件)', store.RAW_FILE, store.CSV_FILE, len(df))


def main() -> None:
    parser = argparse.ArgumentParser(description='Swarm CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_fetch = subparsers.add_parser('fetch', help='チェックインを取り込む')
    p_fetch.add_argument('--login', action='store_true', help='ブラウザで許可して token を作り直す')
    p_fetch.add_argument('--full', action='store_true', help='全期間を取り直す')
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
