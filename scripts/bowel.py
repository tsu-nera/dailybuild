#!/usr/bin/env python
# coding: utf-8
"""
排便記録（Google Form、Bristol Stool Scale）

setup-form でフォームを生成し、fetch で回答を直接取得する。
気分記録（scripts/emotion.py）と同じ流儀の別フォーム。
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.bowel import render, store
from lib.clients import gforms_client
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/bowel_def.yaml'
# show 側と同じパスを指すよう store から借りる
OUT_FILE = store.CSV_FILE


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


def choice_strings(conf) -> list[str]:
    """yaml の choices から "{code} {label}" の表示文字列リストを作る"""
    return [f"{c['code']} {c['label']}" for c in conf['choices']]


def build_items(conf):
    """yaml の定義からフォームの item spec リストを組み立てる"""
    q = conf['questions']
    return [
        gforms_client.radio_item(q['bristol'], choice_strings(conf), required=True),
    ]


def parse_bristol_value(value) -> int | float:
    """選択肢の表示文字列から先頭の数値を取り出す

    "3 ひび割れのあるソーセージ状" -> 3。未回答・パース不能（先頭が数字で
    ない）は pd.NA を返す。0 に潰さない（欠測を捏造しない）。
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NA
    m = re.match(r'^\s*(\d+)', str(value))
    if not m:
        return pd.NA
    return int(m.group(1))


def build_dataframe(form, responses, conf):
    """回答リストを CSV スキーマの DataFrame にする"""
    by_title = gforms_client.question_id_by_title(form)
    q = conf['questions']
    if q['bristol'] not in by_title:
        raise ValueError(
            f"フォームに質問がない: {q['bristol']} / 実際: {list(by_title)}。"
            'setup-form --update で合わせること')

    rows = []
    for res in responses:
        v = gforms_client.answer_values(res, by_title[q['bristol']])
        rows.append({
            'timestamp': res.get('lastSubmittedTime') or res.get('createTime'),
            'bristol': v[0] if v else pd.NA,
        })

    columns = ['timestamp', 'date', 'bristol']
    df = pd.DataFrame(rows, columns=['timestamp', 'bristol'])
    if df.empty:
        return df.assign(date=pd.Series(dtype='object'))[columns]

    # API は RFC3339 の UTC を返す。他データと揃えて JST の naive にする
    ts = pd.to_datetime(df['timestamp'], format='ISO8601', utc=True)
    # 秒に丸める。ミリ秒は他のCSVと粒度が揃わないうえ、マージキーとして
    # 無駄に細かい（同一秒に2回送ることは無い）
    df['timestamp'] = ts.dt.tz_convert('Asia/Tokyo').dt.tz_localize(None).dt.floor('s')
    # 日境界の補正はしない（深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.date
    df['bristol'] = df['bristol'].apply(parse_bristol_value).astype('Int64')
    return df[columns]


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
        preserve_existing_on_nan=True,
    )
    df.to_csv(OUT_FILE, index=False)
    print(f"保存完了: {OUT_FILE} ({len(df)}件)", file=out)
    print(df.tail(), file=out)


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
    df = df_all[df_all['timestamp'].dt.date >= start].reset_index(drop=True)

    print(f'# 排便記録（{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}）\n')
    # 記録が無いのは故障ではない（断続的な記録でもトレンド用途は成立する）ので
    # 0件でも正常終了する。CSV 自体が無い場合だけ上で落としてある。
    # 被覆は統計の但し書きとして出すだけで、上げるべき目標としては出さない
    print(f"記録 {len(df)}件 / {df['date'].nunique()}日に記録あり"
          f'（{args.days}日中）\n')

    print('## 型の分布\n')
    print(render.render_distribution(df))
    print('\n## 3分類\n')
    print(render.render_category(df))
    print('\n## 日別の一覧\n')
    print(render.render_daily(df))


def main():
    parser = argparse.ArgumentParser(description='排便記録（Google Form）')
    sub = parser.add_subparsers(dest='command', required=True)

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

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
