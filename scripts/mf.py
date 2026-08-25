#!/usr/bin/env python
# coding: utf-8
"""
MoneyForward ME CLI（fetch / show）

保存済みのブラウザセッションで月次 CSV を取得して年ごとの CSV に蓄積する fetch と、
data/mf/収入・支出詳細_YYYY.csv（dailybuild-private への symlink）を読んで
markdown サマリを出す show をまとめたスクリプト。

Usage:
    python scripts/mf.py fetch --login              # 初回・セッション切れ時
    python scripts/mf.py fetch                      # 直近3ヶ月
    python scripts/mf.py fetch --refresh            # 取得後に一括更新をキック（日次運用）
    python scripts/mf.py fetch --months 6
    python scripts/mf.py fetch --year 2025          # 2025年を丸ごと
    python scripts/mf.py fetch --start 2026-01 --end 2026-08

    python scripts/mf.py show                       # 月次（直近3ヶ月）
    python scripts/mf.py show --months 12
    python scripts/mf.py show --unit year           # 年次（全期間）
    python scripts/mf.py show --year 2018           # 2018年を丸ごと
    python scripts/mf.py show --month 1 --year 2026 # 指定月
    python scripts/mf.py show --unit day --days 14  # 日次
    python scripts/mf.py show --list                # 明細一覧
    python scripts/mf.py show --update              # 取得してから表示

show は既定では MF に一切アクセスしないので、セッション切れの影響を受けない。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import io
from typing import IO

import pandas as pd

from lib.mf import client as mf_client
from lib.mf import render, store
from lib.mf.client import MoneyForwardSession, NotLoggedInError
from lib.utils.report_args import filter_dataframe_by_period, parse_period_args

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / 'config' / 'mf_state.json'

# 連携が生きている状態。これ以外は明細が欠けている可能性がある
HEALTHY_STATUS = '正常'
# 更新実行中。異常ではないので警告しない
PENDING_STATUS = '更新中'

# 取得・表示の既定月数
DEFAULT_MONTHS = 3

# MF に明細が存在する最古の年（2015-02 が初出。それ以前は 0 件）。
# --unit year の既定期間を全期間にするために使う
EARLIEST_YEAR = 2015


def parse_month(text: str) -> dt.date:
    return dt.datetime.strptime(text, '%Y-%m').date().replace(day=1)


def resolve_months(args) -> list[tuple[int, int]]:
    """fetch の引数から取得対象の (year, month) リストを決定"""
    today = dt.date.today()

    if args.year:
        start = dt.date(args.year, 1, 1)
        # 未来の月は明細が無いので当月で打ち切る
        end = min(dt.date(args.year, 12, 1), today.replace(day=1))
        if end < start:
            raise SystemExit(f"{args.year} 年はまだ始まっていない")
        return mf_client.month_range(start, end)

    if args.start or args.end:
        if not (args.start and args.end):
            raise SystemExit('--start と --end は両方指定する')
        return mf_client.month_range(parse_month(args.start), parse_month(args.end))

    start = today.replace(day=1)
    for _ in range(args.months - 1):
        start = (start - dt.timedelta(days=1)).replace(day=1)
    return mf_client.month_range(start, today.replace(day=1))


def warn_unhealthy_accounts(accounts: list[tuple[str, str, str]], out: IO[str]) -> None:
    """連携が正常でない口座を警告する（黙って欠測させないため）"""
    unhealthy = [a for a in accounts
                 if a[2] not in (HEALTHY_STATUS, PENDING_STATUS)]
    if not unhealthy:
        return

    print(f"\n⚠️ 連携が正常でない口座が {len(unhealthy)}件。"
          "該当口座の明細は CSV から欠けている:", file=out)
    for name, fetched_at, status in unhealthy:
        print(f"  {name}  最終取得 {fetched_at}  [{status[:30]}]", file=out)
    print("  → MF の画面で再認証が必要（一括更新では直らない）", file=out)


def run_fetch(args, out: IO[str]) -> None:
    """fetch サブコマンドの処理本体。進捗はすべて out に出す"""
    if args.login:
        mf_client.login(STATE_FILE)
        return

    months = resolve_months(args)
    print(f"MoneyForward ME 取得: {months[0][0]}/{months[0][1]:02d} ～ "
          f"{months[-1][0]}/{months[-1][1]:02d} ({len(months)}ヶ月)", file=out)

    frames = []
    with MoneyForwardSession(STATE_FILE) as session:
        for year, month in months:
            text = session.fetch_month_csv(year, month)
            df_month = pd.read_csv(io.StringIO(text), dtype=str)
            print(f"  {year}/{month:02d}: {len(df_month)}件", file=out)
            frames.append(df_month)

        accounts = session.account_status()

        if args.refresh:
            session.kick_refresh()
            print("\n一括更新をキックした（完了は待たない）。"
                  "取り込まれた明細は次回の取得に乗る", file=out)

    df_new = pd.concat(frames, ignore_index=True)

    if df_new.empty:
        print("⚠️ 明細が0件。MF 側に記録が無いか、取得が壊れている可能性がある", file=out)
        return

    store.save_by_year(df_new, out)
    warn_unhealthy_accounts(accounts, out)


def fetch_args_for_update() -> argparse.Namespace:
    """show --update から呼ぶ fetch 相当の引数（既定の直近Nヶ月を取り直す）"""
    return argparse.Namespace(
        login=False, refresh=False, months=DEFAULT_MONTHS,
        year=None, start=None, end=None,
    )


def filter_recent_months(df: pd.DataFrame, months: int) -> pd.DataFrame:
    """直近Nヶ月（当月を含む）に絞る。

    report_args.filter_dataframe_by_period は日数・週・月指定しか扱えず
    「直近Nヶ月」に相当するものが無いため、ここで月境界を計算する。
    """
    this_month = pd.Timestamp.now().normalize().replace(day=1)
    start = this_month - pd.DateOffset(months=months - 1)
    # MF は引き落とし予定日の未来明細を含む。上限を当月末で切らないと
    # 「直近Nヶ月」に翌年の予定が紛れ込む
    end = this_month + pd.DateOffset(months=1) - pd.Timedelta(days=1)
    return df[(df['date'] >= start) & (df['date'] <= end)]


def default_months(args) -> int:
    """期間指定が無いときの既定月数。

    --unit year で直近3ヶ月だけ出しても年次の表にならないので、年次のときは
    全期間（MF の最古は 2015-02）を既定にする。
    """
    if args.unit == 'year':
        today = dt.date.today()
        return (today.year - EARLIEST_YEAR) * 12 + today.month
    return DEFAULT_MONTHS


def cmd_fetch(args) -> None:
    if args.login and (args.refresh or args.year or args.start or args.end):
        args.parser.error('--login は他のオプションと同時に指定できない')
    run_fetch(args, sys.stdout)


def cmd_show(args) -> None:
    if args.update:
        # show の parser は fetch のオプションを持たないため、fetch 相当の引数を組み立てる。
        # 取得ログは stderr に寄せて stdout を markdown 専用に保つ
        run_fetch(fetch_args_for_update(), sys.stderr)

    week, month, year = parse_period_args(args)

    df = store.load_entries()
    if df.empty:
        print(f"エラー: {store.DATA_DIR}/{store.CSV_GLOB} が存在しません", file=sys.stderr)
        sys.exit(1)

    if week is not None or month is not None or args.days is not None:
        df = filter_dataframe_by_period(
            df=df, date_column='date',
            week=week, month=month, year=year, days=args.days,
        )
    elif year is not None:
        # --year 単独。filter_dataframe_by_period は year だけでは絞れないので
        # ここで年を切る（黙って直近Nヶ月にフォールバックさせない）
        df = df[df['date'].dt.year == year]
    else:
        df = filter_recent_months(df, args.months or default_months(args))

    if df.empty:
        print('該当期間の明細がありません', file=sys.stderr)
        sys.exit(1)

    start = df['date'].min().strftime('%Y-%m-%d')
    end = df['date'].max().strftime('%Y-%m-%d')

    if args.list:
        print(f"# Money 明細一覧（{start} 〜 {end}）\n")
        print(render.render_entries(df))
        print()
        print("## カテゴリ別合計（支出）\n")
        print(render.render_totals(render.expenses(df), store.COL_CATEGORY, 'カテゴリ'))
        return

    df = render.add_bucket(df, args.unit)
    exp = render.expenses(df)

    unit_label = render.unit_label(args.unit)
    print(f"# Money サマリ（{unit_label}: {start} 〜 {end}）\n")

    print(f"## {unit_label}収支\n")
    print(render.render_balance(df, args.unit))
    print()

    print("## カテゴリ別内訳（支出）\n")
    print(render.render_category_matrix(exp, args.unit))
    print()

    print("## カテゴリ別合計（期間全体・支出）\n")
    print(render.render_totals(exp, store.COL_CATEGORY, 'カテゴリ'))
    print()

    print(f"## 中項目別（上位{args.top}・支出）\n")
    print(render.render_totals(
        exp, [store.COL_CATEGORY, store.COL_SUBCATEGORY], 'カテゴリ', top=args.top))
    print()

    print(f"## 店舗別（上位{args.top}・支出）\n")
    print(render.render_totals(exp, store.COL_NAME, '店舗', top=args.top))
    print()

    print("## 金融機関別（支出）\n")
    print(render.render_totals(exp, store.COL_ACCOUNT, '金融機関'))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='MoneyForward ME CLI（fetch / show）')
    subparsers = parser.add_subparsers(dest='command', required=True)

    fetch_parser = subparsers.add_parser('fetch', help='MoneyForward ME 収入・支出詳細取得')
    fetch_parser.add_argument('--login', action='store_true',
                              help='ブラウザを開いて手動ログインし、セッションを保存する')
    fetch_parser.add_argument('--refresh', action='store_true',
                              help='取得後に金融機関からのデータ一括更新をキックする（完了は待たない）')
    fetch_parser.add_argument('--months', type=int, default=DEFAULT_MONTHS,
                              help='取得月数（当月から遡る）')
    fetch_parser.add_argument('--year', type=int, help='指定年を丸ごと取得')
    fetch_parser.add_argument('--start', type=str, help='開始月（YYYY-MM）')
    fetch_parser.add_argument('--end', type=str, help='終了月（YYYY-MM）')
    fetch_parser.set_defaults(func=cmd_fetch, parser=fetch_parser)

    show_parser = subparsers.add_parser('show', help='MoneyForward ME 収入・支出のサマリを表示')
    show_parser.add_argument('--unit', choices=['day', 'week', 'month', 'year'],
                             default='month',
                             help='集計単位（デフォルト: month）')
    show_parser.add_argument('--months', type=int, default=None,
                             help=f'直近Nヶ月（--days/--week/--month 未指定時のデフォルト: {DEFAULT_MONTHS}）')
    show_parser.add_argument('--days', type=int, default=None,
                             help='直近N日')
    show_parser.add_argument('--week', type=str, default=None,
                             help='ISO週番号（例: 34）または "current"')
    show_parser.add_argument('--month', type=str, default=None,
                             help='月番号（例: 8）または "current"')
    show_parser.add_argument('--year', type=int, default=None,
                             help='年。単独指定でその年を丸ごと（--week/--month と併用も可）')
    show_parser.add_argument('--top', type=int, default=10,
                             help='中項目別・店舗別で表示する件数（デフォルト: 10）')
    show_parser.add_argument('--list', action='store_true',
                             help='集計せず明細を時系列で一覧表示する')
    show_parser.add_argument('--update', action='store_true',
                             help='表示前に fetch で最新データを取得する')
    show_parser.set_defaults(func=cmd_show)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    try:
        main()
    except NotLoggedInError as e:
        print(f"⚠️ {e}")
        sys.exit(1)
