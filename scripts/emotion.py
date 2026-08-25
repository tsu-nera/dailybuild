#!/usr/bin/env python
# coding: utf-8
"""
気分記録（Google Form）

setup-form でフォームを生成し、fetch で回答を直接取得する。
回答先スプレッドシートは経由しない（Forms API に回答先のリンク設定が
無いため、そこだけ手作業として残ってしまう）。
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.clients import gforms_api
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/emotion_def.yaml'
OUT_FILE = require_private_path(BASE_DIR / 'data/emotion.csv')

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


def cmd_setup_form(args):
    conf = load_def()
    choices = [v['label'] for v in conf['vocabulary']]
    q = conf['questions']

    service = gforms_api.create_service()

    if conf.get('form_id'):
        if not args.update:
            print(f"フォームは作成済み: {conf['form_id']}")
            print('選択肢や質問文を yaml に合わせ直すなら --update')
            return
        _update_form(service, conf['form_id'], q, choices)
        form = gforms_api.get_form(service, conf['form_id'])
    else:
        form = gforms_api.create_form(service, conf['form_title'],
                                      document_title=conf['form_title'])
        print(f"フォーム作成: {form['formId']}")
        gforms_api.add_questions(service, form['formId'],
                                 q['emotions'], choices, q['note'])
        save_form_id(form['formId'])
        form = gforms_api.get_form(service, form['formId'])

    print(f"質問: {list(gforms_api.question_id_by_title(form))}")
    print(f"回答用URL: {responder_uri(form)}")
    print(f"編集用URL: https://docs.google.com/forms/d/{form['formId']}/edit")


def _update_form(service, form_id, questions, choices):
    """既存フォームの質問文と選択肢を yaml に合わせる"""
    form = gforms_api.get_form(service, form_id)
    items = [i for i in form.get('items', []) if 'questionItem' in i]
    if len(items) != 2:
        raise ValueError(
            f'質問が2つでない（{len(items)}個）。画面で編集した可能性がある: {form_id}')

    requests = [
        {
            'updateItem': {
                'item': {
                    'title': questions['emotions'],
                    'questionItem': {
                        'question': {
                            'required': True,
                            'choiceQuestion': {
                                'type': 'CHECKBOX',
                                'options': [{'value': c} for c in choices],
                            },
                        },
                    },
                },
                'location': {'index': 0},
                'updateMask': 'title,questionItem.question',
            },
        },
        {
            'updateItem': {
                'item': {
                    'title': questions['note'],
                    'questionItem': {
                        'question': {
                            'required': False,
                            'textQuestion': {'paragraph': False},
                        },
                    },
                },
                'location': {'index': 1},
                'updateMask': 'title,questionItem.question',
            },
        },
    ]
    service.forms().batchUpdate(formId=form_id,
                                body={'requests': requests}).execute()
    print('フォームを yaml に合わせて更新した')


def build_dataframe(form, responses, conf):
    """回答リストを CSV スキーマの DataFrame にする"""
    by_title = gforms_api.question_id_by_title(form)
    q = conf['questions']
    missing = [t for t in (q['emotions'], q['note']) if t not in by_title]
    if missing:
        raise ValueError(
            f'フォームに質問がない: {missing} / 実際: {list(by_title)}。'
            'setup-form --update で合わせること')

    known = {v['label'] for v in conf['vocabulary']}
    rows = []
    unknown_all = set()
    for res in responses:
        emotions = gforms_api.answer_values(res, by_title[q['emotions']])
        note = gforms_api.answer_values(res, by_title[q['note']])
        unknown_all |= {e for e in emotions if e not in known}
        rows.append({
            'timestamp': res.get('lastSubmittedTime') or res.get('createTime'),
            # 複数選択は配列で返るので分割不要。区切り文字は CSV 側の都合
            'emotions': ';'.join(emotions) if emotions else pd.NA,
            'note': note[0] if note and note[0] else pd.NA,
        })

    if unknown_all:
        print(f"警告: 定義にない選択肢 {sorted(unknown_all)}"
              f"（config/emotion_def.yaml の vocabulary と不一致）")

    df = pd.DataFrame(rows, columns=['timestamp', 'emotions', 'note'])
    if df.empty:
        return df.assign(date=pd.Series(dtype='object'))[
            ['timestamp', 'date', 'emotions', 'note']]

    # API は RFC3339 の UTC を返す。他データと揃えて JST の naive にする
    ts = pd.to_datetime(df['timestamp'], format='ISO8601', utc=True)
    # 秒に丸める。ミリ秒は他のCSVと粒度が揃わないうえ、マージキーとして
    # 無駄に細かい（同一秒に2回送ることは無い）
    df['timestamp'] = ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.floor('s')
    # 日境界の補正はしない（深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.date
    return df[['timestamp', 'date', 'emotions', 'note']]


def cmd_fetch(args):
    conf = load_def()
    if not conf.get('form_id'):
        raise ValueError(
            f'form_id が未設定: {DEF_FILE}。先に setup-form を実行すること')

    service = gforms_api.create_service(interactive=not args.non_interactive)
    form = gforms_api.get_form(service, conf['form_id'])

    print(f"回答取得中: {conf['form_id']}", file=sys.stderr)
    responses = gforms_api.list_responses(service, conf['form_id'])
    print(f"取得: {len(responses)}件", file=sys.stderr)

    df = build_dataframe(form, responses, conf)

    # 毎回全件を取り直すので、既存行があるのに0件は取得側の故障を疑う
    # （マージするため CSV は消えないが、以後ずっと止まったままになる）
    if not responses and OUT_FILE.exists() and len(pd.read_csv(OUT_FILE)) > 0:
        print('警告: 既存CSVに行があるのに回答が0件。'
              'フォームの差し替えかAPIの異常を疑うこと', file=sys.stderr)

    ensure_dir(OUT_FILE.parent)
    df = csv_utils.merge_csv_by_columns(
        df, OUT_FILE,
        key_columns=['timestamp'],
        parse_dates=['timestamp'],
        sort_by=['timestamp'],
    )
    df.to_csv(OUT_FILE, index=False)
    print(f"保存完了: {OUT_FILE} ({len(df)}件)")
    print(df.tail())


def main():
    parser = argparse.ArgumentParser(description='気分記録（Google Form）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_setup = sub.add_parser('setup-form', help='フォームを生成する')
    p_setup.add_argument('--update', action='store_true',
                         help='既存フォームの質問文・選択肢を yaml に合わせる')
    p_setup.set_defaults(func=cmd_setup_form)

    p_fetch = sub.add_parser('fetch', help='回答を取得して CSV に保存する')
    p_fetch.add_argument('--non-interactive', action='store_true',
                         help='トークンが無効ならブラウザを開かず落とす（cron 用）')
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
