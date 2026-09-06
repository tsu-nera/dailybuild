# coding: utf-8
"""活動記録（Google Sheets Form 1 グリッド → CSV）

書いているのは「欠測を捏造しないこと」「二重に入れないこと」「列がずれたまま
黙って取り込まないこと」の3点だけ（ADR-002）。表示の文面は対象にしない。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.activity import store  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    'activity_script', BASE_DIR / 'scripts' / 'activity.py')
activity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(activity)

CONF = {'time_header': '時間', 'day_columns': ['活動', '楽しさ', '重要さ']}
DATES = ['2026-09-07', '2026-09-08']


def grid(*slot_rows, dates=DATES):
    """ヘッダ2行 + 指定した枠の行だけを持つシートを作る

    slot_rows は (枠の見出し, [日1の3セル], [日2の3セル], ...) の並び。
    """
    n = len(dates)
    head_date = [''] + [d if i == 0 else '' for d in dates for i in range(3)]
    head_col = ['時間'] + ['活動', '楽しさ', '重要さ'] * n
    body = [[label] + [c for cells in per_day for c in cells]
            for label, *per_day in slot_rows]
    return [head_date, head_col] + body


def test_未評定は0ではなく欠測として残る():
    df = activity.build_dataframe(
        grid(('10-11', ['読書', '', ''], ['', '', ''])), CONF)
    assert len(df) == 1
    assert pd.isna(df.iloc[0]['enjoyment'])
    assert pd.isna(df.iloc[0]['importance'])


def test_評定0は欠測にならない():
    df = activity.build_dataframe(
        grid(('10-11', ['臥床', '0', '0'], ['', '', ''])), CONF)
    assert df.iloc[0]['enjoyment'] == 0
    assert df.iloc[0]['importance'] == 0


def test_活動が空の枠は取り込まない():
    """評定だけが入っている枠は記録として成立していない"""
    df = activity.build_dataframe(
        grid(('10-11', ['', '5', '5'], ['散歩', '', ''])), CONF)
    assert list(df['activity']) == ['散歩']
    assert df.iloc[0]['date'] == '2026-09-08'


def test_日ごとの列ブロックが正しい日付に割り当たる():
    df = activity.build_dataframe(
        grid(('10-11', ['月の活動', '1', '2'], ['火の活動', '3', '4'])), CONF)
    got = {r['date']: (r['activity'], r['enjoyment'])
           for _, r in df.iterrows()}
    assert got == {'2026-09-07': ('月の活動', 1),
                   '2026-09-08': ('火の活動', 3)}


def test_見出しが崩れていたら落とす():
    """黙って別の列を読むと、評定が別の日に付く"""
    values = grid(('10-11', ['読書', '', ''], ['', '', '']))
    values[1][2] = '重要さ'  # 楽しさ / 重要さ が入れ替わった状態
    with pytest.raises(ValueError):
        activity.build_dataframe(values, CONF)


def test_知らない枠の見出しは落とす():
    """行を足したり並べ替えたりしたシートを黙って取り込まない"""
    with pytest.raises(ValueError):
        activity.build_dataframe(
            grid(('朝', ['読書', '', ''], ['', '', ''])), CONF)


def test_未明の枠は前日の日付に属する():
    """原典の1日は 5am 始まり。0-1 の枠は物理的には翌暦日だが前日に属する"""
    df = activity.build_dataframe(
        grid(('0-1', ['入眠できず', '2', '1'], ['', '', ''])), CONF)
    assert df.iloc[0]['date'] == '2026-09-07'
    assert df.iloc[0]['hour'] == 0


def test_2時から5時は3時間の1枠():
    """原典の最後の枠だけが3時間。長さを1時間として数えると睡眠中が過少になる"""
    assert store.SLOT_HOURS[2] == 3
    assert store.slot_label(2) == '2-5'
    assert len(store.SLOTS) == 22


def test_同じシートを2回取り込んでも増えない(tmp_path):
    from lib.utils import csv_utils

    csv_path = tmp_path / 'activity.csv'
    df = activity.build_dataframe(
        grid(('10-11', ['読書', '8', '3'], ['', '', '']),
             ('12-13', ['昼食', '5', '5'], ['', '', ''])), CONF)

    for _ in range(2):
        merged = csv_utils.replace_csv_period(
            df, csv_path, date_column='date',
            start_date=df['date'].min(),
            end_date=df['date'].max(), sort_by=['date', 'hour'])
        merged.to_csv(csv_path, index=False)

    assert len(pd.read_csv(csv_path)) == 2


def test_シートで枠を消すとCSVからも消える(tmp_path):
    """キーマージだと訂正が反映されず、消したはずの記録が残り続ける"""
    from lib.utils import csv_utils

    csv_path = tmp_path / 'activity.csv'
    before = activity.build_dataframe(
        grid(('10-11', ['読書', '8', '3'], ['', '', '']),
             ('12-13', ['書き間違い', '5', '5'], ['', '', ''])), CONF)
    csv_utils.replace_csv_period(
        before, csv_path, date_column='date',
        start_date=before['date'].min(),
        end_date=before['date'].max(),
        sort_by=['date', 'hour']).to_csv(csv_path, index=False)

    after = activity.build_dataframe(
        grid(('10-11', ['読書', '8', '3'], ['', '', ''])), CONF)
    merged = csv_utils.replace_csv_period(
        after, csv_path, date_column='date',
        start_date=after['date'].min(),
        end_date=after['date'].max(), sort_by=['date', 'hour'])

    assert list(merged['activity']) == ['読書']


def test_取得しなかった週の行は消さない(tmp_path):
    """期間置換は新データにある日付だけを消す（欠測の捏造を避ける）"""
    from lib.utils import csv_utils

    csv_path = tmp_path / 'activity.csv'
    old = activity.build_dataframe(
        grid(('10-11', ['先週の記録', '4', '4']), dates=['2026-08-31']), CONF)
    csv_utils.replace_csv_period(
        old, csv_path, date_column='date',
        start_date=old['date'].min(),
        end_date=old['date'].max(),
        sort_by=['date', 'hour']).to_csv(csv_path, index=False)

    new = activity.build_dataframe(
        grid(('10-11', ['今週の記録', '6', '6'], ['', '', ''])), CONF)
    merged = csv_utils.replace_csv_period(
        new, csv_path, date_column='date',
        start_date=new['date'].min(),
        end_date=new['date'].max(), sort_by=['date', 'hour'])

    assert list(merged['activity']) == ['先週の記録', '今週の記録']


def test_タブの中身は22枠と7日ぶんの列を持つ():
    conf = dict(CONF, score={'low': 0, 'high': 10})
    g = activity.sheet_grid('2026-W37', conf)
    assert g[0][1] == '2026-09-07' and g[0][19] == '2026-09-13'
    assert len(g) == 2 + 22
    assert len(g[1]) == 1 + 21
    assert g[2][0] == '5-6' and g[-1][0] == '2-5'
