"""気分記録（Issue #87）のスコア列・語彙バージョン履歴・質問突き合わせのテスト

実機の Google Forms API は叩かず、変換ロジックだけを検証する。
"""

import argparse
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.clients import gforms_client
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
        'score': 'いまの気分', 'body': '身体の軽さ', 'head': '頭の軽さ',
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
                         'rowQuestion': {'title': '頭の軽さ'}},
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


# --- gforms_client.sync_questions ---

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
        gforms_client.scale_item('いまの気分', 1, 5, '悪い', '良い'),
        gforms_client.checkbox_item('いまの気持ち', ['a', 'b']),
        gforms_client.text_item('何があった？'),
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

    gforms_client.sync_questions(service, 'form1', items, existing_form=existing_form)

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
    items = [gforms_client.text_item('何があった？')]
    service = MagicMock()
    with pytest.raises(gforms_client.GoogleFormsError):
        gforms_client.sync_questions(service, 'form1', items, existing_form=existing_form)


def _existing_grid_form(row_ids):
    """行タイトルは実際のフォームの並びのまま（q_score/q_body/q_head の
    questionId を持つ3行）。row_ids は questionId のリスト（出現順）"""
    titles = ['いまの気分', '身体の軽さ', '頭の軽さ']
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
    gforms_client.sync_questions(service, 'form1', items, existing_form=existing_form)
    return captured['body']['requests']


def test_sync_questions_grid_row_order_change_is_detected():
    """グリッドの行順を変えると、過去の「いまの気分」の questionId が
    別の行（頭の軽さ）に付け替わることを検知する

    行の対応付けはタイトルでなく出現順（FIFO）。PHQ-9 の9問と同じ制約が
    グリッドの行にも効くことを固定するテスト（docs/forms.md 参照）。
    """
    existing_form = _existing_grid_form(['q_score', 'q_body', 'q_head'])
    # 行順を入れ替えた spec: 頭の軽さ / 身体の軽さ / いまの気分
    reordered = gforms_client.grid_item(
        'いまの状態', ['頭の軽さ', '身体の軽さ', 'いまの気分'], 1, 5, '悪い', '良い')

    requests = _run_sync([reordered], existing_form)
    updates = [r['updateItem'] for r in requests if 'updateItem' in r]
    assert len(updates) == 1
    questions = updates[0]['item']['questionGroupItem']['questions']

    # 出現順で対応付けているため、旧「いまの気分」(q_score) の questionId が
    # 新しい先頭行「頭の軽さ」に付け替わってしまう
    assert questions[0]['rowQuestion']['title'] == '頭の軽さ'
    assert questions[0]['questionId'] == 'q_score'
    # 逆に、末尾の「いまの気分」行は元の「頭の軽さ」の questionId を引き継ぐ
    assert questions[2]['rowQuestion']['title'] == 'いまの気分'
    assert questions[2]['questionId'] == 'q_head'


def test_sync_questions_grid_add_row_preserves_existing_row_ids():
    """行を追加しても既存3行の questionId は保持される

    将来 快・達成感 の行を足すコストがこれで決まる。既存行の questionId が
    保持されていれば yaml の grid_rows に行を足すだけで済む。
    """
    existing_form = _existing_grid_form(['q_score', 'q_body', 'q_head'])
    extended = gforms_client.grid_item(
        'いまの状態', ['いまの気分', '身体の軽さ', '頭の軽さ', '快'], 1, 5, '悪い', '良い')

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
    by_title = gforms_client.question_id_by_title(form)
    assert by_title['いまの気分'] == 'q_score'
    assert by_title['身体の軽さ'] == 'q_body'
    assert by_title['頭の軽さ'] == 'q_head'


# --- gforms_client.grid_item: 行ごとの required ---

def test_grid_item_required_per_row():
    """required にリストを渡すと行ごとに反映される（いまの気分だけ必須の運用）"""
    item = gforms_client.grid_item(
        'いまの状態', ['いまの気分', '身体の軽さ', '頭の軽さ'], 1, 5, '悪い', '良い',
        required=[True, False, False])
    questions = item['questionGroupItem']['questions']
    assert questions[0]['rowQuestion']['title'] == 'いまの気分'
    assert questions[0]['required'] is True
    assert questions[1]['rowQuestion']['title'] == '身体の軽さ'
    assert questions[1]['required'] is False
    assert questions[2]['rowQuestion']['title'] == '頭の軽さ'
    assert questions[2]['required'] is False


def test_grid_item_required_bool_broadcasts_to_all_rows():
    """required に bool を渡す従来どおりの呼び方は全行に同じ値が当たる"""
    item = gforms_client.grid_item(
        'いまの状態', ['a', 'b', 'c'], 1, 5, '悪い', '良い', required=False)
    questions = item['questionGroupItem']['questions']
    assert [q['required'] for q in questions] == [False, False, False]


def test_grid_item_required_list_length_mismatch_raises():
    with pytest.raises(ValueError):
        gforms_client.grid_item(
            'いまの状態', ['a', 'b', 'c'], 1, 5, '悪い', '良い',
            required=[True, False])


def test_build_items_required_matches_grid_required_config():
    """emotion.py の build_items が yaml の grid_required を行ごとに反映すること。
    いまの気分だけ required、身体の軽さ・頭の軽さは任意"""
    conf = {**CONF, 'grid_title': 'いまの状態',
            'grid_required': {'score': True, 'body': False, 'head': False}}
    items = emotion.build_items(conf)
    grid_spec = next(i for i in items if 'questionGroupItem' in i)
    questions = grid_spec['questionGroupItem']['questions']
    by_title = {q['rowQuestion']['title']: q['required'] for q in questions}
    assert by_title['いまの気分'] is True
    assert by_title['身体の軽さ'] is False
    assert by_title['頭の軽さ'] is False


def test_build_items_missing_grid_required_defaults_to_required():
    """grid_required が無い/一部欠けている行は既定で required（安全側）"""
    conf = {**CONF, 'grid_title': 'いまの状態'}
    items = emotion.build_items(conf)
    grid_spec = next(i for i in items if 'questionGroupItem' in i)
    questions = grid_spec['questionGroupItem']['questions']
    assert all(q['required'] is True for q in questions)


# --- sync_questions: scale -> grid の型移行（現在の本番フォームが起点） ---
# 本番フォームは scale/checkbox/text の3問で、グリッドはまだ無い。ここへ
# grid/checkbox/text の新 spec を当てると、旧 scaleQuestion がどの kind
# バケットにも一致せず leftover になる。無条件に削除すると「画面で手編集
# された想定外の質問」の検出ができなくなるため、allow_kind_replace を
# 明示したときだけ削除を許す opt-in にしてある。

def _existing_scale_form():
    """移行前の本番フォームと同じ形（scale / checkbox / text）"""
    return {
        'items': [
            {
                'itemId': 'i_scale',
                'title': 'いまの気分',
                'questionItem': {'question': {
                    'questionId': 'q_scale',
                    'scaleQuestion': {'low': 1, 'high': 5},
                }},
            },
            {
                'itemId': 'i_emotions',
                'title': 'いまの気持ち',
                'questionItem': {'question': {
                    'questionId': 'q_emotions',
                    'choiceQuestion': {
                        'type': 'CHECKBOX',
                        'options': [{'value': '落ち着いている'}],
                    },
                }},
            },
            {
                'itemId': 'i_note',
                'title': '何があった？',
                'questionItem': {'question': {
                    'questionId': 'q_note',
                    'textQuestion': {'paragraph': False},
                }},
            },
        ],
    }


def _migration_items():
    return [
        gforms_client.grid_item('いまの状態', ['いまの気分', '身体の軽さ', '頭の軽さ'],
                             1, 5, '悪い', '良い'),
        gforms_client.checkbox_item('いまの気持ち', ['落ち着いている'], required=True),
        gforms_client.text_item('何があった？'),
    ]


def test_sync_questions_scale_to_grid_migration_blocked_without_flag():
    """既定（allow_kind_replace を渡さない）では、型移行の起点になる
    scale + checkbox + text のフォームへ grid の新 spec を当てると
    GoogleFormsError で止まる。ガードが生きていることの固定"""
    existing_form = _existing_scale_form()
    service = MagicMock()
    with pytest.raises(gforms_client.GoogleFormsError) as exc_info:
        gforms_client.sync_questions(service, 'form1', _migration_items(),
                                  existing_form=existing_form)
    assert 'いまの気分' in str(exc_info.value)
    assert 'scaleQuestion' in str(exc_info.value)


def test_sync_questions_scale_to_grid_migration_with_flag_deletes_old_scale():
    """allow_kind_replace=True なら例外を出さず、旧 scaleQuestion の
    deleteItem が発行される。checkbox / text の questionId は保持される"""
    existing_form = _existing_scale_form()
    requests = _run_sync_with_flag(_migration_items(), existing_form,
                                   allow_kind_replace=True)

    deletes = [r['deleteItem'] for r in requests if 'deleteItem' in r]
    creates = [r['createItem'] for r in requests if 'createItem' in r]
    updates = [r['updateItem'] for r in requests if 'updateItem' in r]

    # deleteItem に itemId フィールドは無い（Google Forms API の実際の
    # エラー: "Unknown name 'itemId' at 'requests[0].delete_item'"）。
    # location.index で指定する。i_scale はフォームの item 配列上 index 0。
    assert deletes == [{'location': {'index': 0}}]
    assert len(creates) == 1
    assert 'questionGroupItem' in creates[0]['item']

    checkbox_update = next(u for u in updates
                           if 'choiceQuestion' in u['item']['questionItem']['question'])
    text_update = next(u for u in updates
                       if 'textQuestion' in u['item']['questionItem']['question'])
    assert checkbox_update['item']['questionItem']['question']['questionId'] == 'q_emotions'
    assert text_update['item']['questionItem']['question']['questionId'] == 'q_note'

    # delete が create/update より先に来ること（location.index は delete 後の
    # 状態を前提に計算しているため）
    delete_pos = requests.index({'deleteItem': deletes[0]})
    create_pos = requests.index({'createItem': creates[0]})
    assert delete_pos < create_pos


def _run_sync_with_flag(items, existing_form, allow_kind_replace=False):
    service = MagicMock()
    captured = {}

    def fake_batch_update(formId, body):
        captured['body'] = body
        m = MagicMock()
        m.execute.return_value = {}
        return m

    service.forms.return_value.batchUpdate.side_effect = fake_batch_update
    gforms_client.sync_questions(service, 'form1', items, existing_form=existing_form,
                              allow_kind_replace=allow_kind_replace)
    return captured['body']['requests']


def test_sync_questions_delete_requests_never_contain_item_id():
    """deleteItem リクエストはどれも itemId を持たない（location.index の
    みで指定する）ことの固定。#104 で本番 400 を起こした形の再発防止本丸"""
    existing_form = _existing_scale_form()
    requests = _run_sync_with_flag(_migration_items(), existing_form,
                                   allow_kind_replace=True)
    deletes = [r['deleteItem'] for r in requests if 'deleteItem' in r]
    assert deletes
    for delete in deletes:
        assert 'itemId' not in delete
        assert 'index' in delete['location']


def test_sync_questions_multiple_leftovers_delete_in_descending_index_order():
    """leftover が複数あるとき、deleteItem は index の降順で並ぶこと。

    batchUpdate は requests を逐次適用するため、ある item を index N で
    消すと後続 item の index が 1 つずつ詰まる。昇順で削除すると2件目以降の
    index がずれて意図しない item を消してしまうため、降順必須。
    """
    existing_form = {
        'items': [
            {
                'itemId': 'i_scale',
                'title': 'いまの気分',
                'questionItem': {'question': {
                    'questionId': 'q_scale',
                    'scaleQuestion': {'low': 1, 'high': 5},
                }},
            },
            {
                'itemId': 'i_date',
                'title': '謎の日付質問',
                'questionItem': {'question': {
                    'questionId': 'q_date',
                    'dateQuestion': {},
                }},
            },
            {
                'itemId': 'i_note',
                'title': '何があった？',
                'questionItem': {'question': {
                    'questionId': 'q_note',
                    'textQuestion': {'paragraph': False},
                }},
            },
        ],
    }
    items = [gforms_client.text_item('何があった？')]
    requests = _run_sync_with_flag(items, existing_form, allow_kind_replace=True)
    deletes = [r['deleteItem'] for r in requests if 'deleteItem' in r]
    indices = [d['location']['index'] for d in deletes]
    assert indices == sorted(indices, reverse=True)
    assert set(indices) == {0, 1}


def test_sync_questions_scale_to_grid_migration_full_request_sequence():
    """3問（scale/checkbox/text）→ grid/checkbox/text 移行で生成される
    リクエスト列（種類と index）が期待どおりであることの固定。

    手検証:
      既存: [scale(idx0), checkbox(idx1), text(idx2)]
      leftover は scale(idx0) のみ → delete index=0
      適用後の残り: [checkbox(0), text(1)]
      create（grid）は final_index=0 → [grid(0), checkbox(1), text(2)]
      update（checkbox）final_index=1、update（text）final_index=2
      → 最終順序 [grid(0), checkbox(1), text(2)] は期待どおり
    """
    existing_form = _existing_scale_form()
    requests = _run_sync_with_flag(_migration_items(), existing_form,
                                   allow_kind_replace=True)

    assert requests[0] == {'deleteItem': {'location': {'index': 0}}}

    create = requests[1]['createItem']
    assert 'questionGroupItem' in create['item']
    assert create['location']['index'] == 0

    checkbox_update = next(r['updateItem'] for r in requests
                           if 'updateItem' in r
                           and 'choiceQuestion' in r['updateItem']['item']['questionItem']['question'])
    assert checkbox_update['location']['index'] == 1

    text_update = next(r['updateItem'] for r in requests
                       if 'updateItem' in r
                       and 'textQuestion' in r['updateItem']['item']['questionItem']['question'])
    assert text_update['location']['index'] == 2


def test_preview_kind_mismatch_lists_leftover_before_sync():
    """setup-form --allow-kind-replace が実行前に削除対象を列挙できるよう、
    leftover の事前確認ができること"""
    existing_form = _existing_scale_form()
    leftover = gforms_client.preview_kind_mismatch(_migration_items(), existing_form)
    assert [i['title'] for i in leftover] == ['いまの気分']


def test_sync_questions_raises_on_unmatched_existing_item_default_flag():
    """既存の不一致検出テストが、allow_kind_replace を渡さない既定の
    呼び方のままで通ること（フラグ追加による後退が無いことの確認）"""
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
    items = [gforms_client.text_item('何があった？')]
    service = MagicMock()
    with pytest.raises(gforms_client.GoogleFormsError):
        gforms_client.sync_questions(service, 'form1', items, existing_form=existing_form)


# --- has_unfetched_responses / cmd_setup_form の削除前ガード -------------
# 実際に1件失いかけたインシデントの再発防止: 日次 fetch の後に投稿された
# 回答が CSV に materialize されないまま --allow-kind-replace を実行すると、
# 削除で questionId の対応付けが失われ、その回答の値が読めなくなる。

def test_has_unfetched_responses_true_when_response_newer_than_csv():
    csv_max = pd.Timestamp('2026-08-31 15:01:00')
    responses = [{'lastSubmittedTime': '2026-08-31T06:05:00Z'}]  # JST 15:05
    assert emotion.has_unfetched_responses(responses, csv_max) is True


def test_has_unfetched_responses_false_when_no_response_newer_than_csv():
    csv_max = pd.Timestamp('2026-08-31 15:01:00')
    responses = [{'lastSubmittedTime': '2026-08-31T05:00:00Z'}]  # JST 14:00
    assert emotion.has_unfetched_responses(responses, csv_max) is False


def test_has_unfetched_responses_false_when_no_responses_at_all():
    assert emotion.has_unfetched_responses([], pd.Timestamp('2026-08-31 15:01:00')) is False


def test_has_unfetched_responses_true_when_csv_missing_but_responses_exist():
    """CSV がまだ無い（＝全件未取り込み）のに回答があるなら未取り込み扱い"""
    responses = [{'lastSubmittedTime': '2026-08-31T06:05:00Z'}]
    assert emotion.has_unfetched_responses(responses, None) is True


def _setup_form_conf(tmp_path):
    return {**CONF, 'form_id': 'form1', 'grid_title': 'いまの状態'}


def test_setup_form_aborts_and_skips_delete_when_unfetched_response_exists(
        tmp_path, monkeypatch):
    """CSV 未取り込みの回答がある状態では、deleteItem を含む sync_questions を
    一切呼ばず中止すること（本文の 15:05 投稿インシデントの再現）"""
    csv = tmp_path / 'emotion.csv'
    csv.write_text(
        'timestamp,date,emotions,note,score,body,head\n'
        '2026-08-31 15:01:00,2026-08-31,,,3,,\n'
    )
    monkeypatch.setattr(emotion, 'OUT_FILE', csv)
    monkeypatch.setattr(emotion, 'load_def', lambda: _setup_form_conf(tmp_path))

    existing_form = _existing_scale_form()
    service = MagicMock()
    monkeypatch.setattr(gforms_client, 'create_service', lambda: service)
    monkeypatch.setattr(gforms_client, 'get_form', lambda svc, fid: existing_form)
    monkeypatch.setattr(
        gforms_client, 'list_responses',
        lambda svc, fid: [{'lastSubmittedTime': '2026-08-31T06:05:00Z'}])  # 15:05 JST

    sync_called = MagicMock()
    monkeypatch.setattr(gforms_client, 'sync_questions', sync_called)

    args = argparse.Namespace(update=True, allow_kind_replace=True)
    with pytest.raises(SystemExit):
        emotion.cmd_setup_form(args)

    sync_called.assert_not_called()


def test_setup_form_proceeds_when_no_unfetched_response(tmp_path, monkeypatch):
    """CSV が最新回答まで取り込み済みなら、従来どおり sync_questions
    （delete 込み）まで進むこと"""
    csv = tmp_path / 'emotion.csv'
    csv.write_text(
        'timestamp,date,emotions,note,score,body,head\n'
        '2026-08-31 15:05:00,2026-08-31,,,3,,\n'
    )
    monkeypatch.setattr(emotion, 'OUT_FILE', csv)
    monkeypatch.setattr(emotion, 'load_def', lambda: _setup_form_conf(tmp_path))

    existing_form = {**_existing_scale_form(), 'formId': 'form1',
                     'responderUri': 'https://example.invalid/viewform'}
    service = MagicMock()
    monkeypatch.setattr(gforms_client, 'create_service', lambda: service)
    monkeypatch.setattr(gforms_client, 'get_form', lambda svc, fid: existing_form)
    monkeypatch.setattr(
        gforms_client, 'list_responses',
        lambda svc, fid: [{'lastSubmittedTime': '2026-08-31T06:05:00Z'}])  # 15:05 JST

    sync_called = MagicMock(return_value={'replies': []})
    monkeypatch.setattr(gforms_client, 'sync_questions', sync_called)

    args = argparse.Namespace(update=True, allow_kind_replace=True)
    emotion.cmd_setup_form(args)

    sync_called.assert_called_once()


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
