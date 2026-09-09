"""日次記録・朝夜分割（Issue #157 / #167）のパース・マージ・移行・境界のテスト

実機の Google Forms API は叩かず、変換ロジックだけを検証する。
スキーマは config/daily_{morning,evening}_def.yaml が唯一の正本（Issue #167）。
config/ は public な通常ファイルなので、テストからも実物の yaml をそのまま読む。
"""

import copy
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

CONFS = {'morning': store.load_def('morning'), 'evening': store.load_def('evening')}

# 削除・並び替えを検出するための既知キー（末尾追加は許す。append-only ガード）
_MORNING_KNOWN_KEYS = ['mind', 'body', 'head', 'sleep', 'comment', 'hrv_rmssd', 'eda_responses']
_EVENING_KNOWN_KEYS = ['mind', 'body', 'head', 'satisfaction', 'achievement',
                       'comment', 'hrv_rmssd', 'eda_responses']


def _build_fake_form(conf):
    """conf から daily.build_items() が組む item 順で fake form を作る

    questionId は出現順（FIFO）で割り振る。grid の行は q_grid_i、
    text/number は q_text_i。
    """
    grid_entries = store.grid_rows(conf)
    text_like = [e for e in store.active_questions(conf) if e['type'] in ('text', 'number')]
    items = [{
        'title': conf['grid_title'],
        'questionGroupItem': {
            'questions': [
                {'questionId': f'q_grid_{i}', 'required': e.get('required', False),
                 'rowQuestion': {'title': e['label']}}
                for i, e in enumerate(grid_entries)
            ],
            'grid': {'columns': {'type': 'RADIO',
                                 'options': [{'value': str(n)} for n in range(1, 6)]}},
        },
    }]
    for i, e in enumerate(text_like):
        items.append({
            'title': e['label'],
            'questionItem': {'question': {
                'questionId': f'q_text_{i}',
                'textQuestion': {'paragraph': False},
            }},
        })
    return {'items': items}


def _response(conf, form, timestamp, **answers_by_key):
    """answers_by_key: {question key: value}（'comment' も含めてよい）"""
    by_title = daily.gforms_client.question_id_by_title(form)
    key_to_label = {q['key']: q['label'] for q in conf['questions']}
    answers = {}
    for key, value in answers_by_key.items():
        qid = by_title[key_to_label[key]]
        answers[qid] = {'textAnswers': {'answers': [{'value': str(value)}]}}
    return {'lastSubmittedTime': timestamp, 'answers': answers}


def _ns(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


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


# --- 定義（yaml）の不変条件 ---

@pytest.mark.parametrize('slot,expected_prefix', [
    ('morning', _MORNING_KNOWN_KEYS),
    ('evening', _EVENING_KNOWN_KEYS),
])
def test_questions_keys_are_append_only(slot, expected_prefix):
    """全エントリ（active の真偽によらず）の key が既知リストの prefix であること。

    削除・並び替えを検出して落とす。追加は末尾なら通る（このリストを
    伸ばすだけでよい）。
    """
    conf = CONFS[slot]
    keys = [q['key'] for q in conf['questions']]
    assert keys[:len(expected_prefix)] == expected_prefix


@pytest.mark.parametrize('slot', ['morning', 'evening'])
def test_build_items_comment_is_first_text_question(slot):
    conf = CONFS[slot]
    items = daily.build_items(conf)
    text_items = [i for i in items if 'questionItem' in i
                 and 'textQuestion' in i['questionItem']['question']]
    assert text_items[0]['title'] == 'コメント'


# --- build_dataframe: grid 行の割り当て（順序不変条件、両slot共通） ---

@pytest.mark.parametrize('slot', ['morning', 'evening'])
def test_build_dataframe_assigns_grid_rows_in_yaml_order(slot):
    conf = CONFS[slot]
    form = _build_fake_form(conf)
    grid_entries = store.grid_rows(conf)
    answers = {e['key']: i + 1 for i, e in enumerate(grid_entries)}
    responses = [_response(conf, form, '2026-09-01T10:00:00Z', **answers)]
    df = daily.build_dataframe(form, responses, conf, slot)
    row = df.iloc[0]
    for i, e in enumerate(grid_entries):
        assert row[e['column']] == i + 1


@pytest.mark.parametrize('slot', ['morning', 'evening'])
def test_build_dataframe_unanswered_grid_row_is_na_not_zero(slot):
    conf = CONFS[slot]
    form = _build_fake_form(conf)
    grid_entries = store.grid_rows(conf)
    # mind だけ答え、それ以外のグリッド行は無回答のまま
    responses = [_response(conf, form, '2026-09-01T10:00:00Z', mind=3)]
    df = daily.build_dataframe(form, responses, conf, slot)
    row = df.iloc[0]
    for e in grid_entries:
        if e['key'] == 'mind':
            continue
        assert pd.isna(row[e['column']])


@pytest.mark.parametrize('slot', ['morning', 'evening'])
def test_build_dataframe_number_question_unparseable_is_na_not_zero(slot):
    conf = CONFS[slot]
    form = _build_fake_form(conf)
    responses = [_response(conf, form, '2026-09-01T10:00:00Z',
                           mind=3, hrv_rmssd='invalid')]
    df = daily.build_dataframe(form, responses, conf, slot)
    assert pd.isna(df.iloc[0]['hrv_rmssd'])


@pytest.mark.parametrize('slot', ['morning', 'evening'])
def test_build_dataframe_number_question_zero_is_preserved(slot):
    """EDA responses は 0 が正当な実測値。欠測(NA)と混同しない"""
    conf = CONFS[slot]
    form = _build_fake_form(conf)
    responses = [_response(conf, form, '2026-09-01T10:00:00Z',
                           mind=3, eda_responses=0)]
    df = daily.build_dataframe(form, responses, conf, slot)
    assert df.iloc[0]['eda_responses'] == 0
    assert not pd.isna(df.iloc[0]['eda_responses'])


@pytest.mark.parametrize('slot', ['morning', 'evening'])
def test_build_dataframe_number_question_unanswered_is_na(slot):
    conf = CONFS[slot]
    form = _build_fake_form(conf)
    responses = [_response(conf, form, '2026-09-01T10:00:00Z', mind=3)]
    df = daily.build_dataframe(form, responses, conf, slot)
    assert pd.isna(df.iloc[0]['hrv_rmssd'])
    assert pd.isna(df.iloc[0]['eda_responses'])


@pytest.mark.parametrize('slot', ['morning', 'evening'])
def test_build_dataframe_column_order(slot):
    conf = CONFS[slot]
    form = _build_fake_form(conf)
    df = daily.build_dataframe(form, [], conf, slot)
    assert list(df.columns) == store.columns(slot, conf)


# --- 朝: date は暦日のまま ---

def test_build_dataframe_morning_collapses_same_date_to_last_response():
    conf = CONFS['morning']
    form = _build_fake_form(conf)
    responses = [
        _response(conf, form, '2026-09-01T01:00:00Z', mind=2, comment='朝の分'),
        _response(conf, form, '2026-09-01T10:00:00Z', mind=4, comment='夜の分'),
    ]
    df = daily.build_dataframe(form, responses, conf, 'morning')

    assert len(df) == 1
    assert df.iloc[0]['mind_score'] == 4
    assert df.iloc[0]['comment'] == '夜の分'


def test_build_dataframe_morning_date_matches_response_calendar_date():
    """朝の date は暦日のまま（起床直後の回答でも1日ずれない）"""
    conf = CONFS['morning']
    form = _build_fake_form(conf)
    responses = [_response(conf, form, '2026-08-31T22:00:00Z', mind=3, sleep=4)]  # JST 07:00
    df = daily.build_dataframe(form, responses, conf, 'morning')

    assert str(df.iloc[0]['date']) == '2026-09-01'


def test_build_dataframe_morning_has_source_column():
    conf = CONFS['morning']
    form = _build_fake_form(conf)
    responses = [_response(conf, form, '2026-09-01T10:00:00Z', mind=1)]
    df = daily.build_dataframe(form, responses, conf, 'morning')
    assert df.iloc[0]['source'] == 'form'


# --- 夜: 5:00 境界・source列なし ---

def test_build_dataframe_evening_date_uses_5am_boundary():
    conf = CONFS['evening']
    form = _build_fake_form(conf)
    # JST 03:30 = UTC 前日 18:30
    responses = [_response(conf, form, '2026-08-31T18:30:00Z', mind=3)]
    df = daily.build_dataframe(form, responses, conf, 'evening')

    assert str(df.iloc[0]['date']) == '2026-08-31'


def test_build_dataframe_evening_has_no_source_column():
    conf = CONFS['evening']
    form = _build_fake_form(conf)
    df = daily.build_dataframe(form, [], conf, 'evening')
    assert 'source' not in df.columns


# --- fetch のマージは行ごと置換（両 slot で確認） ---

def test_fetch_merge_replaces_whole_row_for_evening(tmp_path):
    conf = CONFS['evening']
    form = _build_fake_form(conf)
    out_file = tmp_path / 'daily_evening.csv'

    df1 = daily.build_dataframe(
        form, [_response(conf, form, '2026-09-01T13:00:00Z', mind=2, comment='最初のコメント')],
        conf, 'evening')
    merged1 = csv_utils.merge_csv_by_columns(
        df1, out_file, key_columns=['date'], parse_dates=['date'], sort_by=['date'])
    merged1.to_csv(out_file, index=False)
    assert merged1.iloc[0]['comment'] == '最初のコメント'

    # 同じ date（JST, 5:00境界後）にコメント無しで再送信
    df2 = daily.build_dataframe(
        form, [_response(conf, form, '2026-09-01T14:00:00Z', mind=3)],
        conf, 'evening')
    merged2 = csv_utils.merge_csv_by_columns(
        df2, out_file, key_columns=['date'], parse_dates=['date'], sort_by=['date'])

    assert len(merged2) == 1
    assert merged2.iloc[0]['mind_score'] == 3
    assert pd.isna(merged2.iloc[0]['comment'])


def test_fetch_merge_is_idempotent_for_evening(tmp_path):
    """同じ回答を2回 fetch しても行が増えない"""
    conf = CONFS['evening']
    form = _build_fake_form(conf)
    out_file = tmp_path / 'daily_evening.csv'
    responses = [_response(conf, form, '2026-09-01T13:00:00Z', mind=2, comment='メモ')]

    for _ in range(2):
        df = daily.build_dataframe(form, responses, conf, 'evening')
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

    morning_form = _build_fake_form(CONFS['morning'])
    evening_form = _build_fake_form(CONFS['evening'])

    def fake_load_def(slot):
        return {'morning': {**CONFS['morning'], 'form_id': 'FORM_M'},
               'evening': {**CONFS['evening'], 'form_id': 'FORM_E'}}[slot]

    morning_response = _response(CONFS['morning'], morning_form,
                                 '2026-09-01T22:00:00Z', mind=4)
    evening_response = _response(CONFS['evening'], evening_form,
                                 '2026-09-01T13:00:00Z', mind=2)

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
                return {'FORM_M': morning_form, 'FORM_E': evening_form}[form_id]
            responses_by_form = {
                'FORM_M': [morning_response],
                'FORM_E': [evening_response],
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
    columns = store.columns('morning', CONFS['morning'])
    row = {c: pd.NA for c in columns}
    row.update({
        'date': '2026-08-01', 'updated_at': '2026-08-01 07:00:00',
        'source': 'form', 'mind_score': 5, 'body_score': 4,
        'head_score': 2, 'sleep_score': 3, 'comment': 'form由来のコメント',
    })
    pd.DataFrame([row])[columns].to_csv(out_csv, index=False)

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

    assert list(df.columns) == store.columns('morning', CONFS['morning'])
    assert df['body_score'].isna().all()
    assert df['sleep_score'].isna().all()


def test_load_entries_missing_csv_returns_empty_frame_with_correct_dtypes(tmp_path, monkeypatch):
    """夜フォーム未作成など CSV が無い場合、正しい列・dtype の空 DataFrame を返す"""
    csv = tmp_path / 'daily_evening.csv'
    monkeypatch.setitem(store.SLOTS['evening'], 'csv_file', csv)

    df = store.load_entries('evening')

    assert list(df.columns) == store.columns('evening', CONFS['evening'])
    assert len(df) == 0
    assert str(df['mind_score'].dtype) == 'Int64'


def test_load_entries_number_column_is_float64_and_blank_is_na(tmp_path, monkeypatch):
    """HRV のような数値列は Float64 で、空欄は 0 でなく NA になる"""
    csv = tmp_path / 'daily_morning.csv'
    columns = store.columns('morning', CONFS['morning'])
    row1 = {c: pd.NA for c in columns}
    row1.update({'date': '2026-08-01', 'mind_score': 3, 'hrv_rmssd': 45.3})
    row2 = {c: pd.NA for c in columns}
    row2.update({'date': '2026-08-02', 'mind_score': 4})
    pd.DataFrame([row1, row2])[columns].to_csv(csv, index=False)
    monkeypatch.setitem(store.SLOTS['morning'], 'csv_file', csv)

    df = store.load_entries('morning')

    assert str(df['hrv_rmssd'].dtype) == 'Float64'
    assert df['hrv_rmssd'].tolist()[0] == 45.3
    assert pd.isna(df['hrv_rmssd'].tolist()[1])


# --- 退役（active: false）: 列は残し、フォームからだけ外す ---

def _conf_with_retired(slot, key):
    """conf の1設問だけ active: false にした複製を返す"""
    conf = copy.deepcopy(CONFS[slot])
    for q in conf['questions']:
        if q['key'] == key:
            q['active'] = False
    return conf


def test_retired_question_is_dropped_from_form_items():
    conf = _conf_with_retired('morning', 'eda_responses')
    titles = [i.get('title') for i in daily.build_items(conf)]
    assert 'EDA responses (回)' not in titles
    assert 'コメント' in titles  # 他の設問は残る


def test_retired_question_keeps_its_csv_column_as_na():
    """退役させても CSV 列は残り、欠測として埋まる（過去データを読めなくしない）。

    行の組み立ては active な設問しか見ないので、補わないと列選択が
    KeyError で落ちる。設問を退役させた次の fetch が壊れる経路。
    """
    conf = _conf_with_retired('morning', 'eda_responses')
    form = _build_fake_form(conf)
    res = _response(conf, form, '2026-09-01T23:00:00Z', mind=3, comment='x')
    df = daily.build_dataframe(form, [res], conf, 'morning')

    assert 'eda_responses' in df.columns
    assert df['eda_responses'].isna().all()
    assert list(df.columns) == store.columns('morning', conf)


def test_retired_question_empty_response_list_keeps_column():
    conf = _conf_with_retired('evening', 'hrv_rmssd')
    form = _build_fake_form(conf)
    df = daily.build_dataframe(form, [], conf, 'evening')
    assert list(df.columns) == store.columns('evening', conf)
