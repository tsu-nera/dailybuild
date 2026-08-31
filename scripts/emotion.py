#!/usr/bin/env python
# coding: utf-8
"""
気分記録（Google Form）

setup-form でフォームを生成し、fetch で回答を直接取得する。
回答先スプレッドシートは経由しない（Forms API に回答先のリンク設定が
無いため、そこだけ手作業として残ってしまう）。
"""

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml
from lib.clients import gforms_api
from lib.emotion import render, store
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
DEF_FILE = BASE_DIR / 'config/emotion_def.yaml'
# show 側と同じパスを指すよう store から借りる
OUT_FILE = store.CSV_FILE
VOCAB_HISTORY_FILE = require_private_path(
    BASE_DIR / 'data/emotion_vocab_history.csv')
# グリッドの行構成（並び順）の版履歴。仕組みは VOCAB_HISTORY_FILE と同じ
# （update_vocab_history は labels の版管理そのものなので、行タイトルの
# リストを渡してそのまま流用する。ファイルだけ分けているのは、語彙と
# グリッド行が別の構成要素で、同じファイルに混ぜると「何の版か」が
# revision_id だけでは読み取れなくなるため）
GRID_HISTORY_FILE = require_private_path(
    BASE_DIR / 'data/emotion_grid_history.csv')

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
    choices = [v['label'] for v in conf['vocabulary']]
    grid_rows = conf['grid_rows']
    rows = [q[key] for key in grid_rows]
    grid_required = conf.get('grid_required', {})
    # 未指定の行は required 扱い（既定は安全側）
    required = [grid_required.get(key, True) for key in grid_rows]
    return [
        gforms_api.grid_item(conf['grid_title'], rows, s['low'], s['high'],
                             s['low_label'], s['high_label'], required=required),
        gforms_api.checkbox_item(q['emotions'], choices, required=True),
        gforms_api.text_item(q['note'], required=False),
    ]


def _csv_max_timestamp():
    """data/emotion.csv の最新 timestamp。ファイルが無い/空なら None"""
    if not OUT_FILE.exists():
        return None
    df = pd.read_csv(OUT_FILE, usecols=['timestamp'], parse_dates=['timestamp'])
    if df.empty:
        return None
    return df['timestamp'].max()


def _response_timestamp(res):
    """フォーム回答1件の送信時刻を JST naive で返す。取れなければ None"""
    ts = res.get('lastSubmittedTime') or res.get('createTime')
    if not ts:
        return None
    return pd.to_datetime(ts, format='ISO8601', utc=True).tz_convert(TZ).tz_localize(None)


def has_unfetched_responses(responses, csv_max_timestamp) -> bool:
    """フォーム側の回答に data/emotion.csv へ未取り込みのものがあるか

    allow_kind_replace の deleteItem は questionId → どの質問かの対応付けを
    失わせるため、CSV に materialize されていない回答があると、その回答の
    値は削除後は読めなくなる（#105 の preserve_existing_on_nan は「CSV に
    既にある値」しか守れない）。判定は timestamp ベース: CSV の最新
    timestamp より新しい回答が1件でもあれば未取り込みとみなす
    """
    if not responses:
        return False
    if csv_max_timestamp is None:
        return True
    for res in responses:
        ts = _response_timestamp(res)
        if ts is not None and ts > csv_max_timestamp:
            return True
    return False


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
        if args.allow_kind_replace:
            leftover = gforms_api.preview_kind_mismatch(items, existing_form)
            if leftover:
                responses = gforms_api.list_responses(service, conf['form_id'])
                if has_unfetched_responses(responses, _csv_max_timestamp()):
                    print('中止: data/emotion.csv に未取り込みの回答が'
                          'フォーム側にある。削除すると questionId の対応'
                          '付けが失われ、その回答の値が読めなくなる。'
                          '先に `uv run scripts/emotion.py fetch` を実行して'
                          'から、改めて --update --allow-kind-replace を'
                          '実行すること', file=sys.stderr)
                    sys.exit(1)
                print('質問の種類が変わるため、次の既存の質問を削除する'
                      '（questionId の対応付けが失われる。値そのものは'
                      'API レスポンスに残るが、旧 questionId が無いとどの'
                      '質問かを引けない。data/emotion.csv に materialize '
                      '済みの値は保持される）:')
                for i in leftover:
                    print(f"  - {i.get('title')} "
                         f"({gforms_api._question_kind(i)})")
        gforms_api.sync_questions(service, conf['form_id'], items,
                                  existing_form=existing_form,
                                  allow_kind_replace=args.allow_kind_replace)
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


def build_dataframe(form, responses, conf):
    """回答リストを CSV スキーマの DataFrame にする

    グリッドの行（conf['grid_rows']、既定は score/body/head）は列として
    そのまま出力する。行を足すだけで列が増える構成にしてあるので、将来
    快・達成感の行を足しても build_dataframe 自体は変更不要。
    """
    by_title = gforms_api.question_id_by_title(form)
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
            v = gforms_api.answer_values(res, by_title[q[key]])
            grid_values[key] = v[0] if v else pd.NA
        emotions = gforms_api.answer_values(res, by_title[q['emotions']])
        note = gforms_api.answer_values(res, by_title[q['note']])
        unknown_all |= {e for e in emotions if e not in known}
        row = {
            'timestamp': res.get('lastSubmittedTime') or res.get('createTime'),
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

    # API は RFC3339 の UTC を返す。他データと揃えて JST の naive にする
    ts = pd.to_datetime(df['timestamp'], format='ISO8601', utc=True)
    # 秒に丸める。ミリ秒は他のCSVと粒度が揃わないうえ、マージキーとして
    # 無駄に細かい（同一秒に2回送ることは無い）
    df['timestamp'] = ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.floor('s')
    # 日境界の補正はしない（深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.date
    # グリッド（RADIO）の回答は textAnswers に文字列で入る（"3"）。
    # 未回答・パース不能でも落ちないよう coerce → nullable Int64 にする
    for key in grid_rows:
        df[key] = pd.to_numeric(df[key], errors='coerce').astype('Int64')
    return df[columns]


def _checkbox_choices(form, title):
    """フォームの実際のチェックボックス選択肢を title から引く。無ければ None"""
    for item in form.get('items', []):
        if item.get('title') != title:
            continue
        choice = item.get('questionItem', {}).get('question', {}).get(
            'choiceQuestion')
        if choice:
            return [o['value'] for o in choice.get('options', [])]
    return None


def _grid_row_titles(form):
    """フォームの実際のグリッド行タイトルを出現順で返す。無ければ None"""
    for item in form.get('items', []):
        group = item.get('questionGroupItem')
        if group:
            return [q.get('rowQuestion', {}).get('title')
                   for q in group.get('questions', [])]
    return None


def update_vocab_history(revision_id, labels, path, now=None) -> bool:
    """語彙が前回と違えば1行追記する。追記したら True

    per-row の版列は持たない（毎回全件取り直すのでマージが濁る）。
    語彙が変わった時刻だけを別ファイルに残す。

    判定は revisionId でなく **labels 自体**で行う。revisionId は質問文の
    変更や `setup-form --update` の空打ちでも上がるため、これをキーにすると
    語彙が同じ行が積み上がり、「いつ語彙が変わったか」を知るのに結局
    labels を diff する羽目になる（このファイルの存在意義が消える）。
    revision_id 列は「その語彙が最初に観測された版」の記録として残す。
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
        # revisionId が取れない場合も語彙は記録する。版が不明なことと
        # 語彙変更を取りこぼすことでは、後者のほうがはるかに高くつく
        'revision_id': '' if revision_id is None else str(revision_id),
        'labels': label_str,
    }])

    ensure_dir(path.parent)
    if path.exists() and path.stat().st_size > 0:
        row.to_csv(path, mode='a', header=False, index=False)
    else:
        row.to_csv(path, mode='w', header=True, index=False)
    return True


def cmd_fetch(args, out=None):
    # show --update から呼ぶときは stdout を markdown 専用に保つため stderr を渡す
    out = out or sys.stdout
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

    revision_id = form.get('revisionId')
    if revision_id is None:
        print('警告: forms.get の応答に revisionId が無い。'
              '語彙は記録するが版は空になる', file=sys.stderr)
    labels = _checkbox_choices(form, conf['questions']['emotions'])
    if labels is None:
        print(f"警告: フォームに選択式の質問がない"
              f"（{conf['questions']['emotions']}）。"
              '語彙バージョン履歴を更新できない', file=sys.stderr)
    elif update_vocab_history(revision_id, labels, VOCAB_HISTORY_FILE):
        print(f'語彙バージョン履歴を追記: revision {revision_id} / '
              f'{len(labels)}個', file=sys.stderr)

    grid_rows_titles = _grid_row_titles(form)
    if grid_rows_titles is None:
        print('警告: フォームにグリッド質問がない。'
              'グリッド行構成の履歴を更新できない', file=sys.stderr)
    elif update_vocab_history(revision_id, grid_rows_titles, GRID_HISTORY_FILE):
        print(f'グリッド行構成の履歴を追記: revision {revision_id} / '
              f'{len(grid_rows_titles)}行', file=sys.stderr)

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
    p_setup.add_argument('--update', action='store_true',
                         help='既存フォームの質問文・選択肢を yaml に合わせる')
    p_setup.add_argument('--allow-kind-replace', action='store_true',
                         help='質問の種類が変わる移行を許可し、対応しない既存の'
                              '質問を削除する（--update と併用。'
                              '例: scaleQuestion → questionGroupItem 化。'
                              '削除される質問は実行前に列挙する）')
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
