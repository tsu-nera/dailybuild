#!/usr/bin/env python
# coding: utf-8
"""
日次記録（Google Form）— 朝・夜

`daily.py <slot> <action>` の形（slot: morning/evening、action: fetch/show/
setup-form。morning のみ migrate-manual も持つ）。朝夜は同じ尺度（1〜5・
高=良好）を共有する1つの概念の半分ずつなので、スクリプトを2本に割らない
（割ると片方だけ尺度や向きが動いたときに気づけない）。slot 固有の設定は
src/lib/daily/store.py の SLOTS が持ち、fetch/show/setup-form の本体は共通。

setup-form で fetch で回答を直接取得する。data/manual.csv（Google Sheets
手動入力）の一次入力5列を朝フォームへ移すための取得系（Issue #33 / #135）
だったが、Issue #157 で朝・夜の2フォームに分割した。
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.clients import gdrive_client, gforms_client
from lib.daily import render, store
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
MANUAL_FILE = require_private_path(BASE_DIR / 'data' / 'manual.csv')

DEF_FILES = {
    'morning': BASE_DIR / 'config/daily_morning_def.yaml',
    'evening': BASE_DIR / 'config/daily_evening_def.yaml',
}

TZ = 'Asia/Tokyo'


def load_def(slot):
    with open(DEF_FILES[slot]) as f:
        return yaml.safe_load(f)


def save_form_id(slot, form_id):
    """yaml のコメントを壊さないよう form_id の行だけ置換する"""
    def_file = DEF_FILES[slot]
    text = def_file.read_text()
    new_text, n = re.subn(r'^form_id:.*$', f'form_id: {form_id}', text,
                          count=1, flags=re.MULTILINE)
    if n != 1:
        raise ValueError(f'form_id の行が見つからない: {def_file}')
    def_file.write_text(new_text)


def responder_uri(form):
    return form.get('responderUri', f"https://docs.google.com/forms/d/{form['formId']}/viewform")


def build_items(conf):
    """yaml の定義からフォームの item spec リストを組み立てる"""
    q, s = conf['questions'], conf['score']
    grid_rows = conf['grid_rows']
    rows = [q[key] for key in grid_rows]
    grid_required = conf.get('grid_required', {})
    # 未指定の行は required 扱い（既定は安全側）
    required = [grid_required.get(key, True) for key in grid_rows]
    return [
        gforms_client.grid_item(conf['grid_title'], rows, s['low'], s['high'],
                             s['low_label'], s['high_label'], required=required),
        gforms_client.text_item(q['comment'], required=False),
    ]


def _grid_row_titles(form):
    """フォームの実際のグリッド行タイトルを出現順で返す。無ければ None"""
    for item in form.get('items', []):
        group = item.get('questionGroupItem')
        if group:
            return [q.get('rowQuestion', {}).get('title')
                   for q in group.get('questions', [])]
    return None


def update_vocab_history(revision_id, labels, path, now=None) -> bool:
    """グリッド行構成が前回と違えば1行追記する。追記したら True

    emotion.py の同名関数と完全に同じ実装（グリッド行タイトルのリストを
    labels として渡すだけ）。判定基準・理由は docs/forms.md の気分記録の
    節を参照。共通化は他フォームとの結合が強まる割に得るものが薄いため、
    ここでは意図的に重複させている。
    """
    path = Path(path)
    label_str = ';'.join(labels)

    last_labels = None
    if path.exists():
        existing = pd.read_csv(path, dtype=str)
        if not existing.empty:
            last_labels = existing.iloc[-1]['labels']

    if last_labels is not None and str(last_labels) == label_str:
        return False

    now = now or dt.datetime.now()
    row = pd.DataFrame([{
        'first_seen': now.strftime('%Y-%m-%d %H:%M:%S'),
        'revision_id': '' if revision_id is None else str(revision_id),
        'labels': label_str,
    }])

    ensure_dir(path.parent)
    if path.exists() and path.stat().st_size > 0:
        row.to_csv(path, mode='a', header=False, index=False)
    else:
        row.to_csv(path, mode='w', header=True, index=False)
    return True


def _move_new_form_to_drive(form_id):
    """新規作成したフォームを config/personal.yaml の gdrive.folder_id 配下へ移す

    forms.create は親を指定できずマイドライブ直下に作る。移動に失敗しても
    フォーム自体は作成済みなので form_id は失わせず、warning を出して続行する。
    """
    personal_file = BASE_DIR / 'config/personal.yaml'
    if not personal_file.exists():
        print(f'警告: {personal_file} が無い。Drive フォルダへの移動をスキップ',
              file=sys.stderr)
        return
    with open(personal_file, encoding='utf-8') as f:
        personal = yaml.safe_load(f) or {}
    folder_id = (personal.get('gdrive') or {}).get('folder_id')
    if not folder_id:
        print('警告: config/personal.yaml に gdrive.folder_id が無い。'
              'Drive フォルダへの移動をスキップ', file=sys.stderr)
        return
    try:
        drive_service = gdrive_client.create_service()
        gdrive_client.move_to_folder(drive_service, form_id, folder_id)
        print(f'Drive フォルダへ移動した: {folder_id}', file=sys.stderr)
    except Exception as e:
        print(f'警告: Drive フォルダへの移動に失敗（フォームは作成済み）: {e}',
              file=sys.stderr)


def cmd_setup_form(args):
    slot = args.slot
    conf = load_def(slot)
    items = build_items(conf)

    service = gforms_client.create_service()

    if conf.get('form_id'):
        if not args.update:
            print(f"フォームは作成済み: {conf['form_id']}")
            print('選択肢や質問文を yaml に合わせ直すなら --update')
            return
        existing_form = gforms_client.get_form(service, conf['form_id'])
        gforms_client.sync_questions(service, conf['form_id'], items,
                                  existing_form=existing_form)
        # 画面タイトルは item ではないので sync_questions が触らない。
        # questionId には影響しないが、差分があるときだけ叩く
        current_title = existing_form.get('info', {}).get('title')
        if current_title != conf['form_title']:
            gforms_client.update_form_info(service, conf['form_id'],
                                        conf['form_title'])
            print(f"タイトルを更新: {current_title} -> {conf['form_title']}")
        print('フォームを yaml に合わせて更新した')
        form = gforms_client.get_form(service, conf['form_id'])
    else:
        form = gforms_client.create_form(service, conf['form_title'],
                                      document_title=conf['form_title'])
        print(f"フォーム作成: {form['formId']}")
        gforms_client.sync_questions(service, form['formId'], items)
        save_form_id(slot, form['formId'])
        # 新規作成時のみ Drive フォルダへの移動を試みる。--update では移動しない
        _move_new_form_to_drive(form['formId'])
        form = gforms_client.get_form(service, form['formId'])

    print(f"質問: {list(gforms_client.question_id_by_title(form))}")
    print(f"回答用URL: {responder_uri(form)}")
    print(f"編集用URL: https://docs.google.com/forms/d/{form['formId']}/edit")


def build_dataframe(form, responses, conf, slot):
    """回答リストを CSV スキーマの DataFrame にする

    同一 date に複数回答があるときは最後（updated_at 昇順）のものだけを
    残す（date が主キーで、CSV に複数行を残さない）。

    date の作り方は slot ごとに違う（store.SLOTS[slot]['day_start_hour']）。
    朝は暦日のまま、夜は 5:00 境界（store.response_date() を参照）。
    """
    slot_conf = store.SLOTS[slot]
    by_title = gforms_client.question_id_by_title(form)
    q = conf['questions']
    grid_rows = conf['grid_rows']
    required_titles = [q[key] for key in grid_rows] + [q['comment']]
    missing = [t for t in required_titles if t not in by_title]
    if missing:
        raise ValueError(
            f'フォームに質問がない: {missing} / 実際: {list(by_title)}。'
            'setup-form --update で合わせること')

    rows = []
    for res in responses:
        grid_values = {}
        for key in grid_rows:
            v = gforms_client.answer_values(res, by_title[q[key]])
            grid_values[key] = v[0] if v else pd.NA
        comment = gforms_client.answer_values(res, by_title[q['comment']])
        row = {
            'updated_at': res.get('lastSubmittedTime') or res.get('createTime'),
            'comment': comment[0] if comment and comment[0] else pd.NA,
        }
        if slot_conf['has_source']:
            row['source'] = 'form'
        row.update(grid_values)
        rows.append(row)

    base_columns = (['updated_at'] + (['source'] if slot_conf['has_source'] else [])
                    + grid_rows + ['comment'])
    df = pd.DataFrame(rows, columns=base_columns)
    if df.empty:
        df = df.assign(date=pd.Series(dtype='object'))
        df = df.rename(columns=slot_conf['grid_column_map'])
        return df[slot_conf['columns']]

    # API は RFC3339 の UTC を返す。他データと揃えて JST の naive にする
    ts = pd.to_datetime(df['updated_at'], format='ISO8601', utc=True)
    df['updated_at'] = ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.floor('s')
    day_start_hour = slot_conf['day_start_hour']
    df['date'] = df['updated_at'].apply(
        lambda t: store.response_date(t, day_start_hour))
    for key in grid_rows:
        df[key] = pd.to_numeric(df[key], errors='coerce').astype('Int64')

    # 同一 date に複数回答があれば最後（updated_at 昇順で最後）を採る。
    # date が主キーなので複数行を残さない
    df = df.sort_values('updated_at').drop_duplicates(subset=['date'], keep='last')

    # スコアの列名を CSV 列名に合わせる（grid_rows キー -> CSV 列名。
    # f'{k}_score' の決め打ちにしない。夜の satisfaction/achievement には
    # 接尾辞が無いため）
    df = df.rename(columns=slot_conf['grid_column_map'])
    columns = slot_conf['columns']
    return df.sort_values('date').reset_index(drop=True)[columns]


def cmd_fetch(args, out=None):
    # show --update から呼ぶときは stdout を markdown 専用に保つため stderr を渡す
    out = out or sys.stdout
    slot = args.slot
    conf = load_def(slot)
    out_file = store.SLOTS[slot]['csv_file']
    grid_history_file = store.SLOTS[slot]['grid_history_file']

    if not conf.get('form_id'):
        # 夜フォームは merge 後に対話で作成する運用（Issue #157）。form_id が
        # 空のうちに daily-routine.sh から毎日呼ばれても、失敗し続けて
        # ステップが赤く出るのを避けるため正常終了する
        print(f'{slot}: form_id が未設定のためスキップ（{DEF_FILES[slot]}。'
              'setup-form で作成すること）', file=sys.stderr)
        return

    service = gforms_client.create_service(interactive=not args.non_interactive)
    form = gforms_client.get_form(service, conf['form_id'])

    print(f"回答取得中: {conf['form_id']}", file=sys.stderr)
    responses = gforms_client.list_responses(service, conf['form_id'])
    print(f"取得: {len(responses)}件", file=sys.stderr)

    df = build_dataframe(form, responses, conf, slot)

    # 毎回全件を取り直すので、既存行があるのに0件は取得側の故障を疑う
    if not responses and out_file.exists() and len(pd.read_csv(out_file)) > 0:
        print('警告: 既存CSVに行があるのに回答が0件。'
              'フォームの差し替えかAPIの異常を疑うこと', file=sys.stderr)

    revision_id = form.get('revisionId')
    if revision_id is None:
        print('警告: forms.get の応答に revisionId が無い。'
              'グリッド行構成の版は記録するが版は空になる', file=sys.stderr)
    grid_rows_titles = _grid_row_titles(form)
    if grid_rows_titles is None:
        print('警告: フォームにグリッド質問がない。'
              'グリッド行構成の履歴を更新できない', file=sys.stderr)
    elif update_vocab_history(revision_id, grid_rows_titles, grid_history_file):
        print(f'グリッド行構成の履歴を追記: revision {revision_id} / '
              f'{len(grid_rows_titles)}行', file=sys.stderr)

    ensure_dir(out_file.parent)
    # preserve_existing_on_nan は既定の False のまま使う（行単位の置換）。
    # True（セル単位マージ）にすると、comment を空で送った回答が来たときに
    # 旧行の comment が生き残り、source=form の行なのに comment だけ移行時の
    # sheet 由来という壊れた行ができる。date が主キーで、フォームに回答が
    # ある date は行ごと置換されるべき（migrate-manual の冪等性側で
    # source=form の行が上書きされないことは別途保証している）
    df = csv_utils.merge_csv_by_columns(
        df, out_file,
        key_columns=['date'],
        parse_dates=['date'],
        sort_by=['date'],
    )
    df.to_csv(out_file, index=False)
    print(f"保存完了: {out_file} ({len(df)}件)", file=out)
    print(df.tail(), file=out)


def cmd_migrate_manual(args):
    """manual.csv の一次入力5列を daily_morning.csv へ移行する（morning 限定）

    実行は #136 が行うが、コードとガードはここで用意する（本 Issue の範囲）。
    """
    out_file = store.SLOTS['morning']['csv_file']
    columns = store.SLOTS['morning']['columns']

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

    df_all = store.load_entries(slot)

    today = dt.date.today()
    start = today - dt.timedelta(days=args.days - 1)
    df = df_all[df_all['date'].dt.date >= start].reset_index(drop=True)

    label = {'morning': '朝', 'evening': '夜'}[slot]
    print(f'# 日次記録（{label}、{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}）\n')
    print(f"記録 {len(df)}日分（{args.days}日中）\n")

    print('## スコア\n')
    print(render.render_scores(df, slot))
    print('\n## コメント\n')
    print(render.render_comments(df))


def _add_action_subparsers(slot_parser, slot):
    sub = slot_parser.add_subparsers(dest='action', required=True)

    p_setup = sub.add_parser('setup-form', help='フォームを生成する')
    p_setup.add_argument('--update', action='store_true',
                         help='既存フォームの質問文・選択肢を yaml に合わせる')
    p_setup.set_defaults(func=cmd_setup_form)

    p_fetch = sub.add_parser('fetch', help='回答を取得して CSV に保存する')
    p_fetch.add_argument('--non-interactive', action='store_true',
                         help='トークンが無効ならブラウザを開かず落とす（cron 用）')
    p_fetch.set_defaults(func=cmd_fetch)

    p_show = sub.add_parser('show', help='記録のサマリを markdown で表示する')
    p_show.add_argument('--days', type=int, default=7,
                        help='直近N日（既定 7）')
    p_show.add_argument('--update', action='store_true',
                        help='表示前に fetch で最新データを取得する')
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
