#!/usr/bin/env python
# coding: utf-8
"""
GPSLogger の GPX を private へ写す -> data/gpslogger/YYYY-MM-DD.gpx

位置の記録の正本。スマホの GPSLogger が1日1ファイルで書き、Syncthing（送信のみ）が vaio の
GPSLOGGER_DIR（.env、既定 ~/gpslogger）へ同期する。日次は vaio が流す。写すのは前日まで
（理由は lib/gpslogger.py）。Dawarich へ上げるのは `dawarich.py import-routes`。

Usage:
    python scripts/gpslogger.py fetch            # 前日までの未取得・伸びたファイルを写す
    python scripts/gpslogger.py fetch --dry-run  # 写すファイルだけ出す
"""

import argparse
import datetime as dt
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib import gpslogger
from lib.utils.env import get_env
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
DEST_DIR = require_private_path(BASE_DIR / 'data' / 'gpslogger')
JST = dt.timezone(dt.timedelta(hours=9))

log = logging.getLogger('gpslogger')


def cmd_fetch(args) -> int:
    src_dir = Path(get_env('GPSLOGGER_DIR', '~/gpslogger')).expanduser()
    if not src_dir.is_dir():
        # 同期先が無いのは vaio 以外で流したか、Syncthing の設定が壊れたか。黙って 0 にしない
        log.error('GPSLOGGER_DIR が無い: %s', src_dir)
        return 1
    pairs = gpslogger.to_copy(src_dir, DEST_DIR, dt.datetime.now(JST).date())
    log.info('GPSLogger: 写すファイル %d 件', len(pairs))
    for src, dest in pairs:
        log.info('  %s -> %s (%d KB)', src.name, dest.name, src.stat().st_size // 1024)
        if not args.dry_run:
            ensure_dir(dest.parent)
            shutil.copy2(src, dest)
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    parser = argparse.ArgumentParser(description='GPSLogger の GPX')
    subparsers = parser.add_subparsers(dest='command', required=True)
    p_fetch = subparsers.add_parser('fetch', help='前日までの GPX を写す')
    p_fetch.add_argument('--dry-run', action='store_true', help='写すファイルだけ出す')
    p_fetch.set_defaults(func=cmd_fetch)
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
