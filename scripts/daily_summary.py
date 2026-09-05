#!/usr/bin/env python
# coding: utf-8
"""
日次記録（Google Form）

setup-form でフォームを生成し、fetch で回答を直接取得する。
data/manual.csv（Google Sheets 手動入力）の一次入力5列をこのフォームへ
移すための取得系（Issue #33 / #135）。本番フォームの作成・移行の実行は
このスクリプトの範囲外（#136）。
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.clients import gforms_client
from lib.daily_summary import render, store
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/daily_summary_def.yaml'
MANUAL_FILE = require_private_path(BASE_DIR / 'data' / 'manual.csv')
# show 側と同じパスを指すよう store から借りる
OUT_FILE = store.CSV_FILE
# グリッド行構成（並び順）の版履歴。仕組みは emotion.py の
# GRID_HISTORY_FILE と同じ（update_vocab_history をそのまま流用）。
# Issue #135 の Acceptance Criteria には無い追加（PR 本文に明記）。
# 直近のグリッド行名変更（気分記録「頭の冴え」→「頭の軽さ」）が、行名の
# 変更だけで過去データの意味が変わりうることを示したため、同じ事故を
# ここでも先回りで防ぐ
GRID_HISTORY_FILE = require_private_path(
    BASE_DIR / 'data/daily_summary_grid_history.csv')

TZ = 'Asia/Tokyo'


def load_def():
    with open(DEF_FILE) as f:
        return yaml.safe_load(f)


def save_form_id(form_id):
    """yaml のコメントを壊さないよう form_id の行だけ置換する"""
    text = DEF_FILE.read_text()
    new_text, n = re.subn(r'^form_id:.*$', f'form_id: {form_id}', text,
                          count=1, flags=re.MULTILINE)
    if n != 1:
        raise ValueError(f'form_id の行が見つからない: {DEF_FILE}')
    DEF_FILE.write_text(new_text)


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


def cmd_setup_form(args):
    conf = load_def()
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
        print('フォームを yaml に合わせて更新した')
        form = gforms_client.get_form(service, conf['form_id'])
    else:
        form = gforms_client.create_form(service, conf['form_title'],
                                      document_title=conf['form_title'])
        print(f"フォーム作成: {form['formId']}")
        gforms_client.sync_questions(service, form['formId'], items)
        save_form_id(form['formId'])
        form = gforms_client.get_form(service, form['formId'])

    print(f"質問: {list(gforms_client.question_id_by_title(form))}")
    print(f"回答用URL: {responder_uri(form)}")
    print(f"編集用URL: https://docs.google.com/forms/d/{form['formId']}/edit")


def build_dataframe(form, responses, conf):
    """回答リストを CSV スキーマの DataFrame にする

    同一 date に複数回答があるときは最後（answered_at 昇順）のものだけを
    残す（date が主キーで、CSV に複数行を残さない）。
    """
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
            'answered_at': res.get('lastSubmittedTime') or res.get('createTime'),
            'source': 'form',
            'comment': comment[0] if comment and comment[0] else pd.NA,
        }
        row.update(grid_values)
        rows.append(row)

    df = pd.DataFrame(rows, columns=['answered_at', 'source'] + grid_rows + ['comment'])
    if df.empty:
        df = df.assign(date=pd.Series(dtype='object'))
        df = df.rename(columns={k: f'{k}_score' for k in grid_rows})
        return df[store.COLUMNS]

    # API は RFC3339 の UTC を返す。他データと揃えて JST の naive にする
    ts = pd.to_datetime(df['answered_at'], format='ISO8601', utc=True)
    df['answered_at'] = ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.floor('s')
    # date = 回答日（設問は「今日」）。日境界の補正はしない
    df['date'] = df['answered_at'].dt.date
    for key in grid_rows:
        df[key] = pd.to_numeric(df[key], errors='coerce').astype('Int64')

    # 同一 date に複数回答があれば最後（answered_at 昇順で最後）を採る。
    # date が主キーなので複数行を残さない
    df = df.sort_values('answered_at').drop_duplicates(subset=['date'], keep='last')

    # スコアの列名を store.COLUMNS に合わせる（mind/body/sleep -> *_score）
    df = df.rename(columns={k: f'{k}_score' for k in grid_rows})
    columns = store.COLUMNS
    return df.sort_values('date').reset_index(drop=True)[columns]


def cmd_fetch(args, out=None):
    # show --update から呼ぶときは stdout を markdown 専用に保つため stderr を渡す
    out = out or sys.stdout
    conf = load_def()
    if not conf.get('form_id'):
        raise ValueError(
            f'form_id が未設定: {DEF_FILE}。先に setup-form を実行すること')

    service = gforms_client.create_service(interactive=not args.non_interactive)
    form = gforms_client.get_form(service, conf['form_id'])

    print(f"回答取得中: {conf['form_id']}", file=sys.stderr)
    responses = gforms_client.list_responses(service, conf['form_id'])
    print(f"取得: {len(responses)}件", file=sys.stderr)

    df = build_dataframe(form, responses, conf)

    # 毎回全件を取り直すので、既存行があるのに0件は取得側の故障を疑う
    if not responses and OUT_FILE.exists() and len(pd.read_csv(OUT_FILE)) > 0:
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
    elif update_vocab_history(revision_id, grid_rows_titles, GRID_HISTORY_FILE):
        print(f'グリッド行構成の履歴を追記: revision {revision_id} / '
              f'{len(grid_rows_titles)}行', file=sys.stderr)

    ensure_dir(OUT_FILE.parent)
    # preserve_existing_on_nan は既定の False のまま使う（行単位の置換）。
    # True（セル単位マージ）にすると、comment を空で送った回答が来たときに
    # 旧行の comment が生き残り、source=form の行なのに comment だけ移行時の
    # sheet 由来という壊れた行ができる。date が主キーで、フォームに回答が
    # ある date は行ごと置換されるべき（migrate-manual の冪等性側で
    # source=form の行が上書きされないことは別途保証している）
    df = csv_utils.merge_csv_by_columns(
        df, OUT_FILE,
        key_columns=['date'],
        parse_dates=['date'],
        sort_by=['date'],
    )
    df.to_csv(OUT_FILE, index=False)
    print(f"保存完了: {OUT_FILE} ({len(df)}件)", file=out)
    print(df.tail(), file=out)


def cmd_migrate_manual(args):
    """manual.csv の一次入力5列を daily_summary.csv へ移行する

    実行は #136 が行うが、コードとガードはここで用意する（本 Issue の範囲）。
    """
    manual = pd.read_csv(MANUAL_FILE, usecols=[
        'date', 'mind_score', 'body_score', 'sleep_score', 'comment'])
    total_rows = len(manual)

    value_cols = ['mind_score', 'body_score', 'sleep_score', 'comment']
    # 4列すべて欠測の行は移行しない（未記録の日を捏造しない）
    all_missing = manual[value_cols].isna().all(axis=1)
    skipped_missing = int(all_missing.sum())
    manual = manual[~all_missing]

    existing_dates = set()
    if OUT_FILE.exists():
        existing = pd.read_csv(OUT_FILE, usecols=['date'])
        existing_dates = set(existing['date'].astype(str))

    # 冪等性: 既に daily_summary.csv にある date は上書きしない
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

    to_migrate['answered_at'] = pd.NA  # Sheets は入力時刻を記録していない（復元不能）
    to_migrate['source'] = 'sheet'
    to_migrate = to_migrate[store.COLUMNS]

    ensure_dir(OUT_FILE.parent)
    if OUT_FILE.exists():
        merged = pd.concat([pd.read_csv(OUT_FILE), to_migrate], ignore_index=True)
    else:
        merged = to_migrate
    merged = merged.sort_values('date').reset_index(drop=True)
    merged.to_csv(OUT_FILE, index=False)
    print(f"移行完了: {OUT_FILE} (+{len(to_migrate)}行, 計{len(merged)}行)",
          file=sys.stderr)


def cmd_show(args):
    if args.update:
        # 取得ログは stderr に寄せ、stdout は markdown 専用に保つ
        cmd_fetch(argparse.Namespace(non_interactive=False), out=sys.stderr)

    if not OUT_FILE.exists():
        print(f'エラー: {OUT_FILE} が存在しません', file=sys.stderr)
        sys.exit(1)

    df_all = store.load_entries()

    today = dt.date.today()
    start = today - dt.timedelta(days=args.days - 1)
    df = df_all[df_all['date'].dt.date >= start].reset_index(drop=True)

    print(f'# 日次記録（{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}）\n')
    print(f"記録 {len(df)}日分（{args.days}日中）\n")

    print('## スコア\n')
    print(render.render_scores(df))
    print('\n## コメント\n')
    print(render.render_comments(df))


def main():
    parser = argparse.ArgumentParser(description='日次記録（Google Form）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_setup = sub.add_parser('setup-form', help='フォームを生成する')
    p_setup.add_argument('--update', action='store_true',
                         help='既存フォームの質問文・選択肢を yaml に合わせる')
    p_setup.set_defaults(func=cmd_setup_form)

    p_fetch = sub.add_parser('fetch', help='回答を取得して CSV に保存する')
    p_fetch.add_argument('--non-interactive', action='store_true',
                         help='トークンが無効ならブラウザを開かず落とす（cron 用）')
    p_fetch.set_defaults(func=cmd_fetch)

    p_migrate = sub.add_parser('migrate-manual',
                               help='manual.csv の一次入力5列を移行する')
    p_migrate.add_argument('--dry-run', action='store_true',
                           help='書き込まず対象件数だけ表示する')
    p_migrate.set_defaults(func=cmd_migrate_manual)

    p_show = sub.add_parser('show', help='記録のサマリを markdown で表示する')
    p_show.add_argument('--days', type=int, default=7,
                        help='直近N日（既定 7）')
    p_show.add_argument('--update', action='store_true',
                        help='表示前に fetch で最新データを取得する')
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
