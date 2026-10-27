"""
def yaml の questions（順序付きリスト）だけで動くフォームのスキーマ

日次記録（朝・夜）で育てた形（Issue #167 / #176）を、固有処理を持たないフォーム
すべてに使う。新しいフォームは config/<key>_def.yaml とレジストリ1行で動く
（docs/forms.md の「新しいフォームの追加手順」）。列名・型・グリッド行・表示
ラベルはすべて yaml から導出し、コード側に複製を持たない。

def yaml のトップレベル:
  form_id / form_title: setup-form が使う（form_id は書き戻される）
  grid_title または grids: グリッド item の見出し
  score: グリッドの列（low / high / low_label / high_label）
  questions: 設問の順序付きリスト（key / label / short / column / type /
      required / active / description / question_id / grid / legacy_question_ids）
  unit: day（既定。date が主キーで同じ日の回答は最後の1件）
        | response（timestamp が主キーで回答ごとに1行）
  day_start_hour: この時刻より前の回答は前日に帰属する（既定 0 = 暦日のまま）
  source: 指定すると source 列を作り、この値を入れる（日次記録・朝の form / sheet）
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from lib.clients import gforms_client
from lib.forms.responses import submitted_at, to_jst

UNITS = ('day', 'response')


def unit(conf: dict) -> str:
    u = conf.get('unit', 'day')
    if u not in UNITS:
        raise ValueError(f'未知の unit: {u!r}（{"/".join(UNITS)}）')
    return u


def key_column(conf: dict) -> str:
    """CSV の主キー（マージキー）"""
    return 'date' if unit(conf) == 'day' else 'timestamp'


def _time_column(conf: dict) -> str:
    """回答時刻の列。day は「その日の採用回答の時刻」なので updated_at"""
    return 'updated_at' if unit(conf) == 'day' else 'timestamp'


def active_questions(conf: dict) -> list:
    """active な設問だけを yaml の並び順で返す（生きたフォームの構成）"""
    return [q for q in conf['questions'] if q.get('active', True)]


def grid_rows(conf: dict) -> list:
    """active なグリッド行の設問（フォームのグリッド item になる行）"""
    return [q for q in active_questions(conf) if q['type'] == 'grid']


def grid_groups(conf: dict) -> list:
    """フォーム上のグリッド item ごとの (タイトル, 行の設問リスト) を並び順で返す

    yaml に grids があれば、各行の grid キーで振り分ける（行の並びは
    questions の並び順）。無ければ grid_title の1グリッドに全行が入る。
    グリッド行が無ければ空リスト。
    """
    rows = grid_rows(conf)
    if 'grids' not in conf:
        return [(conf['grid_title'], rows)] if rows else []
    return [(g['title'], [q for q in rows if q.get('grid') == g['key']])
            for g in conf['grids']]


def text_like_questions(conf: dict) -> list:
    """active な text/number の設問（フォームの text item になるもの）"""
    return [q for q in active_questions(conf) if q['type'] in ('text', 'number')]


def columns(conf: dict) -> list:
    """CSV の列順。active/inactive を問わず全設問の列を含む
    （退役した設問も過去データが読めるよう列は残す）
    """
    cols = ['date', 'updated_at'] if unit(conf) == 'day' else ['timestamp', 'date']
    if conf.get('source'):
        cols.append('source')
    cols += [q['column'] for q in conf['questions']]
    return cols


def score_columns(conf: dict) -> list:
    """グリッド（1〜5）の CSV 列。active/inactive を問わない
    （dtype 補正はどちらも Int64 に揃えるため）
    """
    return [q['column'] for q in conf['questions'] if q['type'] == 'grid']


def number_columns(conf: dict) -> list:
    """数値設問の CSV 列。active/inactive を問わない"""
    return [q['column'] for q in conf['questions'] if q['type'] == 'number']


def text_columns(conf: dict) -> list:
    """自由記述の CSV 列。active/inactive を問わない"""
    return [q['column'] for q in conf['questions'] if q['type'] == 'text']


def display_labels(conf: dict) -> list:
    """表示用の (列名, ラベル) リスト。text と inactive は除く

    ラベルは short があればそちら。label は設問文（フォームに出る文）で、
    表のヘッダとしては長すぎることがあるため分けている。
    """
    return [(q['column'], q.get('short', q['label']))
            for q in active_questions(conf) if q['type'] != 'text']


def text_labels(conf: dict) -> list:
    """自由記述の (列名, ラベル) リスト。inactive は除く"""
    return [(q['column'], q.get('short', q['label']))
            for q in active_questions(conf) if q['type'] == 'text']


def response_date(ts: pd.Timestamp, day_start_hour: int) -> dt.date:
    """回答時刻（JST naive）から帳票上の date を作る

    day_start_hour 時より前の回答は前日に帰属する。day_start_hour=0（朝）は
    補正なし。day_start_hour=5（夜）は 00:00-04:59 の回答が前日になる。
    """
    d = ts.date()
    if ts.hour < day_start_hour:
        d = d - dt.timedelta(days=1)
    return d


def build_items(conf):
    """yaml の定義からフォームの item spec リストを組み立てる

    grid item がまとめて先頭、続けて active な text/number の設問が
    yaml の並び順で1 item ずつ続く（number は textQuestion として作る。
    Forms API の TextQuestion に数値バリデーションは無いため、数値化は
    fetch 側 build_dataframe() が pd.to_numeric(errors='coerce') で行う）。

    yaml に question_id があれば item spec へ明示する（Issue #176）。
    sync_questions() 側でこれを優先して突き合わせることで、中間の設問を
    退役させても後続の設問の questionId が付け替わらなくなる。
    question_id が無い（backfill 前）設問は従来どおり kind-FIFO で
    対応付く。
    """
    items = []
    if grid_rows(conf):
        s = conf['score']
        items += [
            gforms_client.grid_item(title, [e['label'] for e in entries], s['low'], s['high'],
                                    s['low_label'], s['high_label'],
                                    required=[e.get('required', False) for e in entries])
            for title, entries in grid_groups(conf)
        ]
    for e in text_like_questions(conf):
        items.append(gforms_client.text_item(
            e['label'], required=e.get('required', False),
            question_id=e.get('question_id')))
    return items


def backfill_question_ids(conf, form) -> dict:
    """sync 後の form から text/number 設問の {key: questionId} を作る

    grid 行は対象外（grid 行は FIFO のまま）。label がフォームに無い設問
    （退役済みなど）はスキップする。
    """
    by_title = gforms_client.question_id_by_title(form)
    return {e['key']: by_title[e['label']] for e in text_like_questions(conf)
            if e['label'] in by_title}


def _with_all_columns(df, conf):
    """退役（active: false）した設問の列を欠測として補い、CSV の列順に揃える

    行の組み立ては active な設問だけを見るが、CSV の列は退役分も残す
    （過去データを読めなくしないため）。補わずに列選択すると、設問を
    退役させた次の fetch が KeyError で落ちる。
    """
    cols = columns(conf)
    for col in cols:
        if col not in df.columns:
            df[col] = pd.NA
    return df[cols]


def build_dataframe(form, responses, conf):
    """回答リストを CSV スキーマの DataFrame にする

    unit: day では同一 date に複数回答があるときは最後（updated_at 昇順）の
    ものだけを残す（date が主キーで、CSV に複数行を残さない）。
    date は day_start_hour 境界で作る（response_date() を参照）。
    """
    by_title = gforms_client.question_id_by_title(form)
    grid_entries = grid_rows(conf)
    text_like_entries = text_like_questions(conf)
    number_cols = [e['column'] for e in text_like_entries if e['type'] == 'number']
    time_col = _time_column(conf)
    source = conf.get('source')

    required_titles = [e['label'] for e in grid_entries] + [e['label'] for e in text_like_entries]
    missing = [t for t in required_titles if t not in by_title]
    if missing:
        raise ValueError(
            f'フォームに質問がない: {missing} / 実際: {list(by_title)}。'
            'setup-form --update で合わせること')

    rows = []
    for res in responses:
        row = {time_col: submitted_at(res)}
        if source:
            row['source'] = source
        for e in grid_entries:
            # 別グリッドへ移した行は questionId が変わる。移す前の回答は
            # 旧 id のまま API に残るので legacy_question_ids から引く
            v = []
            for qid in [by_title[e['label']], *e.get('legacy_question_ids', [])]:
                v = gforms_client.answer_values(res, qid)
                if v:
                    break
            row[e['column']] = v[0] if v else pd.NA
        for e in text_like_entries:
            v = gforms_client.answer_values(res, by_title[e['label']])
            row[e['column']] = v[0] if v and v[0] else pd.NA
        rows.append(row)

    base_columns = ([time_col] + (['source'] if source else [])
                    + [e['column'] for e in grid_entries]
                    + [e['column'] for e in text_like_entries])
    df = pd.DataFrame(rows, columns=base_columns)
    if df.empty:
        df = df.assign(date=pd.Series(dtype='object'))
        return _with_all_columns(df, conf)

    df[time_col] = to_jst(df[time_col])
    day_start_hour = conf.get('day_start_hour', 0)
    df['date'] = df[time_col].apply(lambda t: response_date(t, day_start_hour))
    for e in grid_entries:
        df[e['column']] = pd.to_numeric(df[e['column']], errors='coerce').astype('Int64')
    for col in number_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Float64')

    df = df.sort_values(time_col)
    if unit(conf) == 'day':
        # 同一 date に複数回答があれば最後（updated_at 昇順で最後）を採る。
        # API の返却順は時刻順とは限らないので、必ずソートしてから落とす
        df = df.drop_duplicates(subset=['date'], keep='last')

    df = _with_all_columns(df, conf)
    return df.sort_values(key_column(conf)).reset_index(drop=True)


def carry_retired_values(df, existing, conf):
    """退役（active: false）した設問の値を既存 CSV から引き継ぐ

    fetch は毎回全回答を取り直して主キーごとに行を置換するが、
    build_dataframe は active な設問しか読まないので、退役した列は常に
    欠測になる。そのまま置換すると、退役前に記録した値が次の fetch で
    すべて消える。退役した設問は新しい回答を受けないので、既存 CSV が正本。
    """
    retired = [q['column'] for q in conf['questions'] if not q.get('active', True)]
    if not retired or existing is None or existing.empty:
        return df
    key = key_column(conf)
    prev = existing.set_index(pd.to_datetime(existing[key]))
    keys = pd.to_datetime(df[key])
    for col in retired:
        if col in prev.columns:
            df[col] = keys.map(prev[col]).to_numpy()
    return df


def load_entries(csv_file: Path, conf: dict) -> pd.DataFrame:
    """CSV を主キー昇順で読む。

    グリッドのスコアは未回答・パース不能を 0 に潰さず nullable Int64 の
    まま扱う。数値設問は小数もありうるため nullable Float64。どちらも
    Forms API の TextQuestion に数値バリデーションが無いためパース不能値が
    入りうるが、それも 0 でなく NA にする。

    CSV が無ければ（フォーム未作成など）、正しい列・dtype の空
    DataFrame を返す（show が落ちないように。マウント忘れの検出は
    require_private_path 側が担っている）。

    列が無い CSV（スキーマ変更前）は backfill する。列ごと無いのは
    「未設問」であって「0件」ではないので、全欠測の列として補う。
    """
    cols = columns(conf)
    csv_file = Path(csv_file)
    df = pd.read_csv(csv_file) if csv_file.exists() else pd.DataFrame(columns=cols)

    for col in cols:
        if col not in df.columns:
            df[col] = pd.NA
    for col in score_columns(conf):
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    for col in number_columns(conf):
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Float64')
    for col in text_columns(conf):
        df[col] = df[col].fillna('')
    df['date'] = pd.to_datetime(df['date'], format='ISO8601')
    if unit(conf) == 'response':
        df['timestamp'] = pd.to_datetime(df['timestamp'], format='ISO8601')
    return df[cols].sort_values(key_column(conf)).reset_index(drop=True)
