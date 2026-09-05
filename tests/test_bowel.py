"""排便記録（Issue #109）のパース・マージのテスト

実機の Google Forms API は叩かず、変換ロジックだけを検証する。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.bowel import store
from lib.utils import csv_utils
from lib.utils.private_data import require_private_path


def _load_script():
    """scripts/ 配下はパッケージではないのでファイルから直接ロードする"""
    path = BASE_DIR / 'scripts' / 'bowel.py'
    spec = importlib.util.spec_from_file_location('bowel', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['bowel'] = module
    spec.loader.exec_module(module)
    return module


bowel = _load_script()


CONF = {
    'questions': {'bristol': '便の形（ブリストル）'},
    'choices': [
        {'code': 1, 'label': 'コロコロ（硬い塊）'},
        {'code': 2, 'label': 'ゴツゴツ（塊が集まった硬便）'},
        {'code': 3, 'label': 'ひび割れのあるソーセージ状'},
        {'code': 4, 'label': 'なめらかなソーセージ状'},
        {'code': 5, 'label': 'やわらかい小さな塊'},
        {'code': 6, 'label': '泥状'},
        {'code': 7, 'label': '水様'},
    ],
}


def _form():
    return {
        'items': [
            {
                'title': '便の形（ブリストル）',
                'questionItem': {'question': {
                    'questionId': 'q_bristol',
                    'choiceQuestion': {
                        'type': 'RADIO',
                        'options': [{'value': f"{c['code']} {c['label']}"}
                                   for c in CONF['choices']],
                    },
                }},
            },
        ],
    }


def _response(timestamp, bristol=None):
    answers = {}
    if bristol is not None:
        answers['q_bristol'] = {'textAnswers': {'answers': [{'value': bristol}]}}
    return {'lastSubmittedTime': timestamp, 'answers': answers}


# --- parse_bristol_value ---

def test_parse_bristol_value_extracts_leading_number():
    assert bowel.parse_bristol_value('3 ひび割れのあるソーセージ状') == 3


def test_parse_bristol_value_none_is_na():
    assert pd.isna(bowel.parse_bristol_value(None))


def test_parse_bristol_value_unparseable_is_na_not_zero():
    """未回答・パース不能を 0 に潰さない（欠測を捏造しない）"""
    assert pd.isna(bowel.parse_bristol_value('よくわからない'))
    assert pd.isna(bowel.parse_bristol_value(''))


# --- build_dataframe ---

def test_build_dataframe_bristol_is_nullable_int():
    responses = [
        _response('2026-08-20T10:00:00Z', bristol='4 なめらかなソーセージ状'),
        _response('2026-08-21T10:00:00Z'),
    ]
    df = bowel.build_dataframe(_form(), responses, CONF)
    assert str(df['bristol'].dtype) == 'Int64'
    assert df['bristol'].iloc[0] == 4
    assert pd.isna(df['bristol'].iloc[1])


def test_build_dataframe_column_order():
    df = bowel.build_dataframe(_form(), [], CONF)
    assert list(df.columns) == ['timestamp', 'date', 'bristol']


def test_build_dataframe_empty_has_bristol_column():
    df = bowel.build_dataframe(_form(), [], CONF)
    assert df.empty
    assert 'bristol' in df.columns


# --- 冪等性（同じ回答を2回 fetch 相当のマージにかけても行が増えない） ---

def test_fetch_merge_is_idempotent(tmp_path):
    out_file = tmp_path / 'bowel.csv'
    responses = [
        _response('2026-08-20T10:00:00Z', bristol='4 なめらかなソーセージ状'),
        _response('2026-08-21T10:00:00Z', bristol='6 泥状'),
    ]
    form = _form()

    df1 = bowel.build_dataframe(form, responses, CONF)
    merged1 = csv_utils.merge_csv_by_columns(
        df1, out_file, key_columns=['timestamp'], parse_dates=['timestamp'],
        sort_by=['timestamp'], preserve_existing_on_nan=True)
    merged1.to_csv(out_file, index=False)
    assert len(merged1) == 2

    # 同じ回答をもう一度取得しても行数が増えない
    df2 = bowel.build_dataframe(form, responses, CONF)
    merged2 = csv_utils.merge_csv_by_columns(
        df2, out_file, key_columns=['timestamp'], parse_dates=['timestamp'],
        sort_by=['timestamp'], preserve_existing_on_nan=True)
    merged2.to_csv(out_file, index=False)
    assert len(merged2) == 2


# --- store.load_entries ---

def test_load_entries_keeps_missing_bristol_as_na(tmp_path, monkeypatch):
    csv = tmp_path / 'bowel.csv'
    csv.write_text(
        'timestamp,date,bristol\n'
        '2026-08-25 22:02:09,2026-08-25,\n'
        '2026-08-26 07:42:15,2026-08-26,4\n'
    )
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df = store.load_entries()

    assert str(df['bristol'].dtype) == 'Int64'
    assert df['bristol'].isna().tolist() == [True, False]
    assert df['bristol'].dropna().tolist() == [4]


def test_load_entries_on_header_only_csv(tmp_path, monkeypatch):
    """回答0件（ヘッダのみ）の CSV でも落ちない

    setup-form 直後〜初回回答前がこの状態になる。parse_dates で読むと
    空の timestamp 列が object のまま残り、.dt が AttributeError で
    落ちて show が使えなくなる（実機で踏んだ）。
    """
    csv = tmp_path / 'bowel.csv'
    csv.write_text('timestamp,date,bristol\n')
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df = store.load_entries()

    assert df.empty
    assert str(df['timestamp'].dtype).startswith('datetime64')
    assert str(df['bristol'].dtype) == 'Int64'
    # show の被覆表示が nunique を呼ぶので date 列も引けている必要がある
    assert df['date'].nunique() == 0


# --- data/bowel.csv が private symlink 配下であることの検証 ---

def test_csv_file_resolves_to_private_repo():
    """store.CSV_FILE は require_private_path 済みなので既に検証されている。

    symlink 未設定の環境で public 側の別パスを渡すと落ちることも確認する
    （private_data.py のガードが bowel.py 側でも効くことの固定）。
    """
    require_private_path(store.CSV_FILE)

    with pytest.raises(FileNotFoundError):
        require_private_path(BASE_DIR / 'bowel_outside_private.csv')
