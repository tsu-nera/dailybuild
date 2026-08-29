#!/usr/bin/env python
# coding: utf-8
"""
PHQ-9（週次）

setup-form でフォームを生成し、fetch で回答を直接取得する。
scripts/emotion.py と同じ構成（Google Form 直読み、回答先スプレッドシートは
経由しない）。

設問文の著作権上、config/phq9_def.yaml は追跡対象外（.gitignore 済み）。
config/phq9_def.yaml.sample をコピーして出典から書き写すこと。
CLAUDE.md の「PHQ-9」節を参照。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.clients import gforms_api
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/phq9_def.yaml'
SAMPLE_FILE = BASE_DIR / 'config/phq9_def.yaml.sample'
OUT_FILE = require_private_path(BASE_DIR / 'data/phq9.csv')

TZ = 'Asia/Tokyo'

# yaml の質問キー（q1〜q9）。sync_questions は同型の質問を出現順で
# 突き合わせるため、この順序を変えてはいけない（CLAUDE.md 参照）
QUESTION_KEYS = [f'q{i}' for i in range(1, 10)]


def load_def():
    if not DEF_FILE.exists():
        raise FileNotFoundError(
            f'{DEF_FILE} が無い。著作権の都合でこのファイルはコミットされて'
            f'いない。{SAMPLE_FILE} をコピーし、出典から設問文を書き写すこと'
            '（CLAUDE.md の「PHQ-9」節を参照）:\n'
            f'  cp {SAMPLE_FILE} {DEF_FILE}'
        )
    with open(DEF_FILE) as f:
        return yaml.safe_load(f)


def save_form_id(form_id):
    """yaml のコメントを壊さないよう form_id の行だけ置換する"""
    import re
    text = DEF_FILE.read_text()
    new_text, n = re.subn(r'^form_id:.*$', f'form_id: {form_id}', text,
                          count=1, flags=re.MULTILINE)
    if n != 1:
        raise ValueError(f'form_id の行が見つからない: {DEF_FILE}')
    DEF_FILE.write_text(new_text)


def responder_uri(form):
    return form.get('responderUri', f"https://docs.google.com/forms/d/{form['formId']}/viewform")


def impairment_enabled(conf):
    return conf.get('impairment', {}).get('enabled', True)


def build_items(conf):
    """yaml の定義からフォームの item spec リストを組み立てる

    9問すべて同型（ラジオボタン）。sync_questions は kind ごとの出現順で
    突き合わせるため、ここでのリスト順が questions の yaml 記載順と
    一致していること（QUESTION_KEYS の順）。
    """
    q = conf['questions']
    choices = [c['label'] for c in conf['choices']]
    items = [gforms_api.radio_item(q[key], choices, required=True)
             for key in QUESTION_KEYS]

    if impairment_enabled(conf):
        imp = conf['impairment']
        items.append(gforms_api.radio_item(imp['question'], imp['choices'],
                                           required=False))
    return items


def cmd_setup_form(args):
    conf = load_def()
    items = build_items(conf)

    service = gforms_api.create_service()

    if conf.get('form_id'):
        if not args.update:
            print(f"フォームは作成済み: {conf['form_id']}")
            print('選択肢や質問文を yaml に合わせ直すなら --update')
            return
        existing_form = gforms_api.get_form(service, conf['form_id'])
        gforms_api.sync_questions(service, conf['form_id'], items,
                                  existing_form=existing_form)
        print('フォームを yaml に合わせて更新した')
        form = gforms_api.get_form(service, conf['form_id'])
    else:
        form = gforms_api.create_form(service, conf['form_title'],
                                      document_title=conf['form_title'])
        print(f"フォーム作成: {form['formId']}")
        gforms_api.sync_questions(service, form['formId'], items)
        save_form_id(form['formId'])
        form = gforms_api.get_form(service, form['formId'])

    print(f"質問: {list(gforms_api.question_id_by_title(form))}")
    print(f"回答用URL: {responder_uri(form)}")
    print(f"編集用URL: https://docs.google.com/forms/d/{form['formId']}/edit")


def cmd_url(args):
    """回答用URLを表示する（/weekly-review が回答を促すのに使う）"""
    conf = load_def()
    if not conf.get('form_id'):
        raise SystemExit(f'form_id が未設定: {DEF_FILE}。先に setup-form を実行すること')
    service = gforms_api.create_service(interactive=not args.non_interactive)
    form = gforms_api.get_form(service, conf['form_id'])
    print(responder_uri(form))


def build_dataframe(form, responses, conf):
    """回答リストを CSV スキーマの DataFrame にする

    合計（total）は9問すべてに回答があるときだけ算出する。1つでも
    未回答なら NaN（未回答を0点として足さない。食品マスタの「-」＝未測定
    と同じ原則）。機能障害の設問（採点対象外）は impairment 列に生の
    ラベルで残す。
    """
    by_title = gforms_api.question_id_by_title(form)
    q = conf['questions']
    has_impairment = impairment_enabled(conf)
    imp_title = conf['impairment']['question'] if has_impairment else None

    titles = [q[key] for key in QUESTION_KEYS]
    if has_impairment:
        titles = titles + [imp_title]
    missing = [t for t in titles if t not in by_title]
    if missing:
        raise ValueError(
            f'フォームに質問がない: {missing} / 実際: {list(by_title)}。'
            'setup-form --update で合わせること')

    score_by_label = {c['label']: c['score'] for c in conf['choices']}

    rows = []
    unknown_all = set()
    for res in responses:
        row = {'timestamp': res.get('lastSubmittedTime') or res.get('createTime')}
        item_scores = []
        for key in QUESTION_KEYS:
            vals = gforms_api.answer_values(res, by_title[q[key]])
            label = vals[0] if vals else None
            score = score_by_label.get(label) if label is not None else None
            if label is not None and score is None:
                unknown_all.add(label)
            row[key] = score if score is not None else pd.NA
            item_scores.append(score)

        row['total'] = (sum(item_scores)
                        if all(s is not None for s in item_scores) else pd.NA)

        if has_impairment:
            imp_vals = gforms_api.answer_values(res, by_title[imp_title])
            row['impairment'] = imp_vals[0] if imp_vals else pd.NA

        rows.append(row)

    if unknown_all:
        print(f"警告: 定義にない選択肢 {sorted(unknown_all)}"
              f"（config/phq9_def.yaml の choices と不一致）")

    value_columns = QUESTION_KEYS + ['total'] + (['impairment'] if has_impairment else [])
    columns = ['timestamp', 'date'] + value_columns
    df = pd.DataFrame(rows, columns=['timestamp'] + value_columns)
    if df.empty:
        return df.assign(date=pd.Series(dtype='object'))[columns]

    # API は RFC3339 の UTC を返す。他データと揃えて JST の naive にする
    ts = pd.to_datetime(df['timestamp'], format='ISO8601', utc=True)
    df['timestamp'] = ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.floor('s')
    df['date'] = df['timestamp'].dt.date

    for key in QUESTION_KEYS + ['total']:
        df[key] = pd.to_numeric(df[key], errors='coerce').astype('Int64')

    return df[columns]


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

    # 週1回の質問紙なので大半の日は0件が正常。0件をエラーにしない
    # （data/googlehealth/caffeine.csv と同じ扱い）
    df = build_dataframe(form, responses, conf)

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
    parser = argparse.ArgumentParser(description='PHQ-9（週次）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_setup = sub.add_parser('setup-form', help='フォームを生成する')
    p_setup.add_argument('--update', action='store_true',
                         help='既存フォームの質問文・選択肢を yaml に合わせる')
    p_setup.set_defaults(func=cmd_setup_form)

    p_fetch = sub.add_parser('fetch', help='回答を取得して CSV に保存する')
    p_fetch.add_argument('--non-interactive', action='store_true',
                         help='トークンが無効ならブラウザを開かず落とす（cron 用）')
    p_fetch.set_defaults(func=cmd_fetch)

    p_url = sub.add_parser('url', help='回答用URLを表示する')
    p_url.add_argument('--non-interactive', action='store_true',
                       help='トークンが無効ならブラウザを開かず落とす')
    p_url.set_defaults(func=cmd_url)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
