#!/usr/bin/env python
# coding: utf-8
"""
日次記録（Google Form）— 朝・夜

`daily.py <slot> <action>` の形（slot: morning/evening、action: fetch/show/
setup-form。morning のみ migrate-manual も持つ）。朝夜は同じ尺度（1〜5・
高=良好）を共有する1つの概念の半分ずつなので、スクリプトを2本に割らない
（割ると片方だけ尺度や向きが動いたときに気づけない）。

fetch / show / setup-form の本体は固有処理を持たないフォームと共通
（lib.forms.generic。scripts/forms.py の `fetch daily_morning` と同じ処理）。
slot の差（日付境界・source 列）は config/daily_{slot}_def.yaml にある。
ここに残る固有処理は migrate-manual（data/manual.csv の一次入力5列を朝へ
移す。Issue #33 / #135）だけ。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
from lib.clients import gforms_client  # noqa: F401（テストが monkeypatch する）
from lib.daily import store
from lib.forms import cli, defs, generic, schema
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
MANUAL_FILE = require_private_path(BASE_DIR / 'data' / 'manual.csv')

NAMES = {'morning': '日次記録（朝）', 'evening': '日次記録（夜）'}

# スキーマの唯一の正本は config/daily_{slot}_def.yaml（store.load_def が読む）。
# モジュール global のエイリアスにしておくことで、テストの
# monkeypatch.setattr(daily, 'load_def', fake_load_def) がそのまま効く
load_def = store.load_def
build_items = schema.build_items


def save_question_ids(slot, ids_by_key):
    """question_id だけ yaml へ書き戻す（Issue #176。lib.forms.defs.save_question_ids）"""
    return defs.save_question_ids(store.DEF_FILES[slot], ids_by_key)


def _paths(slot):
    return generic.Paths(def_file=store.DEF_FILES[slot],
                         csv_file=store.SLOTS[slot]['csv_file'],
                         grid_history_file=store.SLOTS[slot]['grid_history_file'])


def cmd_setup_form(args):
    slot = args.slot
    generic.setup_form(lambda: load_def(slot), store.DEF_FILES[slot], args,
                       build_items=build_items)


def cmd_fetch(args, out=None):
    generic.fetch(load_def(args.slot), _paths(args.slot),
                  non_interactive=args.non_interactive, out=out)


def cmd_migrate_manual(args):
    """manual.csv の一次入力5列を daily_morning.csv へ移行する（morning 限定）

    実行は #136 が行うが、コードとガードはここで用意する（本 Issue の範囲）。
    """
    conf = store.load_def('morning')
    out_file = store.SLOTS['morning']['csv_file']
    columns = schema.columns(conf)

    manual = pd.read_csv(MANUAL_FILE, usecols=[
        'date', 'mind_score', 'body_score', 'sleep_score', 'comment'])
    total_rows = len(manual)

    value_cols = ['mind_score', 'body_score', 'sleep_score', 'comment']
    # 4列すべて欠測の行は移行しない（未記録の日を捏造しない）
    all_missing = manual[value_cols].isna().all(axis=1)
    skipped_missing = int(all_missing.sum())
    manual = manual[~all_missing]

    existing_dates = set()
    if out_file.exists():
        existing = pd.read_csv(out_file, usecols=['date'])
        existing_dates = set(existing['date'].astype(str))

    # 冪等性: 既に daily_morning.csv にある date は上書きしない
    # （特に source=form の行を manual.csv の sheet 由来で潰さない）
    to_migrate = manual[~manual['date'].astype(str).isin(existing_dates)].copy()
    skipped_existing = len(manual) - len(to_migrate)

    print(f"manual.csv: {total_rows}行 "
          f"/ 4列すべて欠測でスキップ: {skipped_missing}行 "
          f"/ 既存dateでスキップ: {skipped_existing}行 "
          f"/ 移行対象: {len(to_migrate)}行", file=sys.stderr)

    if args.dry_run:
        print('--dry-run のため書き込みなし', file=sys.stderr)
        return

    if to_migrate.empty:
        print('移行対象なし', file=sys.stderr)
        return

    to_migrate['updated_at'] = pd.NA  # Sheets は入力時刻を記録していない（復元不能）
    to_migrate['source'] = 'sheet'
    to_migrate['head_score'] = pd.NA  # manual.csv に頭の記録は無い（0で埋めない）
    for col in columns:
        if col not in to_migrate.columns:
            to_migrate[col] = pd.NA  # HRV/EDA など manual.csv に無い列も欠測として補う
    to_migrate = to_migrate[columns]

    ensure_dir(out_file.parent)
    if out_file.exists():
        merged = pd.concat([pd.read_csv(out_file), to_migrate], ignore_index=True)
    else:
        merged = to_migrate
    merged = merged.sort_values('date').reset_index(drop=True)
    merged.to_csv(out_file, index=False)
    print(f"移行完了: {out_file} (+{len(to_migrate)}行, 計{len(merged)}行)",
          file=sys.stderr)


def cmd_show(args):
    slot = args.slot
    if args.update:
        # 取得ログは stderr に寄せ、stdout は markdown 専用に保つ
        cmd_fetch(argparse.Namespace(slot=slot, non_interactive=False), out=sys.stderr)
    generic.show(load_def(slot), store.SLOTS[slot]['csv_file'], NAMES[slot], args.days)


def _add_action_subparsers(slot_parser, slot):
    sub = slot_parser.add_subparsers(dest='action', required=True)

    p_setup = sub.add_parser('setup-form', help='フォームを生成する')
    cli.add_setup_arguments(p_setup)
    p_setup.set_defaults(func=cmd_setup_form)

    p_fetch = sub.add_parser('fetch', help='回答を取得して CSV に保存する')
    cli.add_fetch_arguments(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    p_show = sub.add_parser('show', help='記録のサマリを markdown で表示する')
    cli.add_show_arguments(p_show)
    p_show.set_defaults(func=cmd_show)

    if slot == 'morning':
        p_migrate = sub.add_parser('migrate-manual',
                                   help='manual.csv の一次入力5列を移行する')
        p_migrate.add_argument('--dry-run', action='store_true',
                               help='書き込まず対象件数だけ表示する')
        p_migrate.set_defaults(func=cmd_migrate_manual)


def main():
    parser = argparse.ArgumentParser(description='日次記録（朝・夜、Google Form）')
    slot_sub = parser.add_subparsers(dest='slot', required=True)
    for slot in ('morning', 'evening'):
        slot_parser = slot_sub.add_parser(slot)
        _add_action_subparsers(slot_parser, slot)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
