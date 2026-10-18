#!/usr/bin/env python
# coding: utf-8
"""
Todoist CLI（fetch）

Todoist API v1 から完了したタスクを取得し、data/todoist/completed.csv
（dailybuild-private への symlink）に1行=1完了で蓄積する。

Usage:
    python scripts/todoist.py fetch --update                 # CSV の続きから今日まで
    python scripts/todoist.py fetch --start-date 2026-10-01  # 過去分の取り込み（終端の既定は今日）
    python scripts/todoist.py fetch --start-date 2026-10-01 --end-date 2026-10-18

残すのは完了（何を・いつ・どのプロジェクト）と延期の回数（postponed_count）だけで、
編集・並べ替えなどの操作ログは取らない。

繰り返しタスクの完了は取れない。by_completion_date には出ず、完了しても次の期日へ
移るだけに見える（推測）。必要になったら activities API（event_type=completed）で
別に取る。
"""

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path
from typing import IO
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.todoist import client as todoist_client
from lib.todoist import store
from lib.utils.env import MissingEnvError

# --update で CSV の最終完了日から遡って取り直す日数。
# 完了をあとから付け直すことがあるため、最終日ちょうどではなく少し重ねて取る
UPDATE_OVERLAP_DAYS = 3


def parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, '%Y-%m-%d').date()


def resolve_period(args, out: IO[str]) -> tuple[dt.date, dt.date]:
    """fetch の引数から取得期間 [start, end] を決める"""
    end = parse_date(args.end_date) if args.end_date else dt.date.today()

    if args.start_date:
        return parse_date(args.start_date), end

    last = store.last_completed_date()
    if last is None:
        print(f"⚠️ {store.CSV_FILE} に既存データが無いため --update できない。"
              "初回は --start-date YYYY-MM-DD で期間を指定する", file=out)
        sys.exit(1)
    start = last - dt.timedelta(days=UPDATE_OVERLAP_DAYS)
    return min(start, end), end


def run_fetch(args, out: IO[str]) -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=out)

    try:
        api_token = todoist_client.load_api_token()
    except MissingEnvError as exc:
        print(f"⚠️ {exc}", file=out)
        sys.exit(1)

    start, end = resolve_period(args, out)
    print(f"Todoist 完了タスク取得: {start} ～ {end}", file=out)

    items = todoist_client.fetch_completed_tasks(
        api_token, start, end, ZoneInfo(store.TIMEZONE))
    projects = store.update_project_cache(todoist_client.fetch_projects(api_token))

    df_new = store.build_dataframe(items, projects)
    if df_new.empty:
        print(f"期間 {start}〜{end} の完了タスクは0件", file=out)
        return

    df_merged = store.save_merged(df_new)
    print(f"取得件数: {len(df_new)}件", file=out)
    print(f"保存完了: {store.CSV_FILE} (総行数 {len(df_merged)}行)", file=out)


def cmd_fetch(args) -> None:
    if args.update == bool(args.start_date):
        args.parser.error('--update か --start-date のどちらか一方を指定する')
    if args.update and args.end_date:
        args.parser.error('--update と --end-date は同時に指定できない')
    run_fetch(args, sys.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description='Todoist CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    fetch_parser = subparsers.add_parser('fetch', help='完了したタスクを CSV に取り込む')
    fetch_parser.add_argument('--update', action='store_true',
                              help=f'CSV の最終完了日の{UPDATE_OVERLAP_DAYS}日前から今日まで')
    fetch_parser.add_argument('--start-date', help='開始日 (YYYY-MM-DD)')
    fetch_parser.add_argument('--end-date', help='終了日 (YYYY-MM-DD、既定は今日)')
    fetch_parser.set_defaults(func=cmd_fetch, parser=fetch_parser)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
