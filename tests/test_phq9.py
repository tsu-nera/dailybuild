"""PHQ-9（Issue #100）のスコア列・合計算出・同型9問の突き合わせのテスト

実機の Google Forms API は叩かず、変換ロジックだけを検証する。
設問文・選択肢のラベルは著作権の都合でこのリポジトリに書けないため、
テストではダミーの文言（"設問1" "選択肢A" 等）を使う。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.clients import gforms_api


def _load_script():
    """scripts/ 配下はパッケージではないのでファイルから直接ロードする"""
    path = BASE_DIR / 'scripts' / 'phq9.py'
    spec = importlib.util.spec_from_file_location('phq9', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['phq9'] = module
    spec.loader.exec_module(module)
    return module


phq9 = _load_script()


QUESTION_TITLES = {f'q{i}': f'設問{i}' for i in range(1, 10)}

CONF = {
    'questions': QUESTION_TITLES,
    'choices': [
        {'label': '選択肢A', 'score': 0},
        {'label': '選択肢B', 'score': 1},
        {'label': '選択肢C', 'score': 2},
        {'label': '選択肢D', 'score': 3},
    ],
    'impairment': {
        'enabled': True,
        'question': '機能障害の設問',
        'choices': ['困難度A', '困難度B', '困難度C', '困難度D'],
    },
}

CONF_NO_IMPAIRMENT = {
    **CONF,
    'impairment': {'enabled': False},
}


def _form(conf=CONF):
    items = []
    for key in phq9.QUESTION_KEYS:
        items.append({
            'title': conf['questions'][key],
            'questionItem': {'question': {
                'questionId': f'qid_{key}',
                'choiceQuestion': {
                    'type': 'RADIO',
                    'options': [{'value': c['label']} for c in conf['choices']],
                },
            }},
        })
    if conf.get('impairment', {}).get('enabled', True):
        items.append({
            'title': conf['impairment']['question'],
            'questionItem': {'question': {
                'questionId': 'qid_impairment',
                'choiceQuestion': {
                    'type': 'RADIO',
                    'options': [{'value': c} for c in conf['impairment']['choices']],
                },
            }},
        })
    return {'items': items}


def _response(timestamp, answers_by_key=None, impairment=None):
    answers = {}
    answers_by_key = answers_by_key or {}
    for key, label in answers_by_key.items():
        answers[f'qid_{key}'] = {'textAnswers': {'answers': [{'value': label}]}}
    if impairment is not None:
        answers['qid_impairment'] = {'textAnswers': {'answers': [{'value': impairment}]}}
    return {'lastSubmittedTime': timestamp, 'answers': answers}


ALL_LOW = {k: '選択肢A' for k in phq9.QUESTION_KEYS}


# --- build_dataframe: total ---

def test_build_dataframe_total_when_all_answered():
    answers = dict(ALL_LOW)
    answers['q1'] = '選択肢B'  # 1点
    answers['q9'] = '選択肢D'  # 3点
    responses = [_response('2026-08-20T10:00:00Z', answers, impairment='困難度B')]
    df = phq9.build_dataframe(_form(), responses, CONF)
    # 1 + 3 + 残り7問 * 0 = 4
    assert df['total'].iloc[0] == 4


def test_build_dataframe_total_is_nan_when_one_missing():
    answers = dict(ALL_LOW)
    del answers['q5']  # 1問未回答
    responses = [_response('2026-08-20T10:00:00Z', answers)]
    df = phq9.build_dataframe(_form(), responses, CONF)
    assert pd.isna(df['total'].iloc[0])
    assert pd.isna(df['q5'].iloc[0])
    # 未回答を0として合算していないことの確認（他は0点で埋まっている）
    assert df['q1'].iloc[0] == 0


def test_build_dataframe_total_not_zero_padded_for_missing():
    """未回答が1つでもあれば合計はNaN。0として足されていないことを別角度からも確認"""
    responses = [_response('2026-08-20T10:00:00Z', {})]  # 全問未回答
    df = phq9.build_dataframe(_form(), responses, CONF)
    assert pd.isna(df['total'].iloc[0])


def test_build_dataframe_score_range():
    answers = {k: '選択肢D' for k in phq9.QUESTION_KEYS}
    responses = [_response('2026-08-20T10:00:00Z', answers)]
    df = phq9.build_dataframe(_form(), responses, CONF)
    assert df['total'].iloc[0] == 27  # 9問 * 3点満点

    responses_min = [_response('2026-08-20T10:00:00Z', dict(ALL_LOW))]
    df_min = phq9.build_dataframe(_form(), responses_min, CONF)
    assert df_min['total'].iloc[0] == 0


def test_build_dataframe_column_order_with_impairment():
    df = phq9.build_dataframe(_form(), [], CONF)
    assert list(df.columns) == ['timestamp', 'date'] + phq9.QUESTION_KEYS + ['total', 'impairment']


def test_build_dataframe_column_order_without_impairment():
    df = phq9.build_dataframe(_form(CONF_NO_IMPAIRMENT), [], CONF_NO_IMPAIRMENT)
    assert list(df.columns) == ['timestamp', 'date'] + phq9.QUESTION_KEYS + ['total']


def test_build_dataframe_empty_ok():
    """回答0件は週1回の質問紙として正常。エラーにしない"""
    df = phq9.build_dataframe(_form(), [], CONF)
    assert df.empty
    assert 'total' in df.columns


def test_build_dataframe_impairment_not_in_total():
    answers = dict(ALL_LOW)
    responses = [_response('2026-08-20T10:00:00Z', answers, impairment='困難度C')]
    df = phq9.build_dataframe(_form(), responses, CONF)
    assert df['total'].iloc[0] == 0
    assert df['impairment'].iloc[0] == '困難度C'


def test_build_dataframe_missing_impairment_answer_is_na():
    answers = dict(ALL_LOW)
    responses = [_response('2026-08-20T10:00:00Z', answers)]  # impairment未回答
    df = phq9.build_dataframe(_form(), responses, CONF)
    assert pd.isna(df['impairment'].iloc[0])
    # 機能障害の設問は採点対象外。未回答でも total は算出される
    assert df['total'].iloc[0] == 0


def test_build_dataframe_raises_on_missing_question_in_form():
    broken_form = _form()
    broken_form['items'] = broken_form['items'][:-1]  # impairment 設問を欠落させる
    with pytest.raises(ValueError):
        phq9.build_dataframe(broken_form, [], CONF)


# --- gforms_api.sync_questions: 同型9問が出現順で対応付けられること ---

def test_sync_questions_matches_nine_radio_questions_by_order():
    """PHQ-9 は9問すべて同型（ラジオ）。sync_questions はタイトルを見ず
    出現順（FIFO）で対応付けるため、この挙動をテストで固定する。
    yaml の質問順を変えると questionId が別の設問に引き継がれ、過去の
    回答が別の質問の回答として読めてしまう（CLAUDE.md 参照）。
    """
    existing_items = []
    for i in range(1, 10):
        existing_items.append({
            'itemId': f'old_i{i}',
            'title': f'旧設問{i}',
            'questionItem': {'question': {
                'questionId': f'old_q{i}',
                'choiceQuestion': {'type': 'RADIO', 'options': [{'value': 'x'}]},
            }},
        })
    existing_form = {'items': existing_items}

    choices = ['選択肢A', '選択肢B', '選択肢C', '選択肢D']
    items = [gforms_api.radio_item(f'新設問{i}', choices) for i in range(1, 10)]

    from unittest.mock import MagicMock
    service = MagicMock()
    captured = {}

    def fake_batch_update(formId, body):
        captured['body'] = body
        m = MagicMock()
        m.execute.return_value = {}
        return m

    service.forms.return_value.batchUpdate.side_effect = fake_batch_update

    gforms_api.sync_questions(service, 'form1', items, existing_form=existing_form)

    updates = [r['updateItem'] for r in captured['body']['requests'] if 'updateItem' in r]
    assert len(updates) == 9
    # i番目の新設問が i番目の旧設問の questionId・index を引き継ぐこと（出現順）
    for i, update in enumerate(updates):
        assert update['item']['title'] == f'新設問{i + 1}'
        assert update['item']['questionItem']['question']['questionId'] == f'old_q{i + 1}'
        assert update['location']['index'] == i


def test_build_items_uses_radio_and_preserves_order():
    items = phq9.build_items(CONF)
    assert len(items) == 10  # 9問 + 機能障害
    for item in items[:9]:
        assert item['questionItem']['question']['choiceQuestion']['type'] == 'RADIO'
    titles = [item['title'] for item in items[:9]]
    assert titles == [CONF['questions'][k] for k in phq9.QUESTION_KEYS]


def test_build_items_without_impairment():
    items = phq9.build_items(CONF_NO_IMPAIRMENT)
    assert len(items) == 9


# --- load_def: yaml 未設置時の親切なメッセージ ---

def test_load_def_missing_file_raises_with_helpful_message(tmp_path, monkeypatch):
    missing = tmp_path / 'phq9_def.yaml'
    monkeypatch.setattr(phq9, 'DEF_FILE', missing)
    with pytest.raises(FileNotFoundError, match='phq9_def.yaml.sample'):
        phq9.load_def()
