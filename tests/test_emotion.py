"""気分記録（Issue #87）のスコア列・語彙バージョン履歴・質問突き合わせのテスト

実機の Google Forms API は叩かず、変換ロジックだけを検証する。
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.clients import gforms_api
from lib.emotion import render, store


def _load_script():
    """scripts/ 配下はパッケージではないのでファイルから直接ロードする"""
    path = BASE_DIR / 'scripts' / 'emotion.py'
    spec = importlib.util.spec_from_file_location('emotion', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['emotion'] = module
    spec.loader.exec_module(module)
    return module


emotion = _load_script()


CONF = {
    'questions': {
        'score': 'いまの気分', 'body': '身体の軽さ', 'head': '頭の冴え',
        'emotions': 'いまの気持ち', 'note': '何があった？',
    },
    'grid_rows': ['score', 'body', 'head'],
    'score': {'low': 1, 'high': 5, 'low_label': '悪い', 'high_label': '良い'},
    'vocabulary': [
        {'label': '楽しい・うれしい', 'valence': 'pos', 'arousal': 'high'},
        {'label': 'イライラ', 'valence': 'neg', 'arousal': 'high'},
    ],
}


def _form():
    return {
        'items': [
            {
                'title': 'いまの状態',
                'questionGroupItem': {
                    'questions': [
                        {'questionId': 'q_score', 'required': True,
                         'rowQuestion': {'title': 'いまの気分'}},
                        {'questionId': 'q_body', 'required': True,
                         'rowQuestion': {'title': '身体の軽さ'}},
                        {'questionId': 'q_head', 'required': True,
                         'rowQuestion': {'title': '頭の冴え'}},
                    ],
                    'grid': {'columns': {
                        'type': 'RADIO',
                        'options': [{'value': str(n)} for n in range(1, 6)],
                    }},
                },
            },
            {
                'title': 'いまの気持ち',
                'questionItem': {'question': {
                    'questionId': 'q_emotions',
                    'choiceQuestion': {
                        'type': 'CHECKBOX',
                        'options': [{'value': '楽しい・うれしい'}, {'value': 'イライラ'}],
                    },
                }},
            },
            {
                'title': '何があった？',
                'questionItem': {'question': {
                    'questionId': 'q_note',
                    'textQuestion': {'paragraph': False},
                }},
            },
        ],
    }


def _response(timestamp, score=None, body=None, head=None, emotions=None, note=None):
    answers = {}
    if score is not None:
        answers['q_score'] = {'textAnswers': {'answers': [{'value': score}]}}
    if body is not None:
        answers['q_body'] = {'textAnswers': {'answers': [{'value': body}]}}
    if head is not None:
        answers['q_head'] = {'textAnswers': {'answers': [{'value': head}]}}
    if emotions is not None:
        answers['q_emotions'] = {
            'textAnswers': {'answers': [{'value': e} for e in emotions]}}
    if note is not None:
        answers['q_note'] = {'textAnswers': {'answers': [{'value': note}]}}
    return {'lastSubmittedTime': timestamp, 'answers': answers}


# --- build_dataframe ---

def test_build_dataframe_score_is_nullable_int_and_survives_missing():
    responses = [
        _response('2026-08-20T10:00:00Z', score='3', emotions=['イライラ'], note='仕事'),
        _response('2026-08-21T10:00:00Z', emotions=['楽しい・うれしい'], note='散歩'),
    ]
    df = emotion.build_dataframe(_form(), responses, CONF)
    assert str(df['score'].dtype) == 'Int64'
    assert df['score'].iloc[0] == 3
    assert pd.isna(df['score'].iloc[1])


def test_build_dataframe_column_order():
    df = emotion.build_dataframe(_form(), [], CONF)
    assert list(df.columns) == \
        ['timestamp', 'date', 'score', 'body', 'head', 'emotions', 'note']


def test_build_dataframe_empty_has_score_column():
    df = emotion.build_dataframe(_form(), [], CONF)
    assert df.empty
    assert 'score' in df.columns


def test_build_dataframe_body_head_are_nullable_int_and_survive_missing():
    """身体・頭（Issue #104）も score と同じ扱い。値が無い過去回答は NA になり、
    0（最悪）に潰さない"""
    responses = [
        _response('2026-08-20T10:00:00Z', score='3', body='4', head='2',
                  emotions=['イライラ'], note='仕事'),
        # グリッド化前の回答を模す: score だけ無い時代とは別に、body/head が
        # 未設問だった時代（今回の移行直後）を model 化する
        _response('2026-08-21T10:00:00Z', score='5', emotions=['楽しい・うれしい'],
                  note='散歩'),
    ]
    df = emotion.build_dataframe(_form(), responses, CONF)
    assert str(df['body'].dtype) == 'Int64'
    assert str(df['head'].dtype) == 'Int64'
    assert df['body'].iloc[0] == 4
    assert df['head'].iloc[0] == 2
    assert pd.isna(df['body'].iloc[1])
    assert pd.isna(df['head'].iloc[1])


# --- update_vocab_history ---

def test_update_vocab_history_creates_file(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    now = dt.datetime(2026, 8, 26, 10, 0, 0)
    changed = emotion.update_vocab_history('1', ['楽しい・うれしい', 'イライラ'], path, now=now)
    assert changed is True
    df = pd.read_csv(path, dtype=str)
    assert len(df) == 1
    assert df.iloc[0]['revision_id'] == '1'
    assert df.iloc[0]['labels'] == '楽しい・うれしい;イライラ'
    assert df.iloc[0]['first_seen'] == '2026-08-26 10:00:00'


def test_update_vocab_history_same_labels_no_append(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    emotion.update_vocab_history('1', ['楽しい・うれしい'], path)
    changed = emotion.update_vocab_history('1', ['楽しい・うれしい'], path)
    assert changed is False
    assert len(pd.read_csv(path, dtype=str)) == 1


def test_update_vocab_history_new_revision_same_labels_no_append(tmp_path):
    """質問文の変更や setup-form --update の空打ちで revisionId だけが上がる。

    これで行が増えると「いつ語彙が変わったか」を知るのに labels を diff する
    羽目になり、このファイルの存在意義が消える（実機で発生: 00000008 -> 00000009）。
    """
    path = tmp_path / 'emotion_vocab_history.csv'
    emotion.update_vocab_history('00000008', ['楽しい・うれしい', 'イライラ'], path)
    changed = emotion.update_vocab_history('00000009', ['楽しい・うれしい', 'イライラ'], path)
    assert changed is False
    assert len(pd.read_csv(path, dtype=str)) == 1


def test_update_vocab_history_new_labels_append(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    emotion.update_vocab_history('1', ['楽しい・うれしい'], path)
    changed = emotion.update_vocab_history('2', ['楽しい・うれしい', 'イライラ'], path)
    assert changed is True
    df = pd.read_csv(path, dtype=str)
    assert len(df) == 2
    assert df.iloc[0]['revision_id'] == '1'
    assert df.iloc[1]['revision_id'] == '2'
    # 旧語彙の行が残る（過去データの読み方が失われない）
    assert df.iloc[0]['labels'] == '楽しい・うれしい'


def test_update_vocab_history_label_order_change_is_a_change(tmp_path):
    """並び替えもフォームの見た目が変わる = 別の版として記録する"""
    path = tmp_path / 'emotion_vocab_history.csv'
    emotion.update_vocab_history('1', ['楽しい・うれしい', 'イライラ'], path)
    changed = emotion.update_vocab_history('2', ['イライラ', '楽しい・うれしい'], path)
    assert changed is True
    assert len(pd.read_csv(path, dtype=str)) == 2


def test_update_vocab_history_zero_padded_revision_survives_roundtrip(tmp_path):
    path = tmp_path / 'emotion_vocab_history.csv'
    emotion.update_vocab_history('00000004', ['楽しい・うれしい'], path)
    df = pd.read_csv(path, dtype=str)
    assert df.iloc[0]['revision_id'] == '00000004'
    changed = emotion.update_vocab_history('00000004', ['楽しい・うれしい'], path)
    assert changed is False


def test_update_vocab_history_records_labels_without_revision(tmp_path):
    """revisionId が取れなくても語彙は記録する（取りこぼしのほうが高くつく）"""
    path = tmp_path / 'emotion_vocab_history.csv'
    changed = emotion.update_vocab_history(None, ['楽しい・うれしい'], path)
    assert changed is True
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    assert df.iloc[0]['revision_id'] == ''
    assert df.iloc[0]['labels'] == '楽しい・うれしい'


# --- gforms_api.sync_questions ---

def test_sync_questions_matches_by_kind_not_index():
    existing_form = {
        'items': [
            {
                'itemId': 'i1',
                'title': 'いまの気持ち',
                'questionItem': {'question': {
                    'questionId': 'q1',
                    'choiceQuestion': {'type': 'CHECKBOX', 'options': [{'value': 'old'}]},
                }},
            },
            {
                'itemId': 'i2',
                'title': 'ひとこと',
                'questionItem': {'question': {
                    'questionId': 'q2',
                    'textQuestion': {'paragraph': False},
                }},
            },
        ],
    }

    items = [
        gforms_api.scale_item('いまの気分', 1, 5, '悪い', '良い'),
        gforms_api.checkbox_item('いまの気持ち', ['a', 'b']),
        gforms_api.text_item('何があった？'),
    ]

    service = MagicMock()
    captured = {}

    def fake_execute():
        return {}

    def fake_batch_update(formId, body):
        captured['body'] = body
        m = MagicMock()
        m.execute.side_effect = fake_execute
        return m

    service.forms.return_value.batchUpdate.side_effect = fake_batch_update

    gforms_api.sync_questions(service, 'form1', items, existing_form=existing_form)

    body = captured['body']
    requests = body['requests']

    creates = [r['createItem'] for r in requests if 'createItem' in r]
    updates = [r['updateItem'] for r in requests if 'updateItem' in r]

    assert len(creates) == 1
    assert creates[0]['location']['index'] == 0
    assert 'scaleQuestion' in creates[0]['item']['questionItem']['question']

    assert len(updates) == 2
    checkbox_update = next(u for u in updates
                           if 'choiceQuestion' in u['item']['questionItem']['question'])
    text_update = next(u for u in updates
                       if 'textQuestion' in u['item']['questionItem']['question'])
    assert checkbox_update['location']['index'] == 1
    assert text_update['location']['index'] == 2
    # 実機で確認した Forms API の癖: questionId を明示しないと updateItem でも
    # 新しい questionId が割り当てられ、過去回答が読めなくなる。既存の
    # questionId を明示的に引き継いでいることを確認する
    assert checkbox_update['item']['questionItem']['question']['questionId'] == 'q1'
    assert text_update['item']['questionItem']['question']['questionId'] == 'q2'
    # createItem が先、updateItem が後ろに来ること
    assert list(requests).index({'createItem': creates[0]}) < \
        list(requests).index({'updateItem': checkbox_update})


def test_sync_questions_raises_on_unmatched_existing_item():
    existing_form = {
        'items': [
            {
                'itemId': 'i1',
                'title': '謎の質問',
                'questionItem': {'question': {
                    'questionId': 'q1',
                    'dateQuestion': {},
                }},
            },
        ],
    }
    items = [gforms_api.text_item('何があった？')]
    service = MagicMock()
    with pytest.raises(gforms_api.GoogleFormsError):
        gforms_api.sync_questions(service, 'form1', items, existing_form=existing_form)


def _existing_grid_form(row_ids):
    """行タイトルは実際のフォームの並びのまま（q_score/q_body/q_head の
    questionId を持つ3行）。row_ids は questionId のリスト（出現順）"""
    titles = ['いまの気分', '身体の軽さ', '頭の冴え']
    return {
        'items': [
            {
                'itemId': 'i_grid',
                'title': 'いまの状態',
                'questionGroupItem': {
                    'questions': [
                        {'questionId': qid, 'required': True,
                         'rowQuestion': {'title': t}}
                        for qid, t in zip(row_ids, titles)
                    ],
                    'grid': {'columns': {'type': 'RADIO',
                                         'options': [{'value': str(n)} for n in range(1, 6)]}},
                },
            },
        ],
    }


def _run_sync(items, existing_form):
    service = MagicMock()
    captured = {}

    def fake_batch_update(formId, body):
        captured['body'] = body
        m = MagicMock()
        m.execute.return_value = {}
        return m

    service.forms.return_value.batchUpdate.side_effect = fake_batch_update
    gforms_api.sync_questions(service, 'form1', items, existing_form=existing_form)
    return captured['body']['requests']


def test_sync_questions_grid_row_order_change_is_detected():
    """グリッドの行順を変えると、過去の「いまの気分」の questionId が
    別の行（頭の冴え）に付け替わることを検知する

    行の対応付けはタイトルでなく出現順（FIFO）。PHQ-9 の9問と同じ制約が
    グリッドの行にも効くことを固定するテスト（docs/forms.md 参照）。
    """
    existing_form = _existing_grid_form(['q_score', 'q_body', 'q_head'])
    # 行順を入れ替えた spec: 頭の冴え / 身体の軽さ / いまの気分
    reordered = gforms_api.grid_item(
        'いまの状態', ['頭の冴え', '身体の軽さ', 'いまの気分'], 1, 5, '悪い', '良い')

    requests = _run_sync([reordered], existing_form)
    updates = [r['updateItem'] for r in requests if 'updateItem' in r]
    assert len(updates) == 1
    questions = updates[0]['item']['questionGroupItem']['questions']

    # 出現順で対応付けているため、旧「いまの気分」(q_score) の questionId が
    # 新しい先頭行「頭の冴え」に付け替わってしまう
    assert questions[0]['rowQuestion']['title'] == '頭の冴え'
    assert questions[0]['questionId'] == 'q_score'
    # 逆に、末尾の「いまの気分」行は元の「頭の冴え」の questionId を引き継ぐ
    assert questions[2]['rowQuestion']['title'] == 'いまの気分'
    assert questions[2]['questionId'] == 'q_head'


def test_sync_questions_grid_add_row_preserves_existing_row_ids():
    """行を追加しても既存3行の questionId は保持される

    将来 快・達成感 の行を足すコストがこれで決まる。既存行の questionId が
    保持されていれば yaml の grid_rows に行を足すだけで済む。
    """
    existing_form = _existing_grid_form(['q_score', 'q_body', 'q_head'])
    extended = gforms_api.grid_item(
        'いまの状態', ['いまの気分', '身体の軽さ', '頭の冴え', '快'], 1, 5, '悪い', '良い')

    requests = _run_sync([extended], existing_form)
    updates = [r['updateItem'] for r in requests if 'updateItem' in r]
    assert len(updates) == 1
    questions = updates[0]['item']['questionGroupItem']['questions']

    assert len(questions) == 4
    assert questions[0]['questionId'] == 'q_score'
    assert questions[1]['questionId'] == 'q_body'
    assert questions[2]['questionId'] == 'q_head'
    # 追加された行には questionId を付けない（API に新規採番させる）
    assert 'questionId' not in questions[3]
    assert questions[3]['rowQuestion']['title'] == '快'


def test_question_id_by_title_reads_grid_rows():
    """question_id_by_title がグリッドの行名 -> questionId を引けること"""
    form = _existing_grid_form(['q_score', 'q_body', 'q_head'])
    by_title = gforms_api.question_id_by_title(form)
    assert by_title['いまの気分'] == 'q_score'
    assert by_title['身体の軽さ'] == 'q_body'
    assert by_title['頭の冴え'] == 'q_head'


# --- show（集計・表示）側 -------------------------------------------------
# 方針どおり markdown の文面はテストしない。欠測を捏造しないことだけを見る。

VMAP = {'落ち着いている': 'pos', 'つらい・重い': 'neg', '何も感じない': 'neu'}


def test_load_entries_keeps_missing_score_as_na(tmp_path, monkeypatch):
    """score 未設問時代（2026-08-26 より前）の空欄が 0 に潰れないこと

    0 に潰すと尺度の最下端「最悪の気分」として集計に混ざり、
    設問が無かっただけの期間を最悪だった期間として捏造する。
    """
    csv = tmp_path / 'emotion.csv'
    csv.write_text(
        'timestamp,date,emotions,note,score\n'
        '2026-08-25 22:02:09,2026-08-25,何も感じない,,\n'
        '2026-08-26 22:42:15,2026-08-26,落ち着いている,,3\n'
    )
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df = store.load_entries()

    assert df['score'].isna().tolist() == [True, False]
    assert df['score'].dropna().tolist() == [3]


def test_intraday_ignores_records_without_score():
    """score の無い記録から日内の差を作らないこと"""
    df = pd.DataFrame({
        'timestamp': pd.to_datetime(['2026-08-30 07:00', '2026-08-30 08:00']),
        'score': pd.array([pd.NA, 2], dtype='Int64'),
    })

    assert '2件以上' in render.render_intraday(df)


def test_unknown_label_is_neither_positive_nor_dropped():
    """旧語彙版で記録された語は現在の定義から引けない

    極性が引けない語を陽性に数えると回復の指標が水増しされ、
    表から落とすと記録そのものが消える。どちらもしない。
    """
    assert not render.has_positive('廃止された語', VMAP)
    assert render.has_positive('廃止された語;落ち着いている', VMAP)

    table = render.render_vocab(
        pd.DataFrame({'emotions': ['廃止された語;落ち着いている']}), VMAP)
    assert '廃止された語' in table
    assert render.VALENCE_UNKNOWN in table
