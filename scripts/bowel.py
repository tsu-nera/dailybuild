#!/usr/bin/env python
# coding: utf-8
"""
排便記録（Google Form、Bristol Stool Scale）

setup-form でフォームを生成し、fetch で回答を直接取得する。setup-form /
fetch の手順は lib.forms と共通。固有処理は Bristol 値のパース
（選択肢の表示文字列の先頭の数値）と show の集計（型の分布・3分類）。
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
from lib.bowel import render, store
from lib.clients import gforms_client
from lib.forms import cli, defs
from lib.forms.responses import submitted_at, to_jst

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/bowel_def.yaml'
# show 側と同じパスを指すよう store から借りる
OUT_FILE = store.CSV_FILE


def load_def():
    return defs.load_def(DEF_FILE)


def choice_strings(conf) -> list[str]:
    """yaml の choices から "{code} {label}" の表示文字列リストを作る"""
    return [f"{c['code']} {c['label']}" for c in conf['choices']]


def build_items(conf):
    """yaml の定義からフォームの item spec リストを組み立てる"""
    q = conf['questions']
    return [
        gforms_client.radio_item(q['bristol'], choice_strings(conf), required=True),
        gforms_client.text_item(q['comment'], required=False),
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

    # comment はフォームに後から足した任意項目。古いフォーム定義のまま
    # fetch しても落ちないよう、無ければ全行を空文字にする
    comment_qid = by_title.get(q.get('comment'))

    rows = []
    for res in responses:
        v = gforms_client.answer_values(res, by_title[q['bristol']])
        c = gforms_client.answer_values(res, comment_qid) if comment_qid else []
        rows.append({
            'timestamp': submitted_at(res),
            'bristol': v[0] if v else pd.NA,
            # 未入力は NA ではなく空文字。fetch は preserve_existing_on_nan=True で
            # マージするため、NA にすると後から消したコメントが CSV 側に残り続ける
            'comment': c[0] if c else '',
        })

    columns = ['timestamp', 'date', 'bristol', 'comment']
    df = pd.DataFrame(rows, columns=['timestamp', 'bristol', 'comment'])
    if df.empty:
        return df.assign(date=pd.Series(dtype='object'))[columns]

    df['timestamp'] = to_jst(df['timestamp'])
    # 日境界の補正はしない（深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.date
    df['bristol'] = df['bristol'].apply(parse_bristol_value).astype('Int64')
    df['comment'] = df['comment'].fillna('').astype(str)
    return df[columns]


def cmd_setup_form(args):
    cli.setup_form(load_def, DEF_FILE, build_items, update=args.update,
                   allow_kind_replace=args.allow_kind_replace)


def cmd_fetch(args, out=None):
    conf = load_def()
    if not conf.get('form_id'):
        raise ValueError(
            f'form_id が未設定: {DEF_FILE}。先に setup-form を実行すること')

    form, responses = cli.fetch_responses(conf['form_id'],
                                          non_interactive=args.non_interactive)
    df = build_dataframe(form, responses, conf)
    cli.warn_if_no_responses(responses, cli.read_existing(OUT_FILE))
    cli.save_merged(df, OUT_FILE, 'timestamp', preserve_existing_on_nan=True, out=out)


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
    print('\n## メモ\n')
    print(render.render_comments(df))


def main():
    parser = argparse.ArgumentParser(description='排便記録（Google Form）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_setup = sub.add_parser('setup-form', help='フォームを生成する')
    cli.add_setup_arguments(p_setup)
    p_setup.set_defaults(func=cmd_setup_form)

    p_fetch = sub.add_parser('fetch', help='回答を取得して CSV に保存する')
    cli.add_fetch_arguments(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    p_show = sub.add_parser('show', help='記録のサマリを markdown で表示する')
    cli.add_show_arguments(p_show)
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
