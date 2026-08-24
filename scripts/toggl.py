#!/usr/bin/env python
# coding: utf-8
"""
Toggl Track CLI（fetch / show）

Toggl Track API v9 からタイムエントリを取得して CSV に蓄積する fetch と、
data/toggl/time_entries.csv（dailybuild-private への symlink）を読んで
markdown サマリを出す show をまとめたスクリプト。

Usage:
    python scripts/toggl.py fetch --update      # CSV の続きから今日まで
    python scripts/toggl.py fetch --days 7
    python scripts/toggl.py fetch --start-date 2026-08-01 --end-date 2026-08-18

    python scripts/toggl.py show --days 7             # 日次（直近7日）
    python scripts/toggl.py show --update             # 取得してから表示
    python scripts/toggl.py show --list               # 時系列のエントリ一覧
    python scripts/toggl.py show --unit week --days 56  # 週次
    python scripts/toggl.py show --week current
    python scripts/toggl.py show --month 8

show は既定では API を一切叩かないので fetch のレートリミット枠
（/me/* 共通 30 req/h）を消費しない。
"""

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import IO

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.toggl import client as toggl_client
from lib.toggl import store
from lib.toggl import render
from lib.utils.report_args import filter_dataframe_by_period, parse_period_args

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config' / 'toggl_creds.json'

# --update で CSV の最終日から遡って取り直す日数。
# 過去日のエントリを後から追加・編集することがあるため、最終日ちょうどではなく
# 少し重ねて取る（マージは id で keep='last' なので編集は上書きされる）
UPDATE_OVERLAP_DAYS = 2


def load_creds(out: IO[str]) -> dict:
    if not CREDS_FILE.exists():
        print(f"⚠️ 認証情報ファイルが見つかりません: {CREDS_FILE}", file=out)
        print("以下の形式で作成してください:", file=out)
        print('  { "api_token": "..." }', file=out)
        sys.exit(1)
    with open(CREDS_FILE, 'r') as f:
        return json.load(f)


def resolve_period(args) -> tuple[dt.date, dt.date]:
    """fetch の引数から取得期間を決定"""
    end = dt.date.today()

    if args.start_date and args.end_date:
        return (dt.datetime.strptime(args.start_date, '%Y-%m-%d').date(),
                dt.datetime.strptime(args.end_date, '%Y-%m-%d').date())

    if args.update:
        last = store.last_recorded_date()
        if last is None:
            print(f"CSV に既存データが無いため直近 {args.days} 日を取得する")
        else:
            # 期間が長くてもリクエスト数は変わらないので、素直に最終日まで遡る
            start = last - dt.timedelta(days=UPDATE_OVERLAP_DAYS)
            return min(start, end), end

    return end - dt.timedelta(days=args.days - 1), end


def run_fetch(args, out: IO[str]) -> None:
    """fetch サブコマンドの処理本体。進捗はすべて out に出す"""
    # toggl_client がクォータ残量を logger.info で出す。設定しないと握り潰される
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=out)

    creds = load_creds(out)

    start, end = resolve_period(args)
    print(f"Togglタイムエントリ取得: {start} ～ {end}", file=out)

    entries = toggl_client.fetch_time_entries(creds['api_token'], start, end)
    projects = toggl_client.fetch_projects(creds['api_token'])

    df_new = store.build_dataframe(entries, projects)

    if df_new.empty:
        print(f"⚠️ 期間 {start}〜{end} のタイムエントリが0件。"
              "Toggl側に記録が無いか、取得が壊れている可能性がある", file=out)
        return

    df_merged = store.save_merged(df_new)

    period_min = df_merged['start'].min()
    period_max = df_merged['start'].max()
    print(f"取得件数: {len(df_new)}件", file=out)
    print(f"保存完了: {store.CSV_FILE} (総行数 {len(df_merged)}行)", file=out)
    print(f"CSVの期間: {period_min} ～ {period_max}", file=out)


def cmd_fetch(args) -> None:
    if args.update and (args.start_date or args.end_date):
        args.parser.error('--update と --start-date/--end-date は同時に指定できない')
    run_fetch(args, sys.stdout)


def cmd_show(args) -> None:
    if args.update:
        run_fetch(args, sys.stderr)

    if not store.CSV_FILE.exists():
        print(f"エラー: {store.CSV_FILE} が存在しません", file=sys.stderr)
        sys.exit(1)

    week, month, year = parse_period_args(args)
    days = args.days
    if days is None and week is None and month is None:
        if args.list:
            days = 1
        else:
            days = 28 if args.unit == 'week' else 7

    df = store.load_entries()
    df = filter_dataframe_by_period(
        df=df, date_column='date',
        week=week, month=month, year=year, days=days,
    )

    if df.empty:
        print('該当期間のエントリがありません', file=sys.stderr)
        sys.exit(1)

    start = df['date'].min().strftime('%Y-%m-%d')
    end = df['date'].max().strftime('%Y-%m-%d')

    if args.list:
        print(f"# Toggl エントリ一覧（{start} 〜 {end}）\n")
        print(render.render_entries(df))
        print()
        print("## プロジェクト別合計\n")
        print(render.render_project_totals(df))
        return

    df = render.add_bucket(df, args.unit)

    unit_label = '週次' if args.unit == 'week' else '日次'
    print(f"# Toggl サマリ（{unit_label}: {start} 〜 {end}）\n")

    print(f"## {unit_label}合計\n")
    print(render.render_totals(df, args.unit))
    print()

    print("## プロジェクト別内訳\n")
    print(render.render_project_matrix(df, args.unit))
    print()

    print("## プロジェクト別合計（期間全体）\n")
    print(render.render_project_totals(df))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Toggl Track CLI（fetch / show）')
    subparsers = parser.add_subparsers(dest='command', required=True)

    fetch_parser = subparsers.add_parser('fetch', help='Toggl Trackタイムエントリ取得')
    fetch_parser.add_argument(
        '--update', action='store_true',
        help=f'CSV の最終エントリの{UPDATE_OVERLAP_DAYS}日前から今日まで取得（既存データが無ければ --days）')
    fetch_parser.add_argument('--days', type=int, default=7, help='取得日数（今日から遡る）')
    fetch_parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    fetch_parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    fetch_parser.set_defaults(func=cmd_fetch, parser=fetch_parser)

    show_parser = subparsers.add_parser('show', help='Toggl タイムエントリのサマリを表示')
    show_parser.add_argument('--unit', choices=['day', 'week'], default='day',
                              help='集計単位（デフォルト: day）')
    show_parser.add_argument('--days', type=int, default=None,
                              help='直近N日（--week/--month 未指定時のデフォルト: --list=1, day=7, week=28）')
    show_parser.add_argument('--week', type=str, default=None,
                              help='ISO週番号（例: 34）または "current"')
    show_parser.add_argument('--month', type=str, default=None,
                              help='月番号（例: 8）または "current"')
    show_parser.add_argument('--year', type=int, default=None,
                              help='年（--week/--month 指定時に使用）')
    show_parser.add_argument('--list', action='store_true',
                              help='集計せずエントリを時系列で一覧表示する')
    show_parser.add_argument('--update', action='store_true',
                              help='表示前に fetch --update で最新データを取得する')
    show_parser.set_defaults(func=cmd_show)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
