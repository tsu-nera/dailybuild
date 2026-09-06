#!/usr/bin/env python
# coding: utf-8
"""
活動記録（Google Sheets）

BATD-R の Daily Monitoring に相当する手入力の記録をシートから取得する。
記録の単位は活動1件＝1行で、時間帯の枠は持たない（timestamp があれば
時間帯は導出できるが、逆はできない）。原典との相違は docs/batdr.md。
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.activity import store
from lib.clients import gsheets_client
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/activity_def.yaml'
OUT_FILE = store.CSV_FILE

TS_FORMAT = '%Y-%m-%d %H:%M:%S'


def load_def():
    with open(DEF_FILE) as f:
        return yaml.safe_load(f)


def build_dataframe(values, columns) -> pd.DataFrame:
    """シートの全セル（1行目がヘッダ）を CSV スキーマの DataFrame にする

    values は gspread の get_all_values() の戻り。ヘッダは yaml の columns と
    一致している前提で、実際の並びに合わせて引き直す（列を差し替えたときに
    黙って別の列を読まないため）。
    """
    empty = pd.DataFrame(columns=store.COLUMNS)
    if not values:
        return empty

    header = [c.strip() for c in values[0]]
    missing = [c for c in columns if c not in header]
    if missing:
        raise ValueError(
            f'シートに列がない: {missing} / 実際: {header}。'
            f'{DEF_FILE.name} の columns と合わせること')
    idx = {c: header.index(c) for c in columns}

    rows = []
    for raw in values[1:]:
        def cell(name):
            i = idx[name]
            return raw[i].strip() if i < len(raw) else ''

        ts, activity = cell('timestamp'), cell('activity')
        # timestamp か activity が空の行は記録として成立していない。
        # 入力途中の行や、書きかけて消した行を拾って捏造しない
        if not ts or not activity:
            continue
        rows.append({
            'timestamp': ts,
            'activity': activity,
            'enjoyment': cell('enjoyment'),
            'importance': cell('importance'),
            'note': cell('note'),
        })

    if not rows:
        return empty

    df = pd.DataFrame(rows)
    # Apps Script が入れる 'YYYY-MM-DD HH:MM:SS' が正。手で打った行が
    # 別形式でも拾えるよう緩く読み、解釈できない行だけ落とす
    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
    df = df[df['timestamp'].notna()]
    if df.empty:
        return empty

    for col in ('enjoyment', 'importance'):
        # 空欄は未評定。0 に潰さない
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    df['date'] = df['timestamp'].dt.date
    # 同一 timestamp は最後の行を採る（主キー。秒まで一致する手入力は
    # 実際には起きないが、貼り付けで同時刻の行が並ぶことはある）
    df = df.drop_duplicates(subset=['timestamp'], keep='last')
    return df.sort_values('timestamp').reset_index(drop=True)[store.COLUMNS]


def cmd_fetch(args, out=None):
    out = out or sys.stdout
    conf = load_def()

    client = gsheets_client.create_client()
    print(f"シート取得中: {conf['sheet_id']}", file=sys.stderr)
    sheet = client.open_by_key(conf['sheet_id'])
    worksheet = sheet.worksheet(conf['worksheet'])
    values = worksheet.get_all_values()

    df = build_dataframe(values, conf['columns'])
    print(f'取得: {len(df)}件', file=sys.stderr)

    # 毎回全件を取り直すので、既存行があるのに0件は取得側の故障を疑う
    if df.empty and OUT_FILE.exists() and len(pd.read_csv(OUT_FILE)) > 0:
        print('警告: 既存CSVに行があるのにシートが0件。'
              'シートの差し替えかAPIの異常を疑うこと', file=sys.stderr)

    ensure_dir(OUT_FILE.parent)
    merged = csv_utils.merge_csv_by_columns(
        df, OUT_FILE,
        key_columns=['timestamp'],
        parse_dates=['timestamp'],
        sort_by=['timestamp'],
    )
    merged.to_csv(OUT_FILE, index=False)
    print(f'保存完了: {OUT_FILE} ({len(merged)}件)', file=out)


def cmd_show(args):
    if args.update:
        cmd_fetch(argparse.Namespace(), out=sys.stderr)

    if not OUT_FILE.exists():
        print(f'エラー: {OUT_FILE} が存在しません', file=sys.stderr)
        sys.exit(1)

    df = store.load_entries()
    today = dt.date.today()
    start = today - dt.timedelta(days=args.days - 1)
    df = df[df['date'].dt.date >= start]

    print(f'# 活動記録（{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}）\n')
    print(f'{len(df)}件 / 記録のあった日 {df["date"].nunique()}日\n')
    if df.empty:
        return

    print('| 日時 | 活動 | 楽しさ | 重要さ | メモ |')
    print('|---|---|---:|---:|---|')
    for _, r in df.iterrows():
        e = '' if pd.isna(r['enjoyment']) else int(r['enjoyment'])
        i = '' if pd.isna(r['importance']) else int(r['importance'])
        print(f"| {r['timestamp']:%m-%d %H:%M} | {r['activity']} | {e} | {i} | {r['note']} |")


def main():
    parser = argparse.ArgumentParser(description='活動記録（Google Sheets）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_fetch = sub.add_parser('fetch', help='シートを読んで CSV に保存する')
    p_fetch.set_defaults(func=cmd_fetch)

    p_show = sub.add_parser('show', help='記録のサマリを markdown で表示する')
    p_show.add_argument('--days', type=int, default=7, help='直近N日（既定 7）')
    p_show.add_argument('--update', action='store_true',
                        help='表示前に fetch で最新データを取得する')
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
