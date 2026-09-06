#!/usr/bin/env python
# coding: utf-8
"""
活動記録（Google Sheets）

BATD-R の Daily Monitoring（Form 1）を原典の形のままシートに置き、読み取って
CSV にする。1日 = 22枠（5am 開始・翌 5am まで）× 活動 / 楽しさ / 重要さ。

タブは ISO week ごとに1枚。原典の帳票が第4週以降「予定表」に変わる
（計画を先に書き、未実行なら線を引く）ため、追記専用の形にはしない。
原典との相違は docs/batdr.md。
"""

import argparse
import datetime as dt
import re
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

DAYS_PER_TAB = 7


def load_def():
    with open(DEF_FILE) as f:
        return yaml.safe_load(f)


def week_key(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f'{y}-W{w:02d}'


def week_dates(key: str) -> list[dt.date]:
    """タブ名（2026-W37）から月曜〜日曜の7日を作る"""
    y, w = key.split('-W')
    monday = dt.date.fromisocalendar(int(y), int(w), 1)
    return [monday + dt.timedelta(days=i) for i in range(DAYS_PER_TAB)]


def sheet_grid(key: str, conf: dict) -> list[list[str]]:
    """1週ぶんのタブの中身（ヘッダ2行 + 22枠）を作る"""
    day_cols = conf['day_columns']
    header_date = [''] + [d.isoformat() if i == 0 else ''
                          for d in week_dates(key)
                          for i in range(len(day_cols))]
    header_col = [conf['time_header']] + day_cols * DAYS_PER_TAB
    body = [[store.slot_label(h)] + [''] * (len(day_cols) * DAYS_PER_TAB)
            for h, _ in store.SLOTS]
    return [header_date, header_col] + body


def validation_requests(sheet_id: int, conf: dict) -> list[dict]:
    """楽しさ / 重要さの列に 0-10 のプルダウンを張る"""
    low, high = conf['score']['low'], conf['score']['high']
    values = [{'userEnteredValue': str(v)} for v in range(low, high + 1)]
    reqs = []
    for d in range(DAYS_PER_TAB):
        reqs.append({'setDataValidation': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 2 + len(store.SLOTS),
                'startColumnIndex': 2 + 3 * d,
                'endColumnIndex': 4 + 3 * d,
            },
            'rule': {
                'condition': {'type': 'ONE_OF_LIST', 'values': values},
                'showCustomUi': True,
                'strict': False,
            },
        }})
    reqs.append({'updateSheetProperties': {
        'properties': {'sheetId': sheet_id,
                       'gridProperties': {'frozenRowCount': 2,
                                          'frozenColumnCount': 1}},
        'fields': 'gridProperties.frozenRowCount,'
                  'gridProperties.frozenColumnCount',
    }})
    return reqs


def build_dataframe(values: list[list[str]], conf: dict) -> pd.DataFrame:
    """1タブぶんのセルを CSV スキーマの DataFrame にする

    values は gspread の get_all_values() の戻り。1行目が日付、2行目が
    day_columns の繰り返し、3行目以降が枠。**見出しが崩れていたら黙って
    別の列を読まず落とす**（列がずれたまま取り込むと、評定が別の日に付く）。
    """
    empty = pd.DataFrame(columns=store.COLUMNS)
    if len(values) < 3:
        return empty

    day_cols = conf['day_columns']
    n = len(day_cols)
    row_date, row_col = values[0], values[1]

    def cell(row, i):
        return row[i].strip() if i < len(row) else ''

    # 日付が入っている列ブロックだけを見る。setup-sheet は7日ぶん書くが、
    # 途中で切れているタブを黙って部分的に読まないよう連続性で切る
    days = []
    for d in range(DAYS_PER_TAB):
        base = 1 + n * d
        raw = cell(row_date, base)
        if not raw:
            break
        got = [cell(row_col, base + i) for i in range(n)]
        if got != day_cols:
            raise ValueError(
                f'見出しが崩れている: {got} / 期待: {day_cols}。'
                f'{DEF_FILE.name} の day_columns と合わせること')
        days.append((pd.to_datetime(raw).date(), base))
    if not days:
        return empty

    rows = []
    for raw in values[2:]:
        label = cell(raw, 0)
        if not label:
            continue  # シート末尾の空行
        if label not in store.LABEL_TO_HOUR:
            raise ValueError(
                f'知らない枠の見出し: {label!r}。原典 Form 1 の22枠と'
                f'一致していない（行を足したり並べ替えたりしない）')
        hour = store.LABEL_TO_HOUR[label]
        for date, base in days:
            activity = cell(raw, base)
            # 活動が空の枠は「未記録」。評定だけが入っていても記録として
            # 成立していないので取り込まない
            if not activity:
                continue
            rows.append({
                'date': date,
                'hour': hour,
                'activity': activity,
                'enjoyment': cell(raw, base + 1),
                'importance': cell(raw, base + 2),
            })

    if not rows:
        return empty

    df = pd.DataFrame(rows)
    for col in ('enjoyment', 'importance'):
        # 空欄は未評定。0 に潰さない
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    # CSV と同じ文字列で持つ。期間置換が既存 CSV（文字列）と突き合わせるため、
    # ここで Timestamp のまま渡すと型が混ざって並びが壊れる
    df['date'] = df['date'].astype(str)
    # 主キーは (date, hour)。同じ枠が2度現れるのは構造上ありえないが、
    # 手でタブを複製したときに備えて最後を採る
    df = df.drop_duplicates(subset=['date', 'hour'], keep='last')
    return df[store.COLUMNS]


def open_sheet(conf):
    client = gsheets_client.create_client()
    return client.open_by_key(conf['sheet_id'])


def cmd_setup_sheet(args, out=None):
    """当週と翌週のタブを冪等に作る

    既にあるタブには触れない（書き込み済みの記録を消さないため）。
    """
    out = out or sys.stdout
    conf = load_def()
    sheet = open_sheet(conf)
    existing = {ws.title for ws in sheet.worksheets()}

    today = dt.date.today()
    keys = [week_key(today), week_key(today + dt.timedelta(days=7))]
    created = []
    for key in keys:
        if key in existing:
            continue
        grid = sheet_grid(key, conf)
        ws = sheet.add_worksheet(title=key, rows=len(grid),
                                 cols=len(grid[1]))
        ws.update(grid, 'A1')
        sheet.batch_update({'requests': validation_requests(ws.id, conf)})
        created.append(key)

    if created:
        print(f"タブを作成: {', '.join(created)}", file=out)
    else:
        print(f"タブは揃っている: {', '.join(keys)}", file=out)


def cmd_fetch(args, out=None):
    out = out or sys.stdout
    conf = load_def()
    pattern = re.compile(conf['tab_pattern'])

    sheet = open_sheet(conf)
    print(f"シート取得中: {conf['sheet_id']}", file=sys.stderr)

    frames = []
    for ws in sheet.worksheets():
        if not pattern.match(ws.title):
            continue
        df = build_dataframe(ws.get_all_values(), conf)
        print(f'  {ws.title}: {len(df)}枠', file=sys.stderr)
        if not df.empty:
            frames.append(df)

    df = pd.concat(frames, ignore_index=True) if frames else \
        pd.DataFrame(columns=store.COLUMNS)
    print(f'取得: {len(df)}枠', file=sys.stderr)

    # 毎回全タブを取り直すので、既存行があるのに0件は取得側の故障を疑う
    if df.empty and OUT_FILE.exists() and len(pd.read_csv(OUT_FILE)) > 0:
        print('警告: 既存CSVに行があるのにシートが0件。'
              'タブの命名かAPIの異常を疑うこと', file=sys.stderr)
        sys.exit(1)

    ensure_dir(OUT_FILE.parent)
    if df.empty:
        print('保存対象なし', file=out)
        return

    # キーマージではなく期間置換。シート側で枠を消したとき（記録の訂正）に
    # CSV へ古い行が残り続けないようにする。df_new に無い日付は消さない
    merged = csv_utils.replace_csv_period(
        df, OUT_FILE, date_column='date',
        start_date=df['date'].min(),
        end_date=df['date'].max(),
        sort_by=['date', 'hour'], label='活動記録')
    merged.to_csv(OUT_FILE, index=False)
    print(f'保存完了: {OUT_FILE} ({len(merged)}枠)', file=out)


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
    if df.empty:
        print('記録なし')
        return

    if args.list:
        print('| 日付 | 枠 | 活動 | 楽しさ | 重要さ |')
        print('|---|---|---|---:|---:|')
        for _, r in df.iterrows():
            e = '' if pd.isna(r['enjoyment']) else int(r['enjoyment'])
            i = '' if pd.isna(r['importance']) else int(r['importance'])
            print(f"| {r['date']:%m-%d} | {store.slot_label(r['hour'])} "
                  f"| {r['activity']} | {e} | {i} |")
        return

    # 「楽しくも重要でもない時間の長さ」がこの帳票の主目的なので、件数ではなく
    # 時間で出す（評定が付いた枠だけが分母。未評定を 0 として混ぜない）
    print('| 日付 | 記録 | 楽しさ平均 | 重要さ平均 | 低評定(3以下)の時間 |')
    print('|---|---:|---:|---:|---:|')
    for date, g in df.groupby(df['date'].dt.date):
        rated = g[g['enjoyment'].notna() & g['importance'].notna()]
        low = rated[(rated['enjoyment'] <= 3) & (rated['importance'] <= 3)]
        e = f"{g['enjoyment'].mean():.1f}" if g['enjoyment'].notna().any() else '-'
        i = f"{g['importance'].mean():.1f}" if g['importance'].notna().any() else '-'
        print(f"| {date:%m-%d} | {int(g['hours'].sum())}h | {e} | {i} "
              f"| {int(low['hours'].sum())}h |")


def main():
    parser = argparse.ArgumentParser(description='活動記録（Google Sheets）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_setup = sub.add_parser(
        'setup-sheet', help='当週・翌週のタブを作る（既存には触れない）')
    p_setup.set_defaults(func=cmd_setup_sheet)

    p_fetch = sub.add_parser('fetch', help='シートを読んで CSV に保存する')
    p_fetch.set_defaults(func=cmd_fetch)

    p_show = sub.add_parser('show', help='記録のサマリを markdown で表示する')
    p_show.add_argument('--days', type=int, default=7, help='直近N日（既定 7）')
    p_show.add_argument('--list', action='store_true', help='枠を一覧で出す')
    p_show.add_argument('--update', action='store_true',
                        help='表示前に fetch で最新データを取得する')
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
