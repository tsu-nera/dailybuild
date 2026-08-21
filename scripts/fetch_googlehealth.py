#!/usr/bin/env python
# coding: utf-8
"""
Google Health API からデータを取得して CSV に保存する

Fitbit Web API 廃止（2026年9月）への移行用。対応済みエンドポイントのみ扱う。

使い方:
    uv run python scripts/fetch_googlehealth.py --days 7
    uv run python scripts/fetch_googlehealth.py --start-date 2026-06-01
    uv run python scripts/fetch_googlehealth.py --endpoint hrv --days 30

初回はブラウザが開いて認可を求められる。以降は config/googlehealth_token.json を使う。
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib import googlehealth_fetcher  # noqa: E402
from lib.clients import googlehealth_api  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='Google Health データ取得')
    parser.add_argument('--days', type=int, default=7, help='取得日数（デフォルト: 7）')
    parser.add_argument('--start-date', type=str, help='開始日 YYYY-MM-DD（指定時は --days を無視）')
    parser.add_argument('--end-date', type=str, help='終了日 YYYY-MM-DD（未指定時は今日）')
    parser.add_argument('--endpoint', type=str, choices=googlehealth_fetcher.list_endpoints(),
                        help='特定のエンドポイントのみ取得')
    parser.add_argument('--overwrite', action='store_true', help='既存CSVを上書き（既定はマージ）')
    parser.add_argument('--allow-history-rewrite', action='store_true',
                        help='履歴境界より前も取得する（既存の過去の値が書き換わる。Issue #50）')
    args = parser.parse_args()

    start_date = dt.date.fromisoformat(args.start_date) if args.start_date else None
    end_date = dt.date.fromisoformat(args.end_date) if args.end_date else None

    print('=' * 70)
    print('Google Health データ取得')
    print('=' * 70)

    creds = googlehealth_api.authorize()

    if args.endpoint:
        results = {args.endpoint: googlehealth_fetcher.fetch_endpoint(
            creds, args.endpoint, days=args.days, overwrite=args.overwrite,
            start_date=start_date, end_date=end_date,
            allow_history_rewrite=args.allow_history_rewrite,
        )}
    else:
        results = googlehealth_fetcher.fetch_all(
            creds, days=args.days, overwrite=args.overwrite,
            start_date=start_date, end_date=end_date,
            allow_history_rewrite=args.allow_history_rewrite,
        )

    print()
    errors = {k: v['error'] for k, v in results.items() if v.get('error')}
    for endpoint, result in results.items():
        mark = '✗' if result.get('error') else '○'
        print(f"  {mark} {endpoint:<20} {result['records']}件")

    if errors:
        print(f'\n{len(errors)}件のエラー:')
        for endpoint, msg in errors.items():
            print(f'  {endpoint}: {msg}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
