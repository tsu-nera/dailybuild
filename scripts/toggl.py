#!/usr/bin/env python
# coding: utf-8
"""
Toggl CLI（fetch-focus / show / push / start / stop / fetch）

2026-10-27 で Track を凍結し、書き込み（push / start / stop）と日次の取得は
Toggl 2.0（Focus）に移した。fetch は Track のアーカイブ（time_entries.csv）を
取り直すための手段として残してあり、日次には入っていない。
show は区切り日（lib.toggl.store.CUTOVER_DATE）の前を time_entries.csv、
以降を focus_entries.csv から連結して表示する。

Usage:
    python scripts/toggl.py fetch-focus --update      # Toggl 2.0 → focus_entries.csv（続きから今日まで）
    python scripts/toggl.py fetch-focus --days 2
    python scripts/toggl.py fetch --days 7            # Track アーカイブの取り直し（凍結済み）

    python scripts/toggl.py show --days 7             # 日次（直近7日）
    python scripts/toggl.py show --update             # fetch-focus してから表示
    python scripts/toggl.py show --list               # 時系列のエントリ一覧
    python scripts/toggl.py show --unit week --days 56  # 週次
    python scripts/toggl.py show --week current
    python scripts/toggl.py show --month 8

    python scripts/toggl.py push --days 2 --dry-run   # 投入予定を確認（APIを叩かない）
    python scripts/toggl.py push --days 2             # Google Health睡眠・運動と Muse の瞑想（satoru）を 2.0 へ投入
    python scripts/toggl.py push --since 2026-10-27   # 区切り日以降の一括投入

    python scripts/toggl.py start 読書                # プロジェクトを指定して計測開始
    python scripts/toggl.py start 読書 -d "SICP" -t deep   # タグは focus_tags.json から引く
    python scripts/toggl.py stop                      # 計測中のエントリを停止
    python scripts/toggl.py current                   # 計測中のエントリを表示
    python scripts/toggl.py projects                  # プロジェクト名の一覧（キャッシュ）
    python scripts/toggl.py open                      # Toggl 2.0 の Web 画面を開く

show は既定では API を一切叩かない。push の書き込みも 2.0 のレート制限
（30 req/h と仮定）を消費する。
"""

import argparse
import datetime as dt
import logging
import sys
import webbrowser
from pathlib import Path
from typing import IO

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.toggl import client as toggl_client
from lib.toggl import focus as toggl_focus
from lib.toggl import push as toggl_push
from lib.toggl import sources as toggl_sources
from lib.toggl import store
from lib.toggl import render
from lib.toggl import timer as toggl_timer
from lib.utils.env import MissingEnvError, require_env
from lib.utils.report_args import filter_dataframe_by_period, parse_period_args

BASE_DIR = Path(__file__).parent.parent
# --update で CSV の最終日から遡って取り直す日数。
# 過去日のエントリを後から追加・編集することがあるため、最終日ちょうどではなく
# 少し重ねて取る（マージは id で keep='last' なので編集は上書きされる）
UPDATE_OVERLAP_DAYS = 2


def load_api_token(out: IO[str]) -> str:
    try:
        return require_env('TOGGL_API_TOKEN',
                           hint='https://track.toggl.com/profile の API Token')
    except MissingEnvError as exc:
        print(f"⚠️ {exc}", file=out)
        sys.exit(1)


def resolve_period(args, out: IO[str], csv_path: Path | None = None) -> tuple[dt.date, dt.date]:
    """fetch の引数から取得期間を決定（--update は csv_path、既定 time_entries.csv の続きから）"""
    end = dt.date.today()

    if args.start_date and args.end_date:
        return (dt.datetime.strptime(args.start_date, '%Y-%m-%d').date(),
                dt.datetime.strptime(args.end_date, '%Y-%m-%d').date())

    if args.update:
        last = store.last_recorded_date(csv_path)
        if last is None:
            print(f"CSV に既存データが無いため直近 {args.days} 日を取得する", file=out)
        else:
            # 期間が長くてもリクエスト数は変わらないので、素直に最終日まで遡る
            start = last - dt.timedelta(days=UPDATE_OVERLAP_DAYS)
            return min(start, end), end

    return end - dt.timedelta(days=args.days - 1), end


def run_fetch(args, out: IO[str]) -> None:
    """fetch（Track アーカイブ）の処理本体。進捗はすべて out に出す"""
    # toggl_client がクォータ残量を logger.info で出す。設定しないと握り潰される
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=out)

    api_token = load_api_token(out)

    start, end = resolve_period(args, out)
    print(f"Togglタイムエントリ取得: {start} ～ {end}", file=out)

    tz = toggl_push.load_timezone()
    entries = toggl_client.fetch_time_entries(api_token, start, end, tz)
    projects = toggl_client.fetch_projects(api_token)

    df_new = store.build_dataframe(entries, projects)

    if df_new.empty:
        print(f"⚠️ 期間 {start}〜{end} のタイムエントリが0件。"
              "Toggl側に記録が無いか、取得が壊れている可能性がある", file=out)
        return

    df_merged = store.save_merged(df_new, window=(start, end))

    period_min = df_merged['start'].min()
    period_max = df_merged['start'].max()
    print(f"取得件数: {len(df_new)}件", file=out)
    print(f"保存完了: {store.CSV_FILE} (総行数 {len(df_merged)}行)", file=out)
    print(f"CSVの期間: {period_min} ～ {period_max}", file=out)


def fetch_args_for_update() -> argparse.Namespace:
    """show --update から呼ぶ fetch-focus --update 相当の引数

    days は CSV が空のときのフォールバックにしか使われない（fetch の既定値と揃える）
    """
    return argparse.Namespace(update=True, days=7, start_date=None, end_date=None)


def cmd_fetch(args) -> None:
    if args.update and (args.start_date or args.end_date):
        args.parser.error('--update と --start-date/--end-date は同時に指定できない')
    run_fetch(args, sys.stdout)


def load_focus_env(out: IO[str]) -> tuple[str, str, str]:
    hint = '.env.example の Toggl 2.0 の節を参照'
    try:
        return (require_env('TOGGL_FOCUS_API_TOKEN', hint=hint),
                require_env('TOGGL_FOCUS_ORGANIZATION_ID', hint=hint),
                require_env('TOGGL_FOCUS_WORKSPACE_ID', hint=hint))
    except MissingEnvError as exc:
        print(f"⚠️ {exc}", file=out)
        sys.exit(1)


def load_workspace(out: IO[str]) -> toggl_focus.Workspace:
    return toggl_focus.Workspace(*load_focus_env(out))


def run_fetch_focus(args, out: IO[str]) -> None:
    """fetch-focus の処理本体。取得したエントリのタグ（名前 → ID）も focus_tags.json に貯める"""
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=out)

    api_token, organization_id, workspace_id = load_focus_env(out)

    start, end = resolve_period(args, out, csv_path=toggl_focus.CSV_FILE)
    print(f"Toggl 2.0 タイムエントリ取得: {start} ～ {end}", file=out)

    entries = toggl_focus.fetch_time_entries(api_token, organization_id, workspace_id, start, end)
    # push・start がタグ名から ID を引くための対応。0件の窓でも既存の対応は縮めない
    toggl_focus.save_tags(toggl_focus.collect_tags(entries))
    df_new = toggl_focus.build_dataframe(entries, workspace_id=int(workspace_id))

    if df_new.empty:
        print(f"⚠️ 期間 {start}〜{end} の Toggl 2.0 タイムエントリが0件。"
              "記録が無いか、取得が壊れている可能性がある", file=out)
        return

    df_merged = toggl_focus.save_merged(df_new, window=(start, end))

    print(f"取得件数: {len(df_new)}件", file=out)
    print(f"保存完了: {toggl_focus.CSV_FILE} (総行数 {len(df_merged)}行)", file=out)
    print(f"CSVの期間: {df_merged['start'].min()} ～ {df_merged['start'].max()}", file=out)


def cmd_fetch_focus(args) -> None:
    if args.update and (args.start_date or args.end_date):
        args.parser.error('--update と --start-date/--end-date は同時に指定できない')
    run_fetch_focus(args, sys.stdout)


def cmd_show(args) -> None:
    if args.update:
        # show の parser は fetch のオプションを持たないため、fetch 相当の引数を組み立てる。
        # 取得ログは stderr に寄せて stdout を markdown 専用に保つ
        run_fetch_focus(fetch_args_for_update(), sys.stderr)

    if not store.CSV_FILE.exists() and not store.FOCUS_CSV_FILE.exists():
        print(f"エラー: {store.CSV_FILE} も {store.FOCUS_CSV_FILE} も存在しません", file=sys.stderr)
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


PUSH_DEFAULT_DAYS = 2


def resolve_push_period(args) -> tuple[dt.date, dt.date]:
    """push の引数から対象期間を決定。--days と --since は排他"""
    today = dt.date.today()
    if args.since:
        return dt.datetime.strptime(args.since, '%Y-%m-%d').date(), today
    days = args.days if args.days is not None else PUSH_DEFAULT_DAYS
    return today - dt.timedelta(days=days - 1), today


def cmd_push(args) -> None:
    if args.since and args.days is not None:
        args.parser.error('--since と --days は同時に指定できない')
    run_push(args, sys.stdout)


def run_push(args, out: IO[str]) -> None:
    """push サブコマンドの処理本体"""
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=out)

    since, until = resolve_push_period(args)
    print(f"Toggl 2.0 push 対象期間: {since} ～ {until}", file=out)

    config = toggl_push.load_push_config()
    tz = toggl_push.load_timezone()

    intervals: list[toggl_push.Interval] = []
    for source_name, source_fn in toggl_sources.SOURCES.items():
        source_config = config.get('sources', {}).get(source_name, {})
        if not source_config.get('enabled', False):
            continue
        intervals.extend(source_fn(since, until, config, tz))

    if not intervals:
        print("⚠️ 投入対象のソースデータが0件。取得が壊れている可能性がある", file=out)
        return

    focus_df = toggl_push.load_focus_entries_for_match()
    if focus_df is None or focus_df.empty:
        print("⚠️ focus_entries.csv が無いか空。台帳だけで判定するので、"
              "migrate 済み・手入力のエントリと二重になりうる。fetch-focus を先に回す", file=out)
    else:
        earliest = focus_df['start'].min().date()
        from_date = max(since, store.CUTOVER_DATE)
        if earliest > from_date:
            print(f"⚠️ focus_entries.csv が {earliest} から始まっていて、投入対象の開始 {from_date} を"
                  "覆っていない。その範囲の照合ができないので fetch-focus --start-date で取り直す", file=out)

    ledger_df = toggl_push.load_ledger()

    workspace = None
    if not args.dry_run:
        workspace = load_workspace(out)

    result = toggl_push.push_intervals(
        intervals=intervals,
        ledger_df=ledger_df,
        focus_df=focus_df,
        max_writes=args.max_writes,
        dry_run=args.dry_run,
        workspace=workspace,
        out=out,
    )

    pending = result['pending']
    skipped = result['skipped']
    carried_over = result['carried_over']

    if args.dry_run:
        to_push = result.get('to_push', [])
        print(f"投入予定: {len(to_push)}件（スキップ {skipped}件 / 上限 {args.max_writes}）", file=out)
        for interval in to_push:
            duration = interval.stop - interval.start
            hours, remainder = divmod(int(duration.total_seconds()), 3600)
            minutes = remainder // 60
            print(
                f"  {interval.start.strftime('%Y-%m-%d %H:%M:%S')} 〜 "
                f"{interval.stop.strftime('%Y-%m-%d %H:%M:%S')} "
                f"({hours}h{minutes}m) [{interval.project}] {interval.description} "
                f"#{interval.source}/{interval.source_id}",
                file=out,
            )
        if carried_over:
            print(f"⚠️ 上限 {args.max_writes} 件に達した。残り {len(carried_over)} 件を次回に繰り越し", file=out)
        return

    pushed = result['pushed']
    print(f"投入: {pushed}件 / スキップ: {skipped}件 / 対象: {len(pending)}件", file=out)
    if carried_over:
        print(f"⚠️ 上限 {args.max_writes} 件に達した。残り {len(carried_over)} 件を次回に繰り越し", file=out)


def load_projects_for_timer(workspace: toggl_focus.Workspace, out: IO[str],
                            refresh: bool = False) -> tuple[dict[int, str], bool]:
    """({project_id: name}, キャッシュ由来か)。キャッシュがあれば API を叩かない"""
    if not refresh:
        cached = toggl_timer.load_project_cache()
        if cached is not None:
            return cached[1], True

    projects = toggl_focus.fetch_projects(workspace)
    toggl_timer.save_project_cache(int(workspace.workspace_id), projects)
    print(f"プロジェクト一覧を更新: {len(projects)}件 ({toggl_timer.PROJECTS_CACHE_FILE})", file=out)
    return projects, False


def parse_tags(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(tag.strip() for tag in value.split(',') if tag.strip())


def cmd_start(args) -> None:
    # 進捗・クォータ残量は stderr。stdout には結果の1行だけを出す
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)

    try:
        tag_ids = toggl_timer.resolve_tags(parse_tags(args.tags), toggl_focus.load_tags())
    except toggl_timer.TagResolutionError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    workspace = load_workspace(sys.stderr)

    projects, from_cache = load_projects_for_timer(workspace, sys.stderr, refresh=args.refresh_projects)
    try:
        project_id, project_name = toggl_timer.resolve_project(args.project, projects)
    except toggl_timer.ProjectResolutionError as e:
        # キャッシュが古くて新規プロジェクトを知らないだけの可能性がある。
        # 一度だけ取り直して再試行する（候補が複数のときは取り直しても解決しない）
        if not from_cache:
            print(f"エラー: {e}", file=sys.stderr)
            sys.exit(1)
        print(f"{e}。プロジェクト一覧を取り直す", file=sys.stderr)
        projects, _ = load_projects_for_timer(workspace, sys.stderr, refresh=True)
        try:
            project_id, project_name = toggl_timer.resolve_project(args.project, projects)
        except toggl_timer.ProjectResolutionError as e2:
            print(f"エラー: {e2}", file=sys.stderr)
            sys.exit(1)

    payload = toggl_timer.build_start_payload(
        project_id=project_id,
        description=args.description or project_name,
        tag_ids=tag_ids,
    )
    now = dt.datetime.now(store.JST)

    if args.dry_run:
        print(f"[dry-run] 計測開始しない: [{project_name}] {payload['description']} "
              f"tags={list(parse_tags(args.tags))} at {now.strftime('%H:%M:%S')}")
        return

    created = toggl_focus.start_tracking(workspace, payload)
    print(f"計測開始 {now.strftime('%H:%M:%S')}: [{project_name}] "
          f"{payload['description']} (id={created.get('id')})")


def cmd_stop(args) -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)

    workspace = load_workspace(sys.stderr)

    entry = toggl_focus.fetch_current(workspace)
    if entry is None:
        print('計測中のエントリは無い', file=sys.stderr)
        sys.exit(1)

    cached = toggl_timer.load_project_cache()
    projects = cached[1] if cached else {}
    now = dt.datetime.now(dt.timezone.utc)

    if args.dry_run:
        print(f"[dry-run] 停止しない: {toggl_timer.describe_entry(entry, projects, now)}")
        return

    stopped = toggl_focus.stop_tracking(workspace, now)
    duration = stopped.get('duration') or toggl_timer.elapsed_seconds(entry, now)
    project = toggl_timer.describe_project(entry.get('project_id'), projects)
    print(f"計測停止 {dt.datetime.now(store.JST).strftime('%H:%M:%S')}: "
          f"[{project}] {stopped.get('description') or ''} "
          f"({toggl_timer.format_elapsed(int(duration))})")


def cmd_current(args) -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)

    entry = toggl_focus.fetch_current(load_workspace(sys.stderr))
    if entry is None:
        print('計測中のエントリは無い')
        return

    cached = toggl_timer.load_project_cache()
    projects = cached[1] if cached else {}
    print(toggl_timer.describe_entry(entry, projects, dt.datetime.now(dt.timezone.utc)))


def cmd_projects(args) -> None:
    """キャッシュ済みのプロジェクト一覧を出す（--refresh でAPIから取り直す）"""
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)

    cached = toggl_timer.load_project_cache()
    if args.refresh or cached is None:
        projects, _ = load_projects_for_timer(load_workspace(sys.stderr), sys.stderr, refresh=True)
    else:
        projects = cached[1]

    for name in sorted(projects.values()):
        print(name)


def cmd_open(args) -> None:
    """Toggl 2.0 の Web 画面を既定ブラウザで開く（API は叩かないのでクォータ消費なし）"""
    url = toggl_timer.WEB_URL
    if args.print_url:
        print(url)
        return
    if not webbrowser.open(url):
        # SSH 越しなど、開ける相手が居ない環境。黙って成功しない
        print(f"エラー: ブラウザを開けなかった。URL: {url}", file=sys.stderr)
        sys.exit(1)
    print(f"開いた: {url}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Toggl CLI（fetch-focus / show / push / start / stop）')
    subparsers = parser.add_subparsers(dest='command', required=True)

    fetch_parser = subparsers.add_parser('fetch', help='Toggl Track タイムエントリ取得（凍結済みアーカイブの取り直し）')
    fetch_parser.add_argument(
        '--update', action='store_true',
        help=f'CSV の最終エントリの{UPDATE_OVERLAP_DAYS}日前から今日まで取得（既存データが無ければ --days）')
    fetch_parser.add_argument('--days', type=int, default=7, help='取得日数（今日から遡る）')
    fetch_parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    fetch_parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    fetch_parser.set_defaults(func=cmd_fetch, parser=fetch_parser)

    focus_parser = subparsers.add_parser(
        'fetch-focus', help='Toggl 2.0（Focus）のタイムエントリを focus_entries.csv へ取得')
    focus_parser.add_argument(
        '--update', action='store_true',
        help=f'CSV の最終エントリの{UPDATE_OVERLAP_DAYS}日前から今日まで取得（既存データが無ければ --days）')
    focus_parser.add_argument('--days', type=int, default=7, help='取得日数（今日から遡る）')
    focus_parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    focus_parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    focus_parser.set_defaults(func=cmd_fetch_focus, parser=focus_parser)

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
                              help='表示前に fetch-focus --update で最新データを取得する')
    show_parser.set_defaults(func=cmd_show)

    push_parser = subparsers.add_parser('push', help='Google Health睡眠等を Toggl 2.0 のタイムエントリとして投入')
    push_parser.add_argument('--days', type=int, default=None,
                              help=f'対象日数（今日から遡る。既定 {PUSH_DEFAULT_DAYS}）')
    push_parser.add_argument('--since', type=str, default=None,
                              help='開始日（YYYY-MM-DD）から今日までの一括投入モード')
    push_parser.add_argument('--max-writes', type=int, default=toggl_push.DEFAULT_MAX_WRITES,
                              help=f'1実行あたりの書き込み上限（既定 {toggl_push.DEFAULT_MAX_WRITES}）')
    push_parser.add_argument('--dry-run', action='store_true',
                              help='投入予定を表示するだけでAPIを叩かない')
    push_parser.set_defaults(func=cmd_push, parser=push_parser)

    start_parser = subparsers.add_parser('start', help='指定プロジェクトの計測を開始')
    start_parser.add_argument('project', type=str, help='プロジェクト名（部分一致可）')
    start_parser.add_argument('-d', '--description', type=str, default=None,
                              help='エントリの説明（既定: プロジェクト名）')
    start_parser.add_argument('-t', '--tags', type=str, default=None,
                              help='タグ（カンマ区切り）')
    start_parser.add_argument('--refresh-projects', action='store_true',
                              help='プロジェクト一覧のキャッシュを取り直してから開始する')
    start_parser.add_argument('--dry-run', action='store_true',
                              help='開始予定を表示するだけで書き込まない')
    start_parser.set_defaults(func=cmd_start, parser=start_parser)

    stop_parser = subparsers.add_parser('stop', help='計測中のエントリを停止')
    stop_parser.add_argument('--dry-run', action='store_true',
                             help='停止対象を表示するだけで書き込まない')
    stop_parser.set_defaults(func=cmd_stop, parser=stop_parser)

    current_parser = subparsers.add_parser('current', help='計測中のエントリを表示')
    current_parser.set_defaults(func=cmd_current, parser=current_parser)

    projects_parser = subparsers.add_parser('projects', help='プロジェクト名の一覧を表示')
    projects_parser.add_argument('--refresh', action='store_true',
                                 help='APIから取り直す')
    projects_parser.set_defaults(func=cmd_projects, parser=projects_parser)

    open_parser = subparsers.add_parser('open', help='Toggl 2.0 の Web 画面をブラウザで開く')
    open_parser.add_argument('--print', dest='print_url', action='store_true',
                             help='開かずに URL を出力する')
    open_parser.set_defaults(func=cmd_open, parser=open_parser)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
