#!/usr/bin/env python
# coding: utf-8
"""
くらしTEPCO web CLI（fetch）

保存済みのブラウザセッションで 30分ごとの電力使用量を取得し、
data/tepco/usage_30min.csv（dailybuild-private への symlink）に蓄積する。

Usage:
    python scripts/tepco.py fetch --login              # 初回・セッション切れ時
    python scripts/tepco.py fetch                      # CSV の最終日から今日まで（週次・mouse で手動）
    python scripts/tepco.py fetch --days 3
    python scripts/tepco.py fetch --since 2026-05-01   # 過去分の一括取得

30分値は約2年で消えるため、取りこぼしは取り直せなくなる前に回収すること。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt

import pandas as pd

from lib.tepco import client as tepco_client
from lib.tepco import store
from lib.tepco.client import NotLoggedInError, TepcoSession

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / 'config' / 'tepco_state.json'

# CSV が無い・空のときの既定窓。計量値の確定は翌日以降にずれ込むことがあるので、当日だけでは取りこぼす
DEFAULT_FETCH_DAYS = 7


def last_csv_date(csv_path: Path = store.USAGE_CSV) -> dt.date | None:
    """CSV の最終日。無い・空なら None"""
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path, usecols=['date'])
    return dt.date.fromisoformat(df['date'].max()) if len(df) else None


def resolve_days(args, today: dt.date | None = None, csv_path: Path = store.USAGE_CSV) -> list[dt.date]:
    """取得する日。明示指定が優先、無ければ CSV の最終日（部分日かもしれないので取り直す）から"""
    today = today or dt.date.today()
    if args.since:
        start = dt.date.fromisoformat(args.since)
    elif args.days is not None:
        start = today - dt.timedelta(days=args.days - 1)
    else:
        start = last_csv_date(csv_path) or today - dt.timedelta(days=DEFAULT_FETCH_DAYS - 1)
        start = min(start, today)
    return [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]


def cmd_fetch(args) -> None:
    if args.login:
        tepco_client.login(STATE_FILE)

    days = resolve_days(args)
    rows: list[dict] = []
    empty: list[dt.date] = []
    try:
        with TepcoSession(STATE_FILE) as session:
            for i, day in enumerate(days, 1):
                day_rows = store.parse_hourly(day.strftime('%Y%m%d'), session.hourly(day.strftime('%Y%m%d')))
                if not day_rows:
                    empty.append(day)
                rows.extend(day_rows)
                print(f"\r取得中 {i}/{len(days)} {day}", end='', file=sys.stderr)
            print(file=sys.stderr)
    except NotLoggedInError as e:
        sys.exit(f"ログインが必要です: {e}")

    # 当日は未計量が普通なので数えない
    empty = [d for d in empty if d != dt.date.today()]
    if empty:
        print(f"値の無い日 {len(empty)}日: {empty[0]} 〜 {empty[-1]}", file=sys.stderr)

    if not rows:
        sys.exit("1コマも取得できませんでした（欠測を正常終了にしない）")
    df = store.save(rows)
    print(f"保存完了: {store.USAGE_CSV} (+{len(rows)}コマ, 総行数 {len(df)}行)", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='くらしTEPCO web 電力使用量')
    sub = parser.add_subparsers(dest='command', required=True)

    fetch = sub.add_parser('fetch', help='30分値を取得して CSV に蓄積する')
    fetch.add_argument('--login', action='store_true', help='ブラウザで手動ログインしてセッションを保存')
    period = fetch.add_mutually_exclusive_group()
    period.add_argument('--days', type=int, help='直近N日')
    period.add_argument('--since', help='YYYY-MM-DD から今日まで')
    # --days / --since とも無指定なら CSV の最終日から今日まで（CSV が無ければ直近7日）
    fetch.set_defaults(func=cmd_fetch)
    return parser


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
