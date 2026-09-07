"""Habitica の history 取得のテスト

**Habitica はタスクを削除すると history ごと消える。** API の結果で CSV を
全上書きすると、削除した瞬間に過去の記録まで失われる。復元不可なので、
これは欠測の捏造そのものになる。ここだけを対象にする。

- API に無い task_id の行を消さない
- 同じ (date, task_id) は上書きして重複させない（冪等性）
- Habit と Daily で history の中身が違う（isDue の有無）
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))


def _load_script():
    path = BASE_DIR / 'scripts' / 'habitica.py'
    spec = importlib.util.spec_from_file_location('habitica_script_history', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['habitica_script_history'] = module
    spec.loader.exec_module(module)
    return module


habitica = _load_script()


def _ms(y, m, d, hour=7):
    return int(dt.datetime(y, m, d, hour).timestamp() * 1000)


DAILY = {
    'id': 'daily-1',
    'text': '冷水シャワー',
    'history': [
        {'date': _ms(2026, 9, 5), 'value': 26.9, 'isDue': True, 'completed': True},
        {'date': _ms(2026, 9, 6), 'value': 26.1, 'isDue': True, 'completed': False},
    ],
}

HABIT = {
    'id': 'habit-1',
    'text': '坐禅',
    'history': [
        {'date': _ms(2026, 9, 5), 'value': 1.0, 'scoredUp': 1, 'scoredDown': 0},
    ],
}


def test_habitとdailyで違う列が埋まる():
    rows = habitica.history_rows([HABIT], 'habit') + habitica.history_rows([DAILY], 'daily')
    df = pd.DataFrame(rows, columns=habitica.HISTORY_COLUMNS)

    habit = df[df['task_type'] == 'habit'].iloc[0]
    assert habit['scored_up'] == 1
    assert pd.isna(habit['is_due'])     # Habit に isDue は無い＝分母が取れない

    daily = df[df['task_type'] == 'daily'].iloc[0]
    assert bool(daily['is_due']) is True
    assert pd.isna(daily['scored_up'])


def test_削除されたタスクの記録を消さない():
    """API から消えた task_id の行が残ること。ここが本題"""
    old = pd.DataFrame(
        habitica.history_rows([HABIT], 'habit') + habitica.history_rows([DAILY], 'daily'),
        columns=habitica.HISTORY_COLUMNS,
    )
    # 坐禅を Habitica 上で削除した状態（API は Daily しか返さない）
    new = pd.DataFrame(habitica.history_rows([DAILY], 'daily'),
                       columns=habitica.HISTORY_COLUMNS)

    merged = habitica.merge_history(old, new)

    assert '坐禅' in set(merged['task_name'])
    assert len(merged) == len(old)


def test_同じ日付とタスクは上書きされ重複しない():
    old = pd.DataFrame(habitica.history_rows([DAILY], 'daily'),
                       columns=habitica.HISTORY_COLUMNS)
    updated = dict(DAILY, history=[
        {'date': _ms(2026, 9, 6), 'value': 25.0, 'isDue': True, 'completed': True},
    ])
    new = pd.DataFrame(habitica.history_rows([updated], 'daily'),
                       columns=habitica.HISTORY_COLUMNS)

    merged = habitica.merge_history(old, new)

    assert len(merged) == 2
    row = merged[merged['date'] == '2026-09-06'].iloc[0]
    assert bool(row['completed']) is True   # 未完了だった行が完了で置き換わる
    assert row['value'] == 25.0


def test_2回マージしても増えない():
    new = pd.DataFrame(
        habitica.history_rows([HABIT], 'habit') + habitica.history_rows([DAILY], 'daily'),
        columns=habitica.HISTORY_COLUMNS,
    )
    once = habitica.merge_history(pd.DataFrame(columns=habitica.HISTORY_COLUMNS), new)
    twice = habitica.merge_history(once, new)

    assert len(once) == len(twice) == 3
    pd.testing.assert_frame_equal(once, twice)


def test_空のCSVから始められる():
    empty = pd.DataFrame(columns=habitica.HISTORY_COLUMNS)
    new = pd.DataFrame(habitica.history_rows([DAILY], 'daily'),
                       columns=habitica.HISTORY_COLUMNS)

    merged = habitica.merge_history(empty, new)

    assert list(merged.columns) == habitica.HISTORY_COLUMNS
    assert len(merged) == 2


def test_APIが空でも既存の記録を消さない():
    """取得に失敗して0件が返っても、CSV を空にしない"""
    old = pd.DataFrame(habitica.history_rows([DAILY], 'daily'),
                       columns=habitica.HISTORY_COLUMNS)
    merged = habitica.merge_history(old, pd.DataFrame(columns=habitica.HISTORY_COLUMNS))

    assert len(merged) == 2


def test_同じ日の2エントリを最後の状態に畳む():
    """Daily は cron 時（未完了）と完了時の2エントリが同じ日に届く"""
    task = dict(DAILY, history=[
        {'date': _ms(2026, 9, 7, 10), 'value': 23.9, 'isDue': True, 'completed': False},
        {'date': _ms(2026, 9, 7, 22), 'value': 24.5, 'isDue': True, 'completed': True},
    ])
    new = pd.DataFrame(habitica.history_rows([task], 'daily'),
                       columns=habitica.HISTORY_COLUMNS)

    merged = habitica.merge_history(pd.DataFrame(columns=habitica.HISTORY_COLUMNS), new)

    assert len(merged) == 1
    assert bool(merged.iloc[0]['completed']) is True
    assert merged.iloc[0]['ts'].endswith('22:00:00')


TASKS = {
    'habits': [
        {'id': 'h-new', 'text': '筋トレ', 'up': True, 'down': False, 'value': 0.0},
        {'id': 'habit-1', 'text': '坐禅', 'up': True, 'down': False, 'value': 1.0},
        {'id': 'h-bad', 'text': 'やけ食い', 'up': False, 'down': True, 'value': 0.0},
    ],
    'dailys': [
        {'id': 'daily-1', 'text': '冷水シャワー', 'value': 26.9},
        {'id': 'd-new', 'text': '新しい日課', 'value': 0.0},
    ],
    'tags': [],
}

WEEKS = ['2026-W36', '2026-W37']


def _hist():
    rows = habitica.history_rows([HABIT], 'habit') + habitica.history_rows([DAILY], 'daily')
    rows += habitica.history_rows([{
        'id': 'h-bad', 'text': 'やけ食い',
        'history': [{'date': _ms(2026, 9, 7), 'value': -1.0,
                     'scoredUp': 0, 'scoredDown': 2}],
    }], 'habit')
    return habitica.merge_history(
        pd.DataFrame(columns=habitica.HISTORY_COLUMNS),
        pd.DataFrame(rows, columns=habitica.HISTORY_COLUMNS))


def test_一度も押していない習慣が0として表に出る():
    """history 起点にすると、これから形成する習慣ほど表から消える"""
    table = habitica.habit_table(_hist(), WEEKS, {}, TASKS['habits'], 'up')

    assert '筋トレ' in table.index          # history が1件も無い
    assert table.loc['筋トレ', '2026-W37'] == 0

    daily = habitica.daily_table(_hist(), WEEKS, TASKS['dailys'])
    assert '新しい日課' in daily.index
    assert daily.loc['新しい日課', '2026-W37'] == '-'


def test_減らす習慣はscored_downで数える():
    """up=False の Habit を scored_up で数えると常に0になる"""
    up = habitica.habit_table(_hist(), WEEKS, {}, TASKS['habits'], 'up')
    down = habitica.habit_table(_hist(), WEEKS, {}, TASKS['habits'], 'down')

    assert 'やけ食い' not in up.index       # 増やす表には出ない
    assert down.loc['やけ食い', '2026-W37'] == 2


def test_卒業タグの付いたタスクだけを除外する():
    tasks = dict(TASKS,
                 habits=[dict(TASKS['habits'][1], tags=['tag-grad'])] + TASKS['habits'][::2],
                 tags=[{'id': 'tag-grad', 'name': '卒業'}])
    assert habitica.graduated_ids(tasks) == {'habit-1'}

    # value が高くてもタグが無ければ除外しない（黙って外さない）
    assert habitica.graduated_ids(dict(TASKS, tags=[])) == set()
