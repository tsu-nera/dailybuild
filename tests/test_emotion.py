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
    'questions': {'score': 'いまの気分', 'emotions': 'いまの気持ち', 'note': '何があった？'},
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
                'title': 'いまの気分',
                'questionItem': {'question': {
                    'questionId': 'q_score',
                    'scaleQuestion': {'low': 1, 'high': 5},
                }},
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


def _response(timestamp, score=None, emotions=None, note=None):
    answers = {}
    if score is not None:
        answers['q_score'] = {'textAnswers': {'answers': [{'value': score}]}}
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
    assert list(df.columns) == ['timestamp', 'date', 'score', 'emotions', 'note']


def test_build_dataframe_empty_has_score_column():
    df = emotion.build_dataframe(_form(), [], CONF)
    assert df.empty
    assert 'score' in df.columns


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
