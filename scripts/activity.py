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
import importlib.util
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.activity import render, store
from lib.clients import gsheets_client
from lib.toggl import store as toggl_store
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


def format_requests(sheet_id: int, conf: dict) -> list[dict]:
    """見た目を整える。値には触らないので既存タブにも当てられる

    列幅を決めるのは装飾ではない。活動名が長いと隣の評定列へはみ出して
    表示され、どの列がどの日か読めなくなる（グリッドがずれて見える）。
    """
    low, high = conf['score']['low'], conf['score']['high']
    values = [{'userEnteredValue': str(v)} for v in range(low, high + 1)]
    day_cols = conf['day_columns']
    n = len(day_cols)
    rated = [day_cols.index(conf['record_columns'][k])
             for k in ('enjoyment', 'importance')]
    act = day_cols.index(conf['record_columns']['activity'])
    total = 1 + n * DAYS_PER_TAB
    reqs = []

    def width(start, end, px):
        return {'updateDimensionProperties': {
            'range': {'sheetId': sheet_id, 'dimension': 'COLUMNS',
                      'startIndex': start, 'endIndex': end},
            'properties': {'pixelSize': px}, 'fields': 'pixelSize'}}

    reqs.append(width(0, 1, 64))
    for d in range(DAYS_PER_TAB):
        base = 1 + n * d
        reqs.append(width(base + act, base + act + 1, 190))
        for i in rated:
            reqs.append(width(base + i, base + i + 1, 56))
        # 日付は3列にまたがって見せる。get_all_values は結合セルの値を
        # 左上だけに返すので、パーサ側（先頭列から引く）と食い違わない
        reqs.append({'mergeCells': {
            'range': {'sheetId': sheet_id, 'startRowIndex': 0, 'endRowIndex': 1,
                      'startColumnIndex': base, 'endColumnIndex': base + n},
            'mergeType': 'MERGE_ALL'}})
        reqs.append({'setDataValidation': {
            'range': {
                'sheetId': sheet_id,
                'startRowIndex': 2,
                'endRowIndex': 2 + len(store.SLOTS),
                'startColumnIndex': base + min(rated),
                'endColumnIndex': base + max(rated) + 1,
            },
            'rule': {
                'condition': {'type': 'ONE_OF_LIST', 'values': values},
                'showCustomUi': True,
                'strict': False,
            },
        }})

    # はみ出しを止める。CLIP にしないと空セルの隣に長い活動名が流れ込む
    reqs.append({'repeatCell': {
        'range': {'sheetId': sheet_id, 'startRowIndex': 0,
                  'startColumnIndex': 0, 'endColumnIndex': total},
        'cell': {'userEnteredFormat': {'wrapStrategy': 'CLIP'}},
        'fields': 'userEnteredFormat.wrapStrategy'}})
    # 見出し2行を中央寄せ・太字にして、日付の区切りを目で追えるようにする
    reqs.append({'repeatCell': {
        'range': {'sheetId': sheet_id, 'startRowIndex': 0, 'endRowIndex': 2,
                  'startColumnIndex': 0, 'endColumnIndex': total},
        'cell': {'userEnteredFormat': {'horizontalAlignment': 'CENTER',
                                       'textFormat': {'bold': True}}},
        'fields': 'userEnteredFormat.horizontalAlignment,'
                  'userEnteredFormat.textFormat.bold'}})
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

    # CSV に落とす列だけを名前で引く。Toggl 列（draft の下書き）は読み捨てる
    off = {k: day_cols.index(v) for k, v in conf['record_columns'].items()}
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
            activity = cell(raw, base + off['activity'])
            # 活動が空の枠は「未記録」。評定や Toggl の下書きだけが入って
            # いても記録として成立していないので取り込まない
            if not activity:
                continue
            rows.append({
                'date': date,
                'hour': hour,
                'activity': activity,
                'enjoyment': cell(raw, base + off['enjoyment']),
                'importance': cell(raw, base + off['importance']),
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


def col_letter(n: int) -> str:
    """1始まりの列番号を A1 記法の列名にする"""
    name = ''
    while n:
        n, r = divmod(n - 1, 26)
        name = chr(65 + r) + name
    return name


def slot_window(date: dt.date, hour: int) -> tuple[dt.datetime, dt.datetime]:
    """枠の実時間の範囲。0-2時台の枠は帳票上の日付の翌暦日にある"""
    day = date + dt.timedelta(days=1) if hour < 5 else date
    begin = dt.datetime.combine(day, dt.time(hour))
    return begin, begin + dt.timedelta(hours=store.SLOT_HOURS[hour])


def entry_label(row) -> str:
    """Toggl エントリの表示名。評定表のキーでもある"""
    desc = '' if pd.isna(row['description']) else str(row['description']).strip()
    label = str(row['project_name'])
    return f'{label}: {desc}' if desc and desc != label else label


def toggl_slots(date: dt.date) -> dict[int, str]:
    """その日の Toggl エントリを22枠に割り付ける

    枠ごとに、重なりが最も長いエントリだけを採る。1枠に複数の活動が入る
    ことはあるが、原典の帳票が枠あたり1行なので、最長のものを代表にする。
    """
    df = toggl_store.load_entries()
    labels = {}
    for hour, _ in store.SLOTS:
        begin, end = slot_window(date, hour)
        best, best_sec = None, 0
        for _, r in df.iterrows():
            if pd.isna(r['stop']):
                continue  # 計測中のエントリ
            overlap = (min(r['stop'], end) - max(r['start'], begin)).total_seconds()
            if overlap > best_sec:
                best, best_sec = r, overlap
        if best is not None:
            labels[hour] = entry_label(best)[:40]
    return labels


def load_ratings(conf) -> dict[str, dict]:
    path = BASE_DIR / conf['ratings_file']
    with open(path) as f:
        return (yaml.safe_load(f) or {}).get('ratings') or {}


def fetch_toggl(date: dt.date) -> None:
    """canonical な Toggl 取得（scripts/toggl.py の run_fetch）をそのまま使う

    ここで自前に取得を書くと save_fetch_window を落としがちで、push の
    削除検出が壊れる。窓は date を含む2日ぶん（日跨ぎエントリを拾うため）。
    """
    spec = importlib.util.spec_from_file_location(
        'toggl_script', BASE_DIR / 'scripts' / 'toggl.py')
    toggl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(toggl)
    args = argparse.Namespace(
        update=False, days=None,
        start_date=(date - dt.timedelta(days=1)).isoformat(),
        end_date=(date + dt.timedelta(days=1)).isoformat())
    toggl.run_fetch(args, sys.stderr)


def merge_day_rows(current, slots, ratings, width, off):
    """1日ぶんのセルに Toggl の割り付けと評定を重ねる（シートに触らない純関数）

    **手で書いたセルは上書きしない。** 記録の正本は本人の申告で、Toggl は
    それを埋める材料でしかない。評定は「活動が入っていて評定が空の枠」に
    入れるので、rate で後から表に足したぶんが再実行で既存の枠にも行き渡る。
    """
    rows, wrote, rated, unrated = [], 0, 0, set()
    for i, (hour, _) in enumerate(store.SLOTS):
        row = list(current[i]) if i < len(current) else []
        row += [''] * (width - len(row))

        label = slots.get(hour)
        if label and not row[off['activity']].strip():
            row[off['activity']] = label
            wrote += 1

        name = row[off['activity']].strip()
        if name:
            r = ratings.get(name) or ratings.get(name.split(':')[0].strip())
            blank = not (row[off['enjoyment']].strip()
                         or row[off['importance']].strip())
            if r and blank:
                row[off['enjoyment']] = str(r['enjoyment'])
                row[off['importance']] = str(r['importance'])
                rated += 1
            elif not r and blank:
                unrated.add(name)
        rows.append(row)
    return rows, wrote, rated, unrated


def cmd_sync(args, out=None):
    """Toggl を取得して、その日の空いているセルだけを埋める"""
    out = out or sys.stdout
    conf = load_def()
    date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()

    fetch_toggl(date)
    slots = toggl_slots(date)
    if not slots:
        print(f'{date}: Toggl にエントリなし', file=out)
        return

    key = week_key(date)
    sheet = open_sheet(conf)
    try:
        ws = sheet.worksheet(key)
    except Exception:
        print(f'エラー: タブ {key} が無い。先に setup-sheet を実行すること',
              file=sys.stderr)
        sys.exit(1)

    day_cols = conf['day_columns']
    n = len(day_cols)
    d = week_dates(key).index(date)
    first = 1 + n * d + 1  # 1始まりの列番号（A列が枠の見出し）
    rng = f'{col_letter(first)}3:{col_letter(first + n - 1)}{2 + len(store.SLOTS)}'
    current = ws.get(rng)

    off = {k: day_cols.index(v) for k, v in conf['record_columns'].items()}
    rows, wrote, rated, unrated = merge_day_rows(
        current, slots, load_ratings(conf), n, off)

    ws.update(rows, rng)
    print(f'{date}: 活動を{wrote}枠、評定を{rated}枠に入れた'
          f'（Toggl が割り付いたのは{len(slots)}枠）', file=out)
    if unrated:
        print('\n評定が無い活動:', file=out)
        for label in sorted(unrated):
            print(f"  uv run scripts/activity.py rate '{label}' <楽しさ> <重要さ>",
                  file=out)
    blank = [store.slot_label(h) for h, _ in store.SLOTS if h not in slots]
    if blank:
        print(f'\nToggl が空の枠（自分で書く）: {" ".join(blank)}', file=out)


def cmd_rate(args, out=None):
    """評定表に活動を1件足す"""
    out = out or sys.stdout
    conf = load_def()
    path = BASE_DIR / conf['ratings_file']
    text = path.read_text()
    data = yaml.safe_load(text) or {}
    ratings = data.get('ratings') or {}
    ratings[args.activity] = {'enjoyment': args.enjoyment,
                              'importance': args.importance}
    head = text.split('ratings:')[0]
    body = yaml.safe_dump({'ratings': ratings}, allow_unicode=True,
                          sort_keys=True, default_flow_style=False)
    path.write_text(head + body)
    print(f'{args.activity}: 楽しさ {args.enjoyment} / '
          f'重要さ {args.importance}', file=out)


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
    existing = {ws.title: ws for ws in sheet.worksheets()}

    today = dt.date.today()
    keys = [week_key(today), week_key(today + dt.timedelta(days=7))]
    created = []
    for key in keys:
        ws = existing.get(key)
        if ws is None:
            grid = sheet_grid(key, conf)
            ws = sheet.add_worksheet(title=key, rows=len(grid),
                                     cols=len(grid[1]))
            ws.update(grid, 'A1')
            created.append(key)
        # 書式は毎回当て直す。値には触れないので、既にある記録は壊れない
        sheet.batch_update({'requests': format_requests(ws.id, conf)})

    if created:
        print(f"タブを作成: {', '.join(created)}", file=out)
    else:
        print(f"タブは揃っている（書式は当て直した）: {', '.join(keys)}",
              file=out)


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
        print(render.render_entries(df))
    else:
        print(render.render_daily(df))


def main():
    parser = argparse.ArgumentParser(description='活動記録（Google Sheets）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_setup = sub.add_parser(
        'setup-sheet', help='当週・翌週のタブを作る（既存には触れない）')
    p_setup.set_defaults(func=cmd_setup_sheet)

    p_sync = sub.add_parser(
        'sync', help='Toggl を取得して、その日の空いている枠を埋める')
    p_sync.add_argument('--date', help='対象日（既定は今日）')
    p_sync.set_defaults(func=cmd_sync)

    p_rate = sub.add_parser('rate', help='活動の楽しさ・重要さを評定表に足す')
    p_rate.add_argument('activity', help='活動名（Toggl の表示名）')
    p_rate.add_argument('enjoyment', type=int, help='楽しさ 0-10')
    p_rate.add_argument('importance', type=int, help='重要さ 0-10')
    p_rate.set_defaults(func=cmd_rate)

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
