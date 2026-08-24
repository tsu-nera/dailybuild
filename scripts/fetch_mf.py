#!/usr/bin/env python
# coding: utf-8
"""
MoneyForward ME 収入・支出詳細取得スクリプト

保存済みのブラウザセッションで月次 CSV を取得し、年ごとの CSV に蓄積する。
既存行との重複判定は MF 側の ID で行うため、後から編集・分類変更された
明細は上書きされる（削除された明細は CSV に残り続ける）。

MF 側が金融機関から取り込んだ分しか CSV には出ない。--refresh を付けると
取得後に一括更新をキックする。更新は非同期でカード会社は10分以上かかることが
あるため完了は待たず、その結果は次回の取得で回収する（実質1日遅れ）。

Usage:
    uv run scripts/fetch_mf.py --login              # 初回・セッション切れ時
    uv run scripts/fetch_mf.py                      # 直近3ヶ月
    uv run scripts/fetch_mf.py --refresh            # 取得後に一括更新をキック（日次運用）
    uv run scripts/fetch_mf.py --months 6
    uv run scripts/fetch_mf.py --year 2025          # 2025年を丸ごと
    uv run scripts/fetch_mf.py --start 2026-01 --end 2026-08
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import io

import pandas as pd

from lib.clients import mf_client
from lib.clients.mf_client import MoneyForwardSession, NotLoggedInError
from lib.utils import csv_utils
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / 'config' / 'mf_state.json'
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
DATA_DIR = require_private_path(BASE_DIR / 'data' / 'mf')

# 連携が生きている状態。これ以外は明細が欠けている可能性がある
HEALTHY_STATUS = '正常'
# 更新実行中。異常ではないので警告しない
PENDING_STATUS = '更新中'

DATE_COLUMN = '日付'
KEY_COLUMN = 'ID'
# 既存ファイルに合わせる（Excel で開けるよう BOM 付き）
OUTPUT_ENCODING = 'utf-8-sig'


def csv_path(year: int) -> Path:
    return DATA_DIR / f'収入・支出詳細_{year}.csv'


def parse_month(text: str) -> dt.date:
    return dt.datetime.strptime(text, '%Y-%m').date().replace(day=1)


def resolve_months(args) -> list[tuple[int, int]]:
    """引数から取得対象の (year, month) リストを決定"""
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


def save_by_year(df_new: pd.DataFrame) -> None:
    """明細を日付の年ごとに振り分けて既存 CSV とマージ保存する"""
    years = pd.to_datetime(df_new[DATE_COLUMN], format='%Y/%m/%d').dt.year

    for year, df_year in df_new.groupby(years):
        path = csv_path(year)
        df_merged = csv_utils.merge_csv_by_columns(
            df_year, path, key_columns=[KEY_COLUMN], sort_by=[DATE_COLUMN],
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df_merged.to_csv(path, index=False, encoding=OUTPUT_ENCODING)
        print(f"保存完了: {path} (総行数 {len(df_merged)}行)")


def warn_unhealthy_accounts(accounts: list[tuple[str, str, str]]) -> None:
    """連携が正常でない口座を警告する（黙って欠測させないため）"""
    unhealthy = [a for a in accounts
                 if a[2] not in (HEALTHY_STATUS, PENDING_STATUS)]
    if not unhealthy:
        return

    print(f"\n⚠️ 連携が正常でない口座が {len(unhealthy)}件。"
          "該当口座の明細は CSV から欠けている:")
    for name, fetched_at, status in unhealthy:
        print(f"  {name}  最終取得 {fetched_at}  [{status[:30]}]")
    print("  → MF の画面で再認証が必要（一括更新では直らない）")


def main():
    parser = argparse.ArgumentParser(description='MoneyForward ME 収入・支出詳細取得')
    parser.add_argument('--login', action='store_true',
                        help='ブラウザを開いて手動ログインし、セッションを保存する')
    parser.add_argument('--refresh', action='store_true',
                        help='取得後に金融機関からのデータ一括更新をキックする（完了は待たない）')
    parser.add_argument('--months', type=int, default=3,
                        help='取得月数（当月から遡る）')
    parser.add_argument('--year', type=int, help='指定年を丸ごと取得')
    parser.add_argument('--start', type=str, help='開始月（YYYY-MM）')
    parser.add_argument('--end', type=str, help='終了月（YYYY-MM）')
    args = parser.parse_args()

    if args.login:
        mf_client.login(STATE_FILE)
        return

    months = resolve_months(args)
    print(f"MoneyForward ME 取得: {months[0][0]}/{months[0][1]:02d} ～ "
          f"{months[-1][0]}/{months[-1][1]:02d} ({len(months)}ヶ月)")

    frames = []
    with MoneyForwardSession(STATE_FILE) as session:
        for year, month in months:
            text = session.fetch_month_csv(year, month)
            df_month = pd.read_csv(io.StringIO(text), dtype=str)
            print(f"  {year}/{month:02d}: {len(df_month)}件")
            frames.append(df_month)

        accounts = session.account_status()

        if args.refresh:
            session.kick_refresh()
            print("\n一括更新をキックした（完了は待たない）。"
                  "取り込まれた明細は次回の取得に乗る")

    df_new = pd.concat(frames, ignore_index=True)

    if df_new.empty:
        print("⚠️ 明細が0件。MF 側に記録が無いか、取得が壊れている可能性がある")
        return

    save_by_year(df_new)
    warn_unhealthy_accounts(accounts)


if __name__ == '__main__':
    try:
        main()
    except NotLoggedInError as e:
        print(f"⚠️ {e}")
        sys.exit(1)
