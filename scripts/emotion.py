#!/usr/bin/env python
# coding: utf-8
"""
気分記録（Google Form）

setup-form でフォームを生成し、fetch で回答を直接取得する。
回答先スプレッドシートは経由しない（Forms API に回答先のリンク設定が
無いため、そこだけ手作業として残ってしまう）。setup-form / fetch の手順は
lib.forms と共通。固有処理は語彙（チェックボックス）と極性（valence）、
語彙の版履歴、--allow-kind-replace の前に未取り込み回答を検査すること。
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
from lib.clients import gforms_client
from lib.emotion import render, store
from lib.forms import cli, defs
from lib.forms.responses import (checkbox_choices, csv_max_timestamp,
                                 grid_row_titles, has_unfetched_responses,
                                 record_history, submitted_at, to_jst)
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/emotion_def.yaml'
# show 側と同じパスを指すよう store から借りる
OUT_FILE = store.CSV_FILE
VOCAB_HISTORY_FILE = require_private_path(
    BASE_DIR / 'data/emotion_vocab_history.csv')
# グリッドの行構成（並び順）の版履歴。仕組みは VOCAB_HISTORY_FILE と同じ
# （ファイルだけ分けているのは、語彙とグリッド行が別の構成要素で、同じ
# ファイルに混ぜると「何の版か」が revision_id だけでは読み取れなくなるため）
GRID_HISTORY_FILE = require_private_path(
    BASE_DIR / 'data/emotion_grid_history.csv')


def load_def():
    return defs.load_def(DEF_FILE)


def build_items(conf):
    """yaml の定義からフォームの item spec リストを組み立てる"""
    q, s = conf['questions'], conf['score']
    choices = [v['label'] for v in conf['vocabulary']]
    grid_rows = conf['grid_rows']
    rows = [q[key] for key in grid_rows]
    grid_required = conf.get('grid_required', {})
    # 未指定の行は required 扱い（既定は安全側）
    required = [grid_required.get(key, True) for key in grid_rows]
    return [
        gforms_client.grid_item(conf['grid_title'], rows, s['low'], s['high'],
                                s['low_label'], s['high_label'], required=required),
        gforms_client.checkbox_item(q['emotions'], choices, required=True),
        gforms_client.text_item(q['note'], required=False),
    ]


def _abort_if_unfetched(service, conf, leftover):
    """削除の前に、CSV に未取り込みの回答がフォーム側に無いか確かめる

    実際に1件失いかけたインシデントの再発防止: 日次 fetch の後に投稿された
    回答が CSV に materialize されないまま削除すると、questionId の対応付けが
    失われ、その回答の値が読めなくなる。
    """
    responses = gforms_client.list_responses(service, conf['form_id'])
    if has_unfetched_responses(responses, csv_max_timestamp(OUT_FILE, 'timestamp')):
        print('中止: data/emotion.csv に未取り込みの回答が'
              'フォーム側にある。削除すると questionId の対応'
              '付けが失われ、その回答の値が読めなくなる。'
              '先に `uv run scripts/emotion.py fetch` を実行して'
              'から、改めて --update --allow-kind-replace を'
              '実行すること', file=sys.stderr)
        sys.exit(1)


def cmd_setup_form(args):
    cli.setup_form(load_def, DEF_FILE, build_items, update=args.update,
                   allow_kind_replace=args.allow_kind_replace,
                   before_delete=_abort_if_unfetched)


def build_dataframe(form, responses, conf):
    """回答リストを CSV スキーマの DataFrame にする

    グリッドの行（conf['grid_rows']、現状は score のみ）は列としてそのまま
    出力する。行を足すだけで列が増える構成にしてあるので、将来 快・達成感の
    行を足しても build_dataframe 自体は変更不要。

    2026-09-07 に外した body / head は列を出さなくなるが、CSV 側の列は
    マージ（preserve_existing_on_nan=True）で残り続ける。
    """
    by_title = gforms_client.question_id_by_title(form)
    q = conf['questions']
    grid_rows = conf['grid_rows']
    required_titles = [q[key] for key in grid_rows] + [q['emotions'], q['note']]
    missing = [t for t in required_titles if t not in by_title]
    if missing:
        raise ValueError(
            f'フォームに質問がない: {missing} / 実際: {list(by_title)}。'
            'setup-form --update で合わせること')

    known = {v['label'] for v in conf['vocabulary']}
    rows = []
    unknown_all = set()
    for res in responses:
        grid_values = {}
        for key in grid_rows:
            v = gforms_client.answer_values(res, by_title[q[key]])
            grid_values[key] = v[0] if v else pd.NA
        emotions = gforms_client.answer_values(res, by_title[q['emotions']])
        note = gforms_client.answer_values(res, by_title[q['note']])
        unknown_all |= {e for e in emotions if e not in known}
        row = {
            'timestamp': submitted_at(res),
            # 複数選択は配列で返るので分割不要。区切り文字は CSV 側の都合
            'emotions': ';'.join(emotions) if emotions else pd.NA,
            'note': note[0] if note and note[0] else pd.NA,
        }
        row.update(grid_values)
        rows.append(row)

    if unknown_all:
        print(f"警告: 定義にない選択肢 {sorted(unknown_all)}"
              f"（config/emotion_def.yaml の vocabulary と不一致）",
              file=sys.stderr)

    columns = ['timestamp', 'date'] + grid_rows + ['emotions', 'note']
    df = pd.DataFrame(rows, columns=['timestamp'] + grid_rows + ['emotions', 'note'])
    if df.empty:
        return df.assign(date=pd.Series(dtype='object'))[columns]

    df['timestamp'] = to_jst(df['timestamp'])
    # 日境界の補正はしない（深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.date
    # グリッド（RADIO）の回答は textAnswers に文字列で入る（"3"）。
    # 未回答・パース不能でも落ちないよう coerce → nullable Int64 にする
    for key in grid_rows:
        df[key] = pd.to_numeric(df[key], errors='coerce').astype('Int64')
    return df[columns]


def cmd_fetch(args, out=None):
    conf = load_def()
    if not conf.get('form_id'):
        raise ValueError(
            f'form_id が未設定: {DEF_FILE}。先に setup-form を実行すること')

    form, responses = cli.fetch_responses(conf['form_id'],
                                          non_interactive=args.non_interactive)
    df = build_dataframe(form, responses, conf)
    cli.warn_if_no_responses(responses, cli.read_existing(OUT_FILE))

    # 語彙を変えたら過去データを読み違えないよう、構成が変わった時刻を残す
    record_history(form, checkbox_choices(form, conf['questions']['emotions']),
                   VOCAB_HISTORY_FILE, '語彙バージョン')
    record_history(form, grid_row_titles(form), GRID_HISTORY_FILE, 'グリッド行構成')

    cli.save_merged(df, OUT_FILE, 'timestamp', preserve_existing_on_nan=True, out=out)


def cmd_show(args):
    if args.update:
        # 取得ログは stderr に寄せ、stdout は markdown 専用に保つ
        cmd_fetch(argparse.Namespace(non_interactive=False), out=sys.stderr)

    if not OUT_FILE.exists():
        print(f'エラー: {OUT_FILE} が存在しません', file=sys.stderr)
        sys.exit(1)

    vmap = render.valence_map(load_def())
    df_all = store.load_entries()

    today = dt.date.today()
    start = today - dt.timedelta(days=args.days - 1)
    df = df_all[df_all['timestamp'].dt.date >= start].reset_index(drop=True)

    print(f'# 気分記録（{start:%Y-%m-%d} 〜 {today:%Y-%m-%d}）\n')
    # 記録が無いのは故障ではない（断続的な記録でもトレンド用途は成立する）ので
    # 0件でも正常終了する。CSV 自体が無い場合だけ上で落としてある。
    # 被覆は統計の但し書きとして出すだけで、上げるべき目標としては出さない
    print(f"記録 {len(df)}件 / {df['date'].nunique()}日に記録あり"
          f'（{args.days}日中）\n')

    print('## 記録\n')
    print(render.render_entries(df))
    print('\n## 日内の変化\n')
    print(render.render_intraday(df))
    print('\n## 陽性感情\n')
    print(render.render_positive(df, df_all, vmap, today))
    print('\n## 語の出現回数\n')
    print(render.render_vocab(df, vmap))


def main():
    parser = argparse.ArgumentParser(description='気分記録（Google Form）')
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
