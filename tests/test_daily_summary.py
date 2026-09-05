"""日次記録（Issue #135）のパース・マージ・移行のテスト

実機の Google Forms API は叩かず、変換ロジックだけを検証する。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.daily_summary import store
from lib.utils import csv_utils


def _load_script():
    """scripts/ 配下はパッケージではないのでファイルから直接ロードする"""
    path = BASE_DIR / 'scripts' / 'daily_summary.py'
    spec = importlib.util.spec_from_file_location('daily_summary', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['daily_summary'] = module
    spec.loader.exec_module(module)
    return module


daily_summary = _load_script()


CONF = {
    'questions': {
        'mind': '気分', 'body': '身体の軽さ', 'head': '頭の軽さ',
        'sleep': '昨夜の眠り', 'comment': 'コメント',
    },
    'grid_rows': ['mind', 'body', 'head', 'sleep'],
    'grid_required': {'mind': True, 'body': False, 'head': False, 'sleep': False},
    'score': {'low': 1, 'high': 5, 'low_label': '悪い', 'high_label': '良い'},
}


def _form():
    return {
        'items': [
            {
                'title': '今日はどうだった？',
                'questionGroupItem': {
                    'questions': [
                        {'questionId': 'q_mind', 'required': True,
                         'rowQuestion': {'title': '気分'}},
                        {'questionId': 'q_body', 'required': False,
                         'rowQuestion': {'title': '身体の軽さ'}},
                        {'questionId': 'q_head', 'required': False,
                         'rowQuestion': {'title': '頭の軽さ'}},
                        {'questionId': 'q_sleep', 'required': False,
                         'rowQuestion': {'title': '昨夜の眠り'}},
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


def _response(timestamp, mind=None, body=None, head=None, sleep=None, comment=None):
    answers = {}
    if mind is not None:
        answers['q_mind'] = {'textAnswers': {'answers': [{'value': mind}]}}
    if body is not None:
        answers['q_body'] = {'textAnswers': {'answers': [{'value': body}]}}
    if head is not None:
        answers['q_head'] = {'textAnswers': {'answers': [{'value': head}]}}
    if sleep is not None:
        answers['q_sleep'] = {'textAnswers': {'answers': [{'value': sleep}]}}
    if comment is not None:
        answers['q_comment'] = {'textAnswers': {'answers': [{'value': comment}]}}
    return {'lastSubmittedTime': timestamp, 'answers': answers}


# --- build_dataframe: 同一 date の複数回答は最後を採る ---

def test_build_dataframe_collapses_same_date_to_last_response():
    responses = [
        _response('2026-09-01T01:00:00Z', mind='2', comment='朝の分'),
        _response('2026-09-01T10:00:00Z', mind='4', comment='夜の分'),
    ]
    df = daily_summary.build_dataframe(_form(), responses, CONF)

    assert len(df) == 1
    assert df.iloc[0]['mind_score'] == 4
    assert df.iloc[0]['comment'] == '夜の分'


# --- build_dataframe: 列構成・型 ---

def test_build_dataframe_column_order():
    df = daily_summary.build_dataframe(_form(), [], CONF)
    assert list(df.columns) == store.COLUMNS


def test_build_dataframe_scores_are_nullable_int_and_survive_missing():
    responses = [
        _response('2026-09-01T10:00:00Z', mind='4', body='3'),
        _response('2026-09-02T10:00:00Z', mind='2'),
    ]
    df = daily_summary.build_dataframe(_form(), responses, CONF)

    assert str(df['mind_score'].dtype) == 'Int64'
    assert str(df['body_score'].dtype) == 'Int64'
    assert df.loc[df['date'] == pd.Timestamp('2026-09-01').date(), 'body_score'].iloc[0] == 3
    assert pd.isna(df.loc[df['date'] == pd.Timestamp('2026-09-02').date(), 'body_score'].iloc[0])


def test_build_dataframe_assigns_four_grid_rows_without_reordering():
    """4行のグリッド回答が mind/body/head/sleep に正しく割り当たる（回帰）

    grid_rows の並び順を変えたときに列の取り違えが起きないことを固定する。
    """
    responses = [
        _response('2026-09-01T10:00:00Z', mind='1', body='2', head='3', sleep='4'),
    ]
    df = daily_summary.build_dataframe(_form(), responses, CONF)

    row = df.iloc[0]
    assert row['mind_score'] == 1
    assert row['body_score'] == 2
    assert row['head_score'] == 3
    assert row['sleep_score'] == 4


# --- fetch のマージは行ごと置換（セル単位マージにしない） ---

def test_fetch_merge_replaces_whole_row_comment_does_not_survive(tmp_path):
    """preserve_existing_on_nan=False（既定）のまま使うことの回帰ガード

    もしセル単位マージ（True）に戻すと、comment を空で送った回答が来た
    ときに旧行の comment が生き残り、source=form の行なのに comment だけ
    sheet 由来という壊れた行ができる。
    """
    out_file = tmp_path / 'daily_summary.csv'

    df1 = daily_summary.build_dataframe(
        _form(), [_response('2026-09-01T10:00:00Z', mind='2', comment='最初のコメント')], CONF)
    merged1 = csv_utils.merge_csv_by_columns(
        df1, out_file, key_columns=['date'], parse_dates=['date'], sort_by=['date'])
    merged1.to_csv(out_file, index=False)
    assert merged1.iloc[0]['comment'] == '最初のコメント'

    # 同じ date（JST）に comment 無しで再送信
    df2 = daily_summary.build_dataframe(
        _form(), [_response('2026-09-01T12:00:00Z', mind='3')], CONF)
    merged2 = csv_utils.merge_csv_by_columns(
        df2, out_file, key_columns=['date'], parse_dates=['date'], sort_by=['date'])

    assert len(merged2) == 1
    assert merged2.iloc[0]['mind_score'] == 3
    # comment は空欄で置換されている（旧 comment が残らない）
    assert pd.isna(merged2.iloc[0]['comment'])


# --- 「昨夜の眠り」の date は回答の暦日と一致する（dateOfSleep=起床日と同じ向き） ---

def test_sleep_row_date_matches_response_calendar_date(tmp_path):
    """data/wearable/sleep.csv の dateOfSleep（起床日）との整合を固定する

    朝に回答した場合、その回答の date は response の JST 暦日と一致する
    べきで、1日ずらす補正をしてはいけない（1日ズレの回帰ガード）。
    """
    fake_sleep_csv = tmp_path / 'sleep.csv'
    fake_sleep_csv.write_text(
        'dateOfSleep,startTime,endTime\n'
        '2026-09-01,2026-08-31T23:00:00.000,2026-09-01T06:30:00.000\n'
    )
    sleep_df = pd.read_csv(fake_sleep_csv)
    wake_date = sleep_df.iloc[0]['dateOfSleep']

    # 起床直後（JST 07:00 = UTC 前日22:00）に「昨夜の眠り」へ回答したとする
    responses = [_response('2026-08-31T22:00:00Z', mind='3', sleep='4')]
    df = daily_summary.build_dataframe(_form(), responses, CONF)

    assert str(df.iloc[0]['date']) == wake_date
    assert df.iloc[0]['sleep_score'] == 4


# --- migrate-manual ---

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
    out_csv = tmp_path / 'daily_summary.csv'
    monkeypatch.setattr(daily_summary, 'MANUAL_FILE', manual_csv)
    monkeypatch.setattr(daily_summary, 'OUT_FILE', out_csv)
    monkeypatch.setattr(daily_summary.store, 'CSV_FILE', out_csv)

    daily_summary.cmd_migrate_manual(argparse_namespace(dry_run=False))

    result = pd.read_csv(out_csv)
    assert result['date'].astype(str).tolist() == ['2026-08-02']


def test_migrate_manual_does_not_fabricate_missing_dates(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': None,
         'sleep_score': None, 'comment': None},
        {'date': '2026-08-05', 'mind_score': 2, 'body_score': None,
         'sleep_score': None, 'comment': None},
    ])
    out_csv = tmp_path / 'daily_summary.csv'
    monkeypatch.setattr(daily_summary, 'MANUAL_FILE', manual_csv)
    monkeypatch.setattr(daily_summary, 'OUT_FILE', out_csv)
    monkeypatch.setattr(daily_summary.store, 'CSV_FILE', out_csv)

    daily_summary.cmd_migrate_manual(argparse_namespace(dry_run=False))

    result = pd.read_csv(out_csv)
    # 8/2, 8/3, 8/4 のような manual.csv に無い日を埋めていない
    assert sorted(result['date'].astype(str).tolist()) == ['2026-08-01', '2026-08-05']


def test_migrate_manual_head_score_is_missing_not_zero(tmp_path, monkeypatch):
    """manual.csv に頭の記録は無いので、移行行の head_score は欠測のまま

    0 や 3 で埋めると「未記録」が「回答した」に化ける。
    """
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': 2,
         'sleep_score': 4, 'comment': 'メモ'},
    ])
    out_csv = tmp_path / 'daily_summary.csv'
    monkeypatch.setattr(daily_summary, 'MANUAL_FILE', manual_csv)
    monkeypatch.setattr(daily_summary, 'OUT_FILE', out_csv)
    monkeypatch.setattr(daily_summary.store, 'CSV_FILE', out_csv)

    daily_summary.cmd_migrate_manual(argparse_namespace(dry_run=False))

    result = pd.read_csv(out_csv)
    assert result.iloc[0]['head_score'] != 0
    assert pd.isna(result.iloc[0]['head_score'])


def test_migrate_manual_dry_run_does_not_write(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': None,
         'sleep_score': None, 'comment': None},
    ])
    out_csv = tmp_path / 'daily_summary.csv'
    monkeypatch.setattr(daily_summary, 'MANUAL_FILE', manual_csv)
    monkeypatch.setattr(daily_summary, 'OUT_FILE', out_csv)
    monkeypatch.setattr(daily_summary.store, 'CSV_FILE', out_csv)

    daily_summary.cmd_migrate_manual(argparse_namespace(dry_run=True))

    assert not out_csv.exists()


def test_migrate_manual_twice_never_overwrites_form_row(tmp_path, monkeypatch):
    manual_csv = _write_manual_csv(tmp_path / 'manual.csv', [
        {'date': '2026-08-01', 'mind_score': 3, 'body_score': None,
         'sleep_score': None, 'comment': 'sheet由来のコメント'},
    ])
    out_csv = tmp_path / 'daily_summary.csv'
    # 事前に Form 由来の行が既に存在する状態を作る（同じ date）
    pd.DataFrame([{
        'date': '2026-08-01', 'updated_at': '2026-08-01 07:00:00',
        'source': 'form', 'mind_score': 5, 'body_score': 4,
        'head_score': 2, 'sleep_score': 3, 'comment': 'form由来のコメント',
    }])[store.COLUMNS].to_csv(out_csv, index=False)

    monkeypatch.setattr(daily_summary, 'MANUAL_FILE', manual_csv)
    monkeypatch.setattr(daily_summary, 'OUT_FILE', out_csv)
    monkeypatch.setattr(daily_summary.store, 'CSV_FILE', out_csv)

    daily_summary.cmd_migrate_manual(argparse_namespace(dry_run=False))
    daily_summary.cmd_migrate_manual(argparse_namespace(dry_run=False))

    result = pd.read_csv(out_csv)
    assert len(result) == 1
    row = result.iloc[0]
    assert row['source'] == 'form'
    assert row['mind_score'] == 5
    assert row['comment'] == 'form由来のコメント'


def argparse_namespace(**kwargs):
    import argparse
    return argparse.Namespace(**kwargs)


# --- store.load_entries ---

def test_load_entries_keeps_missing_scores_as_na(tmp_path, monkeypatch):
    csv = tmp_path / 'daily_summary.csv'
    csv.write_text(
        'date,updated_at,source,mind_score,body_score,head_score,sleep_score,comment\n'
        '2026-08-01,,sheet,3,,,,\n'
        '2026-08-02,2026-08-02 07:00:00,form,4,3,2,5,元気\n'
    )
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df = store.load_entries()

    assert str(df['mind_score'].dtype) == 'Int64'
    assert str(df['body_score'].dtype) == 'Int64'
    # 0 に潰れていない（欠測のまま）
    assert df['body_score'].isna().tolist() == [True, False]
    assert df['body_score'].dropna().tolist() == [3]
    assert df['mind_score'].tolist() == [3, 4]


def test_load_entries_backfills_missing_columns(tmp_path, monkeypatch):
    """列そのものが無い CSV（スキーマ変更前）でも落ちない"""
    csv = tmp_path / 'daily_summary.csv'
    csv.write_text('date,mind_score\n2026-08-01,3\n')
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df = store.load_entries()

    assert list(df.columns) == store.COLUMNS
    assert df['body_score'].isna().all()
    assert df['sleep_score'].isna().all()
