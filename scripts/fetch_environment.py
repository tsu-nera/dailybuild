#!/usr/bin/env python
# coding: utf-8
"""
室内環境データ取得スクリプト（Tuya Cloud / CO2・温度・湿度）

Usage:
    uv run scripts/fetch_environment.py --update        # CSVの最終時刻から今まで（日次運用）
    uv run scripts/fetch_environment.py --days 1        # 直近1日
    uv run scripts/fetch_environment.py --start-date 2026-08-25 --end-date 2026-08-26
    uv run scripts/fetch_environment.py --interval-min 10
    uv run scripts/fetch_environment.py --raw           # DPコードの一覧を表示

Tuya のログ API は最大7日しか遡れないため、日次実行で差分を蓄積する前提。
取得済みの境界は既定でスキップするので、再実行は安く済む（`--force` で取り直す）。
ただし**欠測だった境界はスキップ対象にならず毎回引き直す**（CSVに行が無いため）。
過去の長いオフライン区間を含む範囲を `--days` で指定すると、そこを毎回舐めることになる。
日次は `--update` を使えば新しい時間帯しか見ないのでこの影響を受けない。

ログ照会にはレート制限があり、1リクエストあたり実測1.3秒前後かかる。
5分刻みで1日288点だと十数分かかるため、日次では `--update` を使う。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import logging

import pandas as pd

from lib.clients.tuya_client import (
    CODE_TO_COLUMN,
    WINDOW_SEC,
    TuyaEnvironmentClient,
    TuyaError,
    load_credentials,
)
from lib.utils.csv_utils import merge_csv_by_columns
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config' / 'tuya_creds.json'
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'environment.csv')

COLUMNS = ['datetime'] + list(CODE_TO_COLUMN.values())

# Tuya のログ保持期間。これより古い範囲を指定しても返ってこない。
MAX_LOOKBACK_DAYS = 7


def load_existing() -> tuple[set, dt.datetime | None]:
    """既存CSVの datetime 集合と最終時刻を返す"""
    if not CSV_FILE.exists():
        return set(), None
    df = pd.read_csv(CSV_FILE, usecols=['datetime'], parse_dates=['datetime'])
    if df.empty:
        return set(), None
    return set(df['datetime']), df['datetime'].max().to_pydatetime()


def resolve_period(args, last_seen: dt.datetime | None) -> tuple[dt.datetime, dt.datetime]:
    """引数から取得期間を決定する（JST tz-naive）"""
    now = dt.datetime.now()
    if args.start_date and args.end_date:
        start = dt.datetime.strptime(args.start_date, '%Y-%m-%d')
        end = dt.datetime.strptime(args.end_date, '%Y-%m-%d') + dt.timedelta(days=1)
        return start, min(end, now)
    if args.update and last_seen is not None:
        return last_seen, now
    return now - dt.timedelta(days=args.days), now


def boundaries(start: dt.datetime, end: dt.datetime, interval_min: int) -> list[dt.datetime]:
    """interval_min 刻みの境界を並べる（境界は時刻の切りの良い位置に揃える）"""
    step = dt.timedelta(minutes=interval_min)
    epoch = start.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = (start - epoch) // step
    first = epoch + step * offset
    if first < start:
        first += step
    out = []
    cursor = first
    while cursor < end:
        out.append(cursor)
        cursor += step
    return out


def run_raw(client: TuyaEnvironmentClient) -> int:
    """生ログの code と値のサンプルを表示する（マッピング同定用）"""
    start = dt.datetime.now() - dt.timedelta(minutes=5)
    samples = client.raw_codes(start, width_sec=300)
    if not samples:
        print("直近5分に記録がありません。デバイスがオフラインの可能性があります。",
              file=sys.stderr)
        return 1
    print(f"{start:%Y-%m-%d %H:%M} からの5分間に出現した DP コード:")
    for code, values in sorted(samples.items()):
        uniq = sorted(set(values))
        mapped = CODE_TO_COLUMN.get(code, '(未マッピング)')
        print(f"  {code:20} → {mapped:12} {len(values):4}件  例 {uniq[:6]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='室内環境データ取得（Tuya Cloud）')
    parser.add_argument('--days', '-d', type=int, default=1,
                        help=f'取得日数（今から遡る、最大{MAX_LOOKBACK_DAYS}）')
    parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    parser.add_argument('--interval-min', type=int, default=5,
                        help='サンプリング間隔（分）')
    parser.add_argument('--window-sec', type=int, default=WINDOW_SEC,
                        help='各境界で平均を取る窓の幅（秒）')
    parser.add_argument('--update', action='store_true',
                        help='CSVの最終時刻から今までを取得（日次運用向けの差分取得）')
    parser.add_argument('--force', action='store_true',
                        help='取得済みの境界も取り直す')
    parser.add_argument('--raw', action='store_true',
                        help='生ログの DP コード一覧を表示して終了')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)

    try:
        client = TuyaEnvironmentClient(load_credentials(CREDS_FILE))
    except TuyaError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.raw:
        try:
            return run_raw(client)
        except TuyaError as exc:
            print(exc, file=sys.stderr)
            return 1

    existing, last_seen = load_existing()
    start, end = resolve_period(args, last_seen)
    oldest = dt.datetime.now() - dt.timedelta(days=MAX_LOOKBACK_DAYS)
    if start < oldest:
        print(f"警告: Tuya のログは最大{MAX_LOOKBACK_DAYS}日分しか遡れないため "
              f"{oldest:%Y-%m-%d %H:%M} に切り詰める", file=sys.stderr)
        start = oldest

    now = dt.datetime.now()
    points = boundaries(start, end, args.interval_min)
    # 窓がまだ閉じていない境界は取らない。取ると途中までの平均が確定値として
    # CSV に載り、以後 existing に入って二度と取り直されなくなる。
    points = [p for p in points
              if p + dt.timedelta(seconds=args.window_sec) <= now]
    total = len(points)
    if not args.force:
        points = [p for p in points if p not in existing]

    print(f"室内環境データ取得: {start:%Y-%m-%d %H:%M} ～ {end:%Y-%m-%d %H:%M} "
          f"({args.interval_min}分刻み / {len(points)}点"
          f"{f' / 取得済み {total - len(points)}点をスキップ' if total != len(points) else ''})",
          file=sys.stderr)

    if not points:
        print("取得対象の境界がありません（すべて取得済み）", file=sys.stderr)
        return 0

    rows = []
    empty = 0
    try:
        for i, point in enumerate(points, 1):
            row = client.sample_window(point, args.window_sec)
            if row is None:
                empty += 1
            else:
                rows.append(row)
            if i % 50 == 0 or i == len(points):
                print(f"  {i}/{len(points)} 取得済み（欠測 {empty}）", file=sys.stderr)
    except TuyaError as exc:
        print(exc, file=sys.stderr)
        return 1

    if not rows:
        print(f"取得0件（{len(points)}点すべて欠測）。デバイスがオフラインか、"
              f"指定期間に記録がありません。", file=sys.stderr)
        return 1

    if empty:
        # 一部が欠測なのはデバイスのオフライン時間として正常。補間せず穴のまま残す。
        print(f"欠測 {empty}/{len(points)} 点（デバイスのオフライン時間。補間しない）",
              file=sys.stderr)

    df_new = pd.DataFrame(rows, columns=COLUMNS)
    df_combined = merge_csv_by_columns(
        df_new, CSV_FILE, key_columns=['datetime'],
        parse_dates=['datetime'], sort_by=['datetime'])

    ensure_dir(CSV_FILE.parent)
    df_combined.to_csv(CSV_FILE, index=False, date_format='%Y-%m-%d %H:%M:%S')
    print(f"保存完了: {CSV_FILE} ({len(df_combined)}行)", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
