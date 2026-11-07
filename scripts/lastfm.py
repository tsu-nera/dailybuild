#!/usr/bin/env python
# coding: utf-8
"""
Last.fm CLI（fetch）

Last.fm の scrobble を取得し、data/lastfm/scrobbles.csv（dailybuild-private への
symlink）に1行=1 scrobble で蓄積する。スマホの Pano Scrobbler が YouTube 本体の
再生を scrobble するので、音楽に加えて動画も「曲」として混ざる。

Usage:
    python scripts/lastfm.py fetch --login   # 初回のみ。表示された URL をブラウザで開いて許可する
    python scripts/lastfm.py fetch           # CSV の最新から LOOKBACK_DAYS 遡って取り直す（CSV が空なら全期間）
    python scripts/lastfm.py fetch --full    # 全期間を取り直す

API key・Shared secret・ユーザー名は .env（LASTFM_API_KEY / LASTFM_API_SECRET / LASTFM_USER）。
セッションは config/lastfm_session.json（--login が書く。vaio へはコピーする）。
"""

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.lastfm import client, store
from lib.utils.env import MissingEnvError

# Last.fm はオフライン中に貯めた scrobble を、再生した時刻のまま最大14日前まで受け付ける。
# 遅れて届いた分を取りこぼさないよう、CSV の最新からその分だけ遡って取り直す
LOOKBACK_DAYS = 14

log = logging.getLogger('lastfm')


def login(api_key: str, api_secret: str, user: str) -> str:
    token = client.get_token(api_key, api_secret)
    print('次の URL をブラウザで開いて「Yes, allow access」を押す（10分待つ）:', file=sys.stderr)
    print(client.auth_url(api_key, token), file=sys.stderr)
    session = client.wait_for_session(api_key, api_secret, token)
    if session['name'].lower() != user.lower():
        sys.exit(f"⚠️ 許可したアカウント {session['name']} が LASTFM_USER={user} と違う")
    store.SESSION_FILE.write_text(json.dumps(
        {'name': session['name'], 'key': session['key']}, indent=2) + '\n', encoding='utf-8')
    store.SESSION_FILE.chmod(0o600)
    log.info('セッションを保存: %s', store.SESSION_FILE)
    return session['key']


def load_session_key() -> str:
    if not store.SESSION_FILE.exists():
        sys.exit(f'⚠️ {store.SESSION_FILE} が無い。初回は fetch --login で作る'
                 '（vaio では作らず、mouse で作ったものをコピーする）')
    return json.loads(store.SESSION_FILE.read_text(encoding='utf-8'))['key']


def cmd_fetch(args) -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    try:
        api_key, api_secret, user = client.load_credentials()
    except MissingEnvError as exc:
        sys.exit(f'⚠️ {exc}')

    session_key = login(api_key, api_secret, user) if args.login else load_session_key()

    last = None if args.full else store.last_uts()
    from_uts = None if last is None else last - LOOKBACK_DAYS * 86400
    if from_uts is None:
        log.info('Last.fm scrobble 取得: 全期間')
    else:
        since = dt.datetime.fromtimestamp(from_uts).astimezone().isoformat(timespec='minutes')
        log.info('Last.fm scrobble 取得: %s 以降', since)

    tracks = client.fetch_recent_tracks(api_key, api_secret, session_key, user, from_uts)
    df_new = store.build_dataframe(tracks)
    if df_new.empty:
        log.info('期間内の scrobble は0件')
        return
    df_merged = store.save_merged(df_new)
    log.info('取得件数: %d件', len(df_new))
    log.info('保存完了: %s (総行数 %d行)', store.CSV_FILE, len(df_merged))


def main() -> None:
    parser = argparse.ArgumentParser(description='Last.fm CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_fetch = subparsers.add_parser('fetch', help='scrobble を CSV に取り込む')
    p_fetch.add_argument('--login', action='store_true', help='ブラウザで許可してセッションを作り直す')
    p_fetch.add_argument('--full', action='store_true', help='全期間を取り直す')
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
