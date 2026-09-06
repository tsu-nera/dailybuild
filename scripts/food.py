#!/usr/bin/env python
# coding: utf-8
"""
食事記録 CLI（build-master / setup-sheet / sync-sheet / fetch）

食品マスタは文部科学省「日本食品標準成分表（八訂）増補2023年」から作る。
市販の冷凍食品・加工食品は成分表に載らないので、パッケージの栄養成分表示から
可食部100g当たりで別途登録する（source=manual）。マスタを作り直しても
手入力分が消えないよう、既存 CSV の source=mext 以外の行は残す。

入力は Google Sheets（config/food_def.yaml の sheet_id）。#137 で daily_report
への相乗りを削除したため、食事専用シートを使う。

Usage:
    python scripts/food.py build-master              # 成分表から食品マスタを生成
    python scripts/food.py build-master --refresh    # 成分表 Excel を取り直す
    python scripts/food.py build-master --xlsx path/to/seibun.xlsx

    python scripts/food.py setup-sheet               # 3タブを冪等に作る
    python scripts/food.py sync-sheet                # food_master へ候補を流し込む
    python scripts/food.py sync-sheet --all          # 成分表全件を流し込む（実機検証用）
    python scripts/food.py fetch                     # シートを読んで CSV を作る
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml

from lib.clients import gsheets_client
from lib.food import mext
from lib.food import store
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/food_def.yaml'
XLSX_CACHE = BASE_DIR / 'tmp' / 'mext_seibun.xlsx'
NUTRITION_DIR = BASE_DIR / 'data' / 'nutrition'
MASTER_CSV = store.MASTER_CSV


def load_def():
    with open(DEF_FILE) as f:
        return yaml.safe_load(f)


def load_master():
    if not MASTER_CSV.exists():
        print(f"エラー: 食品マスタがありません: {MASTER_CSV}", file=sys.stderr)
        print("  先に scripts/food.py build-master を実行してください", file=sys.stderr)
        sys.exit(1)
    return pd.read_csv(MASTER_CSV, dtype={'food_id': str, 'group': str, 'index_no': str})


def open_spreadsheet(conf):
    return gsheets_client.create_client().open_by_key(conf['sheet_id'])


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


def cmd_setup_sheet(args, out=None):
    """3タブ（food_master / food_recipe / food_log）を冪等に作る

    既にあるタブには触れない（書き込み済みの記録を消さないため）。
    """
    out = out or sys.stdout
    conf = load_def()
    ss = open_spreadsheet(conf)
    created = store.setup_worksheets(ss)

    if created:
        print(f"タブを作成: {', '.join(created)}", file=out)
    else:
        print("タブは揃っている（書式は当て直した）", file=out)
    print(ss.url, file=out)
    return 0


def _read_names_csv(path, column):
    if not path.exists():
        return pd.Series(dtype=object)
    df = pd.read_csv(path)
    if column not in df.columns:
        return pd.Series(dtype=object)
    return df[column]


def cmd_sync_sheet(args, out=None):
    """food_master へ候補を流し込み、ドロップダウンの参照範囲を張り直す"""
    out = out or sys.stdout
    conf = load_def()
    df_master = load_master()
    ss = open_spreadsheet(conf)

    try:
        ss.worksheet(store.MASTER_SHEET)
    except Exception:
        print("エラー: タブが無い。先に setup-sheet を実行すること", file=sys.stderr)
        sys.exit(1)

    if args.all:
        # 実機検証用のエスケープハッチ（issue #63 論点1）。
        # 既定では使わない: 2,538件を全部流し込むとスマホで絞り込めない
        names = sorted(df_master['name'].dropna().astype(str))
    else:
        recipe_names = _read_names_csv(store.RECIPES_CSV, 'name')
        entry_names = _read_names_csv(store.ENTRIES_CSV, 'name')
        cand = conf['candidates']
        names = store.select_candidates(
            df_master, recipe_names, entry_names,
            cand['seed_names'], cand['top_n'])
        if not names:
            print("警告: 候補が0件。sync-sheet --all で成分表全件を流し込むか、"
                  f"{DEF_FILE.name} の candidates.seed_names に手書きで足すこと",
                  file=sys.stderr)

    store.sync_master(ss, names)
    print(f"{store.MASTER_SHEET} に {len(names)}件の食品名を流し込んだ", file=out)
    print(f"{store.RECIPE_SHEET} / {store.LOG_SHEET} の name 列のドロップダウンを"
          f"張り直した", file=out)
    print(ss.url, file=out)
    return 0


def cmd_fetch(args, out=None):
    """シートを読んで entries.csv / daily.csv（レシピが取れれば recipes.csv）を作る

    既存 CSV には Cronometer 由来の過去記録が入っている。全上書きすると
    取り替えられない行を消す（欠測の捏造）ので、新データに日付が存在する
    行だけを replace_csv_period で置き換える。
    """
    out = out or sys.stdout
    conf = load_def()
    df_master = load_master()
    ss = open_spreadsheet(conf)

    print(f"シート取得中: {conf['sheet_id']}", file=sys.stderr)
    df_recipe_raw = store.read_sheet(ss, store.RECIPE_SHEET)
    df_log_raw = store.read_sheet(ss, store.LOG_SHEET)
    print(f"  {store.RECIPE_SHEET}: {len(df_recipe_raw)}行 / "
          f"{store.LOG_SHEET}: {len(df_log_raw)}行", file=sys.stderr)

    df_recipes, unknown_ingredients = store.build_recipes(df_recipe_raw, df_master)
    if len(unknown_ingredients):
        print(f"警告: レシピの材料が食品マスタに見つからない: {list(unknown_ingredients)}",
              file=sys.stderr)

    foods_frames = [df_master[['name'] + store.NUTRIENTS]]
    if len(df_recipes):
        foods_frames.append(df_recipes[['name'] + store.NUTRIENTS])
    df_foods = pd.concat(foods_frames, ignore_index=True)

    df_entries, issues = store.resolve_log(df_log_raw, df_foods)
    if issues['unknown_names']:
        print(f"警告: 食品マスタにもレシピにも無い名前: {issues['unknown_names']}",
              file=sys.stderr)
    if issues['bad_date']:
        print(f"警告: 日付が読めない行を除外: {issues['bad_date']}行", file=sys.stderr)
    if issues['bad_grams']:
        print(f"警告: グラム数が読めない行を除外: {issues['bad_grams']}行", file=sys.stderr)

    df_daily = store.aggregate_daily(df_entries)

    # 毎回シート全体を取り直すので、既存CSVに行があるのに0件は
    # 取得側の故障（タブ名・API異常）を疑う。
    #
    # 判定は entries.csv だけで行う。daily.csv には Cronometer 由来の過去記録が
    # 入っており、出所がシートだけではないため「行があるのにシートが0件」が
    # 立ち上げ期の正常な状態と区別できない（ここで落とすと最初のログを
    # 入れるまで毎回失敗する）
    if store.detect_empty_sheet_failure(df_entries, store.ENTRIES_CSV):
        print("警告: 既存CSVに行があるのにシートが0件。"
              "タブの命名かAPIの異常を疑うこと", file=sys.stderr)
        sys.exit(1)

    if df_entries.empty and df_daily.empty:
        print("保存対象なし（食事ログが空）", file=out)
        return 0

    ensure_dir(NUTRITION_DIR)

    # recipes.csv はシートの現在の中身をそのまま映す派生物（履歴の蓄積では
    # ない）なので、期間置換ではなく全上書きでよい
    if len(df_recipes):
        df_recipes.to_csv(store.RECIPES_CSV, index=False)

    df_entries = df_entries.copy()
    df_entries['date'] = df_entries['date'].dt.strftime('%Y-%m-%d')
    entries_merged = csv_utils.replace_csv_period(
        df_entries, store.ENTRIES_CSV, date_column='date',
        start_date=df_entries['date'].min(), end_date=df_entries['date'].max(),
        sort_by=['date', 'meal'], label='食事ログ')
    entries_merged.to_csv(store.ENTRIES_CSV, index=False)

    df_daily_out = df_daily.reset_index()
    df_daily_out['date'] = df_daily_out['date'].dt.strftime('%Y-%m-%d')
    daily_merged = csv_utils.replace_csv_period(
        df_daily_out, store.DAILY_CSV, date_column='date',
        start_date=df_daily_out['date'].min(), end_date=df_daily_out['date'].max(),
        sort_by=['date'], label='栄養日次')
    daily_merged.to_csv(store.DAILY_CSV, index=False)

    print(f"保存完了:", file=out)
    if len(df_recipes):
        print(f"  {store.RECIPES_CSV.name}: {len(df_recipes)}レシピ", file=out)
    print(f"  {store.ENTRIES_CSV.name}: {len(entries_merged)}件", file=out)
    print(f"  {store.DAILY_CSV.name}: {len(daily_merged)}日", file=out)
    return 0


def main():
    parser = argparse.ArgumentParser(description='食事記録 CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    build = subparsers.add_parser('build-master', help='成分表から食品マスタを生成')
    build.add_argument('--xlsx', help='成分表 Excel のパス（省略時はダウンロード）')
    build.add_argument('--refresh', action='store_true', help='キャッシュを無視して取り直す')
    build.set_defaults(func=cmd_build_master)

    setup = subparsers.add_parser(
        'setup-sheet', help='入力用の3タブを冪等に作る（既存には触れない）')
    setup.set_defaults(func=cmd_setup_sheet)

    sync = subparsers.add_parser(
        'sync-sheet', help='food_master へ候補を流し込み、ドロップダウンを張り直す')
    sync.add_argument('--all', action='store_true',
                      help='成分表全件を流し込む（既定は候補を絞る。実機検証用）')
    sync.set_defaults(func=cmd_sync_sheet)

    fetch = subparsers.add_parser('fetch', help='シートを読んで CSV を作る')
    fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
