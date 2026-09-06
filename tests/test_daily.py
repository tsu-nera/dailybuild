"""日次記録・朝夜分割（Issue #157）のパース・マージ・移行・境界のテスト

実機の Google Forms API は叩かず、変換ロジックだけを検証する。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.daily import store
from lib.utils import csv_utils


def _load_script():
    """scripts/ 配下はパッケージではないのでファイルから直接ロードする"""
    path = BASE_DIR / 'scripts' / 'daily.py'
    spec = importlib.util.spec_from_file_location('daily', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['daily'] = module
    spec.loader.exec_module(module)
    return module


daily = _load_script()


MORNING_CONF = {
    'questions': {
        'mind': '気分', 'body': '身体の軽さ', 'head': '頭の軽さ',
        'sleep': '昨夜の眠り', 'comment': 'コメント',
    },
    'grid_rows': ['mind', 'body', 'head', 'sleep'],
    'grid_required': {'mind': True, 'body': False, 'head': False, 'sleep': False},
    'score': {'low': 1, 'high': 5, 'low_label': '悪い', 'high_label': '良い'},
}

EVENING_CONF = {
    'questions': {
        'mind': '気分', 'body': '身体の軽さ', 'head': '頭の軽さ',
        'satisfaction': '満足感', 'achievement': '達成感', 'comment': 'コメント',
    },
    'grid_rows': ['mind', 'body', 'head', 'satisfaction', 'achievement'],
    'grid_required': {'mind': True, 'body': False, 'head': False,
                      'satisfaction': False, 'achievement': False},
    'score': {'low': 1, 'high': 5, 'low_label': '悪い', 'high_label': '良い'},
}


def _grid_form(rows_titles):
    return {
        'items': [
            {
                'title': '今日はどうだった？',
                'questionGroupItem': {
                    'questions': [
                        {'questionId': f'q_{i}', 'required': i == 0,
                         'rowQuestion': {'title': t}}
                        for i, t in enumerate(rows_titles)
                    ],
                    'grid': {'columns': {
                        'type': 'RADIO',
                        'options': [{'value': str(n)} for n in range(1, 6)],
                    }},
                },
            },
            {
                'title': 'コメント',
                'questionItem': {'question': {
                    'questionId': 'q_comment',
                    'textQuestion': {'paragraph': False},
                }},
            },
        ],
    }


def _morning_form():
    return _grid_form(['気分', '身体の軽さ', '頭の軽さ', '昨夜の眠り'])


def _evening_form():
    return _grid_form(['気分', '身体の軽さ', '頭の軽さ', '満足感', '達成感'])


def _response(timestamp, comment=None, **answers_by_label):
    label_to_qid = {
        '気分': 'q_0', '身体の軽さ': 'q_1', '頭の軽さ': 'q_2',
        '昨夜の眠り': 'q_3',
    }
    # evening 用の追加ラベル（グリッドの並び順は _evening_form と一致させる）
    label_to_qid_evening = {
        '気分': 'q_0', '身体の軽さ': 'q_1', '頭の軽さ': 'q_2',
        '満足感': 'q_3', '達成感': 'q_4',
    }
    answers = {}
    key_map = {
        'mind': '気分', 'body': '身体の軽さ', 'head': '頭の軽さ',
        'sleep': '昨夜の眠り', 'satisfaction': '満足感', 'achievement': '達成感',
    }
    for key, value in answers_by_label.items():
        label = key_map[key]
        qid = label_to_qid.get(label) or label_to_qid_evening.get(label)
        answers[qid] = {'textAnswers': {'answers': [{'value': str(value)}]}}
    if comment is not None:
        answers['q_comment'] = {'textAnswers': {'answers': [{'value': comment}]}}
    return {'lastSubmittedTime': timestamp, 'answers': answers}


# --- response_date（5:00境界・暦日の純関数、単体テスト） ---

def test_response_date_evening_boundary():
    assert store.response_date(pd.Timestamp('2026-09-01 03:30:00'), 5) \
        == pd.Timestamp('2026-08-31').date()
    assert store.response_date(pd.Timestamp('2026-09-01 05:30:00'), 5) \
        == pd.Timestamp('2026-09-01').date()
    assert store.response_date(pd.Timestamp('2026-09-01 04:59:00'), 5) \
        == pd.Timestamp('2026-08-31').date()
    assert store.response_date(pd.Timestamp('2026-09-01 05:00:00'), 5) \
        == pd.Timestamp('2026-09-01').date()


def test_response_date_morning_is_calendar_day_no_shift():
    """朝(day_start_hour=0)は04時台でも当日のまま。前日へずれない（AC の回帰ガード）"""
    assert store.response_date(pd.Timestamp('2026-09-01 04:30:00'), 0) \
        == pd.Timestamp('2026-09-01').date()


# --- build_dataframe: 朝(4行) ---

def test_build_dataframe_morning_collapses_same_date_to_last_response():
    responses = [
        _response('2026-09-01T01:00:00Z', mind=2, comment='朝の分'),
        _response('2026-09-01T10:00:00Z', mind=4, comment='夜の分'),
    ]
    df = daily.build_dataframe(_morning_form(), responses, MORNING_CONF, 'morning')

    assert len(df) == 1
    assert df.iloc[0]['mind_score'] == 4
    assert df.iloc[0]['comment'] == '夜の分'


def test_build_dataframe_morning_column_order():
    df = daily.build_dataframe(_morning_form(), [], MORNING_CONF, 'morning')
    assert list(df.columns) == store.SLOTS['morning']['columns']


def test_build_dataframe_morning_assigns_four_grid_rows_without_reordering():
    responses = [_response('2026-09-01T10:00:00Z',
                           mind=1, body=2, head=3, sleep=4)]
    df = daily.build_dataframe(_morning_form(), responses, MORNING_CONF, 'morning')

    row = df.iloc[0]
    assert row['mind_score'] == 1
    assert row['body_score'] == 2
    assert row['head_score'] == 3
    assert row['sleep_score'] == 4
    assert row['source'] == 'form'


def test_build_dataframe_morning_date_matches_response_calendar_date():
    """朝の date は暦日のまま（起床直後の回答でも1日ずれない）"""
    responses = [_response('2026-08-31T22:00:00Z', mind=3, sleep=4)]  # JST 07:00
    df = daily.build_dataframe(_morning_form(), responses, MORNING_CONF, 'morning')

    assert str(df.iloc[0]['date']) == '2026-09-01'


# --- build_dataframe: 夜(5行・5:00境界) ---

def test_build_dataframe_evening_assigns_five_grid_rows_without_reordering():
    responses = [_response('2026-09-01T10:00:00Z',
                           mind=1, body=2, head=3, satisfaction=4, achievement=5)]
    df = daily.build_dataframe(_evening_form(), responses, EVENING_CONF, 'evening')

    row = df.iloc[0]
    assert row['mind_score'] == 1
    assert row['body_score'] == 2
    assert row['head_score'] == 3
    assert row['satisfaction'] == 4
    assert row['achievement'] == 5
    assert 'source' not in df.columns


def test_build_dataframe_evening_column_order():
    df = daily.build_dataframe(_evening_form(), [], EVENING_CONF, 'evening')
    assert list(df.columns) == store.SLOTS['evening']['columns']
    assert 'source' not in df.columns


def test_build_dataframe_evening_date_uses_5am_boundary():
    # JST 03:30 = UTC 前日 18:30
    responses = [_response('2026-08-31T18:30:00Z', mind=3)]
    df = daily.build_dataframe(_evening_form(), responses, EVENING_CONF, 'evening')

    assert str(df.iloc[0]['date']) == '2026-08-31'


# --- fetch のマージは行ごと置換（両 slot で確認） ---

def test_fetch_merge_replaces_whole_row_for_evening(tmp_path):
    out_file = tmp_path / 'daily_evening.csv'

    df1 = daily.build_dataframe(
        _evening_form(),
        [_response('2026-09-01T13:00:00Z', mind=2, comment='最初のコメント')],
        EVENING_CONF, 'evening')
    merged1 = csv_utils.merge_csv_by_columns(
        df1, out_file, key_columns=['date'], parse_dates=['date'], sort_by=['date'])
    merged1.to_csv(out_file, index=False)
    assert merged1.iloc[0]['comment'] == '最初のコメント'

    # 同じ date（JST, 5:00境界後）にコメント無しで再送信
    df2 = daily.build_dataframe(
        _evening_form(),
        [_response('2026-09-01T14:00:00Z', mind=3)],
        EVENING_CONF, 'evening')
    merged2 = csv_utils.merge_csv_by_columns(
        df2, out_file, key_columns=['date'], parse_dates=['date'], sort_by=['date'])

    assert len(merged2) == 1
    assert merged2.iloc[0]['mind_score'] == 3
    assert pd.isna(merged2.iloc[0]['comment'])


def test_fetch_merge_is_idempotent_for_evening(tmp_path):
    """同じ回答を2回 fetch しても行が増えない"""
    out_file = tmp_path / 'daily_evening.csv'
    responses = [_response('2026-09-01T13:00:00Z', mind=2, comment='メモ')]

    for _ in range(2):
        df = daily.build_dataframe(_evening_form(), responses, EVENING_CONF, 'evening')
        merged = csv_utils.merge_csv_by_columns(
            df, out_file, key_columns=['date'], parse_dates=['date'], sort_by=['date'])
        merged.to_csv(out_file, index=False)

    result = pd.read_csv(out_file)
    assert len(result) == 1


# --- 朝夜は別ファイル: 片方の fetch がもう片方に影響しない ---

def test_morning_and_evening_fetch_do_not_affect_each_other(tmp_path, monkeypatch):
    morning_file = tmp_path / 'daily_morning.csv'
    evening_file = tmp_path / 'daily_evening.csv'
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', morning_file)
    monkeypatch.setitem(store.SLOTS['evening'], 'csv_file', evening_file)
    monkeypatch.setitem(store.SLOTS['morning'], 'grid_history_file',
                        tmp_path / 'daily_morning_grid_history.csv')
    monkeypatch.setitem(store.SLOTS['evening'], 'grid_history_file',
                        tmp_path / 'daily_evening_grid_history.csv')

    def fake_load_def(slot):
        return {'morning': {**MORNING_CONF, 'form_id': 'FORM_M'},
               'evening': {**EVENING_CONF, 'form_id': 'FORM_E'}}[slot]

    class FakeService:
        def forms(self):
            return self

        def get(self, formId):
            self._last = ('get_form', formId)
            return self

        def responses(self):
            return self

        def list(self, formId, pageToken=None):
            self._last = ('list_responses', formId)
            return self

        def execute(self):
            action, form_id = self._last
            if action == 'get_form':
                return {'FORM_M': _morning_form(), 'FORM_E': _evening_form()}[form_id]
            responses_by_form = {
                'FORM_M': [_response('2026-09-01T22:00:00Z', mind=4)],
                'FORM_E': [_response('2026-09-01T13:00:00Z', mind=2)],
            }
            return {'responses': responses_by_form.get(form_id, [])}

    monkeypatch.setattr(daily, 'load_def', fake_load_def)
    monkeypatch.setattr(daily.gforms_client, 'create_service', lambda interactive=True: FakeService())

    args_m = _ns(slot='morning', non_interactive=True)
    daily.cmd_fetch(args_m)
    morning_before = pd.read_csv(morning_file)
    assert len(morning_before) == 1

    args_e = _ns(slot='evening', non_interactive=True)
    daily.cmd_fetch(args_e)

    morning_after = pd.read_csv(morning_file)
    evening_after = pd.read_csv(evening_file)
    # 朝ファイルは夜の fetch で変化しない（別ファイルなので構造的に保証される）
    pd.testing.assert_frame_equal(morning_before, morning_after)
    assert len(evening_after) == 1


def _ns(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


# --- migrate-manual（morning 限定。既存の冪等性テストを引き継ぐ） ---

def _write_manual_csv(path, rows):
    df = pd.DataFrame(rows, columns=[
        'date', 'mind_score', 'body_score', 'sleep_score', 'comment'])
    df.to_csv(path, index=False)
    return path


def test_migrate_manual_skips_rows_with_all_four_missing(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': None, 'body_score': None,
         'sleep_score': None, 'comment': None},
        {'date': '2026-08-02', 'mind_score': 3, 'body_score': None,
         'sleep_score': None, 'comment': None},
    ])
    out_csv = tmp_path / 'daily_morning.csv'
    monkeypatch.setattr(daily, 'MANUAL_FILE', manual_csv)
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', out_csv)

    daily.cmd_migrate_manual(_ns(dry_run=False))

    result = pd.read_csv(out_csv)
    assert result['date'].astype(str).tolist() == ['2026-08-02']


def test_migrate_manual_does_not_fabricate_missing_dates(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': None,
         'sleep_score': None, 'comment': None},
        {'date': '2026-08-05', 'mind_score': 2, 'body_score': None,
         'sleep_score': None, 'comment': None},
    ])
    out_csv = tmp_path / 'daily_morning.csv'
    monkeypatch.setattr(daily, 'MANUAL_FILE', manual_csv)
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', out_csv)

    daily.cmd_migrate_manual(_ns(dry_run=False))

    result = pd.read_csv(out_csv)
    assert sorted(result['date'].astype(str).tolist()) == ['2026-08-01', '2026-08-05']


def test_migrate_manual_head_score_is_missing_not_zero(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': 2,
         'sleep_score': 4, 'comment': 'メモ'},
    ])
    out_csv = tmp_path / 'daily_morning.csv'
    monkeypatch.setattr(daily, 'MANUAL_FILE', manual_csv)
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', out_csv)

    daily.cmd_migrate_manual(_ns(dry_run=False))

    result = pd.read_csv(out_csv)
    assert result.iloc[0]['head_score'] != 0
    assert pd.isna(result.iloc[0]['head_score'])


def test_migrate_manual_dry_run_does_not_write(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': None,
         'sleep_score': None, 'comment': None},
    ])
    out_csv = tmp_path / 'daily_morning.csv'
    monkeypatch.setattr(daily, 'MANUAL_FILE', manual_csv)
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', out_csv)

    daily.cmd_migrate_manual(_ns(dry_run=True))

    assert not out_csv.exists()


def test_migrate_manual_twice_never_overwrites_form_row(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': None,
         'sleep_score': None, 'comment': 'sheet由来のコメント'},
    ])
    out_csv = tmp_path / 'daily_morning.csv'
    pd.DataFrame([{
        'date': '2026-08-01', 'updated_at': '2026-08-01 07:00:00',
        'source': 'form', 'mind_score': 5, 'body_score': 4,
        'head_score': 2, 'sleep_score': 3, 'comment': 'form由来のコメント',
    }])[store.SLOTS['morning']['columns']].to_csv(out_csv, index=False)

    monkeypatch.setattr(daily, 'MANUAL_FILE', manual_csv)
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', out_csv)

    daily.cmd_migrate_manual(_ns(dry_run=False))
    daily.cmd_migrate_manual(_ns(dry_run=False))

    result = pd.read_csv(out_csv)
    assert len(result) == 1
    row = result.iloc[0]
    assert row['source'] == 'form'
    assert row['mind_score'] == 5
    assert row['comment'] == 'form由来のコメント'


# --- store.load_entries ---

def test_load_entries_keeps_missing_scores_as_na_morning(tmp_path, monkeypatch):
    csv = tmp_path / 'daily_morning.csv'
    csv.write_text(
        'date,updated_at,source,mind_score,body_score,head_score,sleep_score,comment\n'
        '2026-08-01,,sheet,3,,,,\n'
        '2026-08-02,2026-08-02 07:00:00,form,4,3,2,5,元気\n'
    )
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', csv)

    df = store.load_entries('morning')

    assert str(df['mind_score'].dtype) == 'Int64'
    assert str(df['body_score'].dtype) == 'Int64'
    assert df['body_score'].isna().tolist() == [True, False]
    assert df['mind_score'].tolist() == [3, 4]


def test_load_entries_backfills_missing_columns(tmp_path, monkeypatch):
    """列そのものが無い CSV（スキーマ変更前）でも落ちない"""
    csv = tmp_path / 'daily_morning.csv'
    csv.write_text('date,mind_score\n2026-08-01,3\n')
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', csv)

    df = store.load_entries('morning')

    assert list(df.columns) == store.SLOTS['morning']['columns']
    assert df['body_score'].isna().all()
    assert df['sleep_score'].isna().all()


def test_load_entries_missing_csv_returns_empty_frame_with_correct_dtypes(tmp_path, monkeypatch):
    """夜フォーム未作成など CSV が無い場合、正しい列・dtype の空 DataFrame を返す"""
    csv = tmp_path / 'daily_evening.csv'
    monkeypatch.setitem(store.SLOTS['evening'], 'csv_file', csv)

    df = store.load_entries('evening')

    assert list(df.columns) == store.SLOTS['evening']['columns']
    assert len(df) == 0
    assert str(df['mind_score'].dtype) == 'Int64'
