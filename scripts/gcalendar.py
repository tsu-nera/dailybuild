#!/usr/bin/env python
# coding: utf-8
"""
Google Calendar（primary）の写しを data/calendar/events.csv に取得する CLI

管理の正本は Google Calendar。CSV は読み取り専用の写し。
description / attendees は保存しない。status=cancelled で返った予定だけを
写しから消し、API が返さなかった既存行は消さない。API が失敗したら CSV には
一切書かず非ゼロ終了する。

ファイル名を calendar.py にしない（scripts/ が sys.path[0] に入り、標準ライブラリの
calendar を shadow する）。

Usage:
    python scripts/gcalendar.py fetch --login      # 初回認可（ブラウザが開く）
    python scripts/gcalendar.py fetch              # 直近 --days 日（既定2）
    python scripts/gcalendar.py fetch --since 2026-01-01
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib import gcalendar
from lib.clients import gcalendar_client
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
CSV_FILE = BASE_DIR / 'data' / 'calendar' / 'events.csv'

JST = gcalendar.JST


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def fetch_to_csv(service, csv_path: Path, time_min: str, time_max: str) -> int:
    """予定を取得して csv_path にマージする。失敗時は CSV に触れず 1 を返す"""
    try:
        items = gcalendar_client.list_events(service, time_min, time_max)
        new_rows, cancelled = gcalendar.to_rows(items)
        merged = gcalendar.merge(csv_path, new_rows, cancelled)
    except Exception as e:  # noqa: BLE001 - どんな失敗でも CSV を変えない
        _log(f'エラー: Google Calendar の取得に失敗: {e}')
        return 1

    ensure_dir(csv_path.parent)
    tmp = csv_path.with_name(csv_path.name + '.tmp')
    merged.to_csv(tmp, index=False)
    tmp.replace(csv_path)
    _log(f'取得 {len(new_rows)}件 / cancelled {len(cancelled)}件 / 合計 {len(merged)}件 -> {csv_path}')
    return 0


def _midnight(day: dt.date) -> str:
    return dt.datetime.combine(day, dt.time(), JST).isoformat()


def cmd_fetch(args) -> int:
    csv_path = require_private_path(CSV_FILE)

    today = dt.datetime.now(JST).date()
    if args.since:
        start_day = dt.date.fromisoformat(args.since)
    else:
        start_day = today - dt.timedelta(days=args.days)
    time_min = _midnight(start_day)
    time_max = _midnight(today + dt.timedelta(days=1))

    try:
        service = gcalendar_client.create_service(interactive=args.login)
    except Exception as e:  # noqa: BLE001
        _log(f'エラー: 認可に失敗: {e}')
        return 1
    return fetch_to_csv(service, csv_path, time_min, time_max)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Google Calendar の写しを取得する')
    sub = parser.add_subparsers(dest='command', required=True)
    p_fetch = sub.add_parser('fetch', help='予定を data/calendar/events.csv へマージする')
    p_fetch.add_argument('--days', type=int, default=2,
                         help='今日から何日前まで取るか（既定 2）')
    p_fetch.add_argument('--since', help='開始日 YYYY-MM-DD（過去分の一括取得。--days より優先）')
    p_fetch.add_argument('--login', action='store_true',
                         help='初回認可（ブラウザが開く）。無ければ非対話で、トークンが無いと失敗する')
    p_fetch.set_defaults(func=cmd_fetch)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
