#!/usr/bin/env python
# coding: utf-8
"""
食事記録 CLI（build-master）

食品マスタは文部科学省「日本食品標準成分表（八訂）増補2023年」から作る。
市販の冷凍食品・加工食品は成分表に載らないので、パッケージの栄養成分表示から
可食部100g当たりで別途登録する（source=manual）。マスタを作り直しても
手入力分が消えないよう、既存 CSV の source=mext 以外の行は残す。

Usage:
    python scripts/food.py build-master              # 成分表から食品マスタを生成
    python scripts/food.py build-master --refresh    # 成分表 Excel を取り直す
    python scripts/food.py build-master --xlsx path/to/seibun.xlsx
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd

from lib.food import mext
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
XLSX_CACHE = BASE_DIR / 'tmp' / 'mext_seibun.xlsx'
NUTRITION_DIR = BASE_DIR / 'data' / 'nutrition'
MASTER_CSV = require_private_path(NUTRITION_DIR / 'foods_master.csv')


def cmd_build_master(args):
    xlsx = Path(args.xlsx) if args.xlsx else XLSX_CACHE
    if args.xlsx:
        if not xlsx.exists():
            print(f"エラー: ファイルがありません: {xlsx}", file=sys.stderr)
            return 1
    else:
        print(f"成分表を取得中: {mext.SEIBUN_URL}", file=sys.stderr)
        mext.download(xlsx, refresh=args.refresh)
        print(f"  {xlsx} ({xlsx.stat().st_size:,} bytes)", file=sys.stderr)

    print("成分表を解析中...", file=sys.stderr)
    df = mext.load(xlsx)
    print(f"  {len(df)}件", file=sys.stderr)

    # 手入力した食品（冷凍食品など）は成分表の作り直しで消さない
    kept = 0
    if MASTER_CSV.exists():
        existing = pd.read_csv(MASTER_CSV, dtype={'food_id': str, 'group': str, 'index_no': str})
        manual = existing[existing['source'] != 'mext']
        kept = len(manual)
        if kept:
            df = pd.concat([df, manual], ignore_index=True)

    ensure_dir(MASTER_CSV.parent)
    df.to_csv(MASTER_CSV, index=False)

    print(f"\n保存完了: {MASTER_CSV} ({len(df)}件, うち手入力 {kept}件)")
    _summarize(df)
    return 0


def _summarize(df):
    """食品群ごとの件数と、成分の欠測率を出す。黙って欠測したまま使わないため"""
    groups = df[df['source'] == 'mext'].groupby('group').size()
    print(f"\n食品群: {len(groups)}群")

    components = list(mext.COMPONENTS.values())
    missing = df[components].isna().mean().sort_values(ascending=False)
    worst = missing[missing > 0.3]
    if len(worst):
        print("\n欠測（未測定）が3割を超える成分:")
        for name, rate in worst.items():
            print(f"  {name:<20} {rate:.0%}")
        print("  ※ これらを含む集計は日によって母数が変わる。合計値をそのまま比較しない")


def main():
    parser = argparse.ArgumentParser(description='食事記録 CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    build = subparsers.add_parser('build-master', help='成分表から食品マスタを生成')
    build.add_argument('--xlsx', help='成分表 Excel のパス（省略時はダウンロード）')
    build.add_argument('--refresh', action='store_true', help='キャッシュを無視して取り直す')
    build.set_defaults(func=cmd_build_master)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
