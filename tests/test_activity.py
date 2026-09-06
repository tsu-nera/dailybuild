# coding: utf-8
"""活動記録（Google Sheets → CSV）のマージと欠測の扱い

書いているのは「欠測を捏造しないこと」と「二重に入れないこと」の2点だけ
（ADR-002）。表示の文面は対象にしない。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / 'src'))

_spec = importlib.util.spec_from_file_location(
    'activity_script', BASE_DIR / 'scripts' / 'activity.py')
activity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(activity)

COLUMNS = ['timestamp', 'activity', 'enjoyment', 'importance', 'note']
HEADER = list(COLUMNS)


def rows(*values):
    return [HEADER] + [list(v) for v in values]


def test_未評定は0ではなく欠測として残る():
    df = activity.build_dataframe(
        rows(['2026-09-06 10:00:00', '読書', '', '', '']), COLUMNS)
    assert len(df) == 1
    assert pd.isna(df.loc[0, 'enjoyment'])
    assert pd.isna(df.loc[0, 'importance'])


def test_評定0は欠測にならない():
    df = activity.build_dataframe(
        rows(['2026-09-06 10:00:00', '臥床', '0', '0', '']), COLUMNS)
    assert df.loc[0, 'enjoyment'] == 0
    assert df.loc[0, 'importance'] == 0


def test_活動が空の行は取り込まない():
    """Apps Script が時刻だけ入れた行や、書きかけて消した行を拾わない"""
    df = activity.build_dataframe(
        rows(['2026-09-06 10:00:00', '', '5', '5', ''],
             ['2026-09-06 11:00:00', '散歩', '', '', '']), COLUMNS)
    assert list(df['activity']) == ['散歩']


def test_timestampが空の行は取り込まない():
    df = activity.build_dataframe(
        rows(['', '散歩', '', '', '']), COLUMNS)
    assert df.empty


def test_解釈できないtimestampの行だけを落とす():
    df = activity.build_dataframe(
        rows(['きのう', '散歩', '', '', ''],
             ['2026-09-06 11:00:00', '読書', '', '', '']), COLUMNS)
    assert list(df['activity']) == ['読書']


def test_列が足りなければ落とす():
    """黙って別の列を読むより、取得を失敗させる"""
    with pytest.raises(ValueError):
        activity.build_dataframe(
            [['timestamp', 'activity'], ['2026-09-06 10:00:00', '読書']],
            COLUMNS)


def test_列の並びが変わっても位置ではなく名前で引く():
    values = [['activity', 'timestamp', 'note', 'enjoyment', 'importance'],
              ['読書', '2026-09-06 10:00:00', 'メモ', '8', '3']]
    df = activity.build_dataframe(values, COLUMNS)
    assert df.loc[0, 'activity'] == '読書'
    assert df.loc[0, 'enjoyment'] == 8
    assert df.loc[0, 'note'] == 'メモ'


def test_同じ行を2回取り込んでも増えない(tmp_path):
    """fetch は毎回シート全件を読む。冪等でないと日次実行で行が増え続ける"""
    from lib.utils import csv_utils

    csv_path = tmp_path / 'activity.csv'
    df = activity.build_dataframe(
        rows(['2026-09-06 10:00:00', '読書', '8', '3', ''],
             ['2026-09-06 12:00:00', '昼食', '5', '5', '']), COLUMNS)

    for _ in range(2):
        merged = csv_utils.merge_csv_by_columns(
            df, csv_path, key_columns=['timestamp'],
            parse_dates=['timestamp'], sort_by=['timestamp'])
        merged.to_csv(csv_path, index=False)

    assert len(pd.read_csv(csv_path)) == 2


def test_評定を後から付けると既存行が更新される(tmp_path):
    """シート側で評定を追記したとき、CSV の未評定行が置き換わること"""
    from lib.utils import csv_utils

    csv_path = tmp_path / 'activity.csv'
    before = activity.build_dataframe(
        rows(['2026-09-06 10:00:00', '読書', '', '', '']), COLUMNS)
    csv_utils.merge_csv_by_columns(
        before, csv_path, key_columns=['timestamp'],
        parse_dates=['timestamp'], sort_by=['timestamp']).to_csv(
            csv_path, index=False)

    after = activity.build_dataframe(
        rows(['2026-09-06 10:00:00', '読書', '8', '3', '']), COLUMNS)
    merged = csv_utils.merge_csv_by_columns(
        after, csv_path, key_columns=['timestamp'],
        parse_dates=['timestamp'], sort_by=['timestamp'])

    assert len(merged) == 1
    assert merged.iloc[0]['enjoyment'] == 8
