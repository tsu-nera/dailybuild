"""
Forms API の回答・フォーム構成の読み取り（全フォーム共通）

- 回答時刻の JST 化
- CSV に未取り込みの回答の検出（--allow-kind-replace の削除前ガード）
- 選択肢・グリッド行構成の版履歴（*_vocab_history.csv / *_grid_history.csv）
"""

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

from lib.utils.private_data import ensure_dir

TZ = 'Asia/Tokyo'


def submitted_at(res: dict):
    """回答1件の送信時刻（RFC3339 の UTC 文字列）。最終更新を優先する"""
    return res.get('lastSubmittedTime') or res.get('createTime')


def to_jst(series: pd.Series) -> pd.Series:
    """API の RFC3339（UTC）を、他データと揃えて JST の naive にする

    秒に丸める。ミリ秒は他のCSVと粒度が揃わないうえ、マージキーとして
    無駄に細かい（同一秒に2回送ることは無い）。
    """
    ts = pd.to_datetime(series, format='ISO8601', utc=True)
    return ts.dt.tz_convert(TZ).dt.tz_localize(None).dt.floor('s')


def _response_timestamp(res):
    """フォーム回答1件の送信時刻を JST naive で返す。取れなければ None"""
    ts = submitted_at(res)
    if not ts:
        return None
    return pd.to_datetime(ts, format='ISO8601', utc=True).tz_convert(TZ).tz_localize(None)


def csv_max_timestamp(path: Path, column: str):
    """CSV の column（日時）の最新値。ファイルが無い/空なら None"""
    path = Path(path)
    if not path.exists():
        return None
    df = pd.read_csv(path, usecols=[column])
    if df.empty:
        return None
    return pd.to_datetime(df[column], format='ISO8601').max()


def has_unfetched_responses(responses, csv_max_timestamp) -> bool:
    """フォーム側の回答に CSV へ未取り込みのものがあるか

    allow_kind_replace の deleteItem は questionId → どの質問かの対応付けを
    失わせるため、CSV に materialize されていない回答があると、その回答の
    値は削除後は読めなくなる（preserve_existing_on_nan は「CSV に
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


def checkbox_choices(form, title):
    """フォームの実際のチェックボックス選択肢を title から引く。無ければ None"""
    for item in form.get('items', []):
        if item.get('title') != title:
            continue
        choice = item.get('questionItem', {}).get('question', {}).get(
            'choiceQuestion')
        if choice:
            return [o['value'] for o in choice.get('options', [])]
    return None


def grid_row_titles(form):
    """フォームの実際のグリッド行タイトルを出現順で返す（複数グリッドは連結）。
    無ければ None
    """
    titles = [q.get('rowQuestion', {}).get('title')
              for item in form.get('items', [])
              for q in item.get('questionGroupItem', {}).get('questions', [])]
    return titles or None


def update_vocab_history(revision_id, labels, path, now=None) -> bool:
    """labels（選択肢・グリッド行タイトルのリスト）が前回と違えば1行追記する。追記したら True

    per-row の版列は持たない（毎回全件取り直すのでマージが濁る）。
    構成が変わった時刻だけを別ファイルに残す。

    判定は revisionId でなく **labels 自体**で行う。revisionId は質問文の
    変更や `setup-form --update` の空打ちでも上がるため、これをキーにすると
    構成が同じ行が積み上がり、「いつ構成が変わったか」を知るのに結局
    labels を diff する羽目になる（このファイルの存在意義が消える）。
    revision_id 列は「その構成が最初に観測された版」の記録として残す。
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
        # revisionId が取れない場合も構成は記録する。版が不明なことと
        # 構成の変更を取りこぼすことでは、後者のほうがはるかに高くつく
        'revision_id': '' if revision_id is None else str(revision_id),
        'labels': label_str,
    }])

    ensure_dir(path.parent)
    if path.exists() and path.stat().st_size > 0:
        row.to_csv(path, mode='a', header=False, index=False)
    else:
        row.to_csv(path, mode='w', header=True, index=False)
    return True


def record_history(form, labels, path, what: str) -> None:
    """update_vocab_history を呼び、結果を stderr に出す。labels が None なら警告だけ出す

    what は「グリッド行構成」「語彙バージョン」のような履歴の名前（ログ用）。
    """
    revision_id = form.get('revisionId')
    if labels is None:
        print(f'警告: フォームに対象の質問がない。{what}の履歴を更新できない',
              file=sys.stderr)
        return
    if revision_id is None:
        print(f'警告: forms.get の応答に revisionId が無い。'
              f'{what}は記録するが版は空になる', file=sys.stderr)
    if update_vocab_history(revision_id, labels, path):
        print(f'{what}の履歴を追記: revision {revision_id} / {len(labels)}個',
              file=sys.stderr)
