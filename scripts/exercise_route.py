#!/usr/bin/env python
# coding: utf-8
"""
運動の GPS 軌跡（TCX）を Google Health から取る -> data/googlehealth/tcx/<開始日>_<id>.tcx

exercise.csv の has_gps=True の行のうち、TCX がまだ無いものを全部取る（窓は無い。
取れなかった日は翌日また取りに行く）。exercise.csv を読むので Google Health の取得の後に流す。
Dawarich へ上げるのは `dawarich.py import-routes`。

トークンは日次取得のものと別の config/googlehealth_location_token.json
（location スコープが要る）。対話マシンで login して作り、vaio へコピーする。

Usage:
    python scripts/exercise_route.py login            # ブラウザで同意してトークンを作る（初回のみ）
    python scripts/exercise_route.py fetch            # 未取得の TCX を取る
    python scripts/exercise_route.py fetch --dry-run  # 取る件数だけ出す
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib import exercise_route
from lib.clients import googlehealth_client as api
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
EXERCISE_CSV = require_private_path(BASE_DIR / 'data' / 'googlehealth' / 'exercise.csv')
TCX_DIR = require_private_path(BASE_DIR / 'data' / 'googlehealth' / 'tcx')

log = logging.getLogger('exercise_route')


def _authorize(interactive: bool):
    return api.authorize(interactive=interactive, token_file=api.LOCATION_TOKEN_FILE,
                         scopes=api.LOCATION_SCOPES)


def cmd_login(args) -> int:
    _authorize(interactive=True)
    log.info('トークンを書いた: %s', api.LOCATION_TOKEN_FILE)
    return 0


def cmd_fetch(args) -> int:
    targets = exercise_route.pending(EXERCISE_CSV, TCX_DIR)
    log.info('軌跡のある運動で TCX が未取得: %d 件', len(targets))
    if args.dry_run or not targets:
        return 0

    creds = _authorize(interactive=False)
    ensure_dir(TCX_DIR)
    failed = 0
    for exercise_id, name in targets:
        try:
            tcx = exercise_route.export_tcx(creds, exercise_id)
        except api.GoogleHealthError as exc:
            log.error('%s: %s', name, exc)
            failed += 1
            continue
        (TCX_DIR / name).write_text(tcx, encoding='utf-8')
        log.info('%s (%d KB)', name, len(tcx.encode()) // 1024)
    return 1 if failed else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    parser = argparse.ArgumentParser(description='運動の GPS 軌跡（TCX）')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_login = subparsers.add_parser('login', help='ブラウザで同意してトークンを作る')
    p_login.set_defaults(func=cmd_login)

    p_fetch = subparsers.add_parser('fetch', help='未取得の TCX を取る')
    p_fetch.add_argument('--dry-run', action='store_true', help='件数だけ出して API を呼ばない')
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
