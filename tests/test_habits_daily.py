"""reports/habits_daily.csv の生成と show の3指標（達成率・時刻の変動性・IRT）のテスト

このリポジトリで最も危険な故障形態は「欠測の捏造」。history に行が無い日を
0埋め/False埋めしないこと、Habit の行に分母を捏造しないことを中心に検証する。
実 API は叩かない（fixture のみ）。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))


def _load_script():
    path = BASE_DIR / 'scripts' / 'habitica.py'
    spec = importlib.util.spec_from_file_location('habitica_script_daily', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['habitica_script_daily'] = module
    spec.loader.exec_module(module)
    return module


habitica = _load_script()

# monkeypatch される前の実体を控えておく（置き場の検証用）
REAL_HABITS_DAILY_CSV = habitica.HABITS_DAILY_CSV


def _history(rows):
    return pd.DataFrame(rows, columns=habitica.HISTORY_COLUMNS)


TASKS = {
    'habits': [
        {'id': 'h1', 'text': '瞑想', 'value': 1.0},
    ],
    'dailys': [
        {'id': 'd1', 'text': '筋トレ', 'value': 1.0},
    ],
    'tags': [],
}

ROSTER = {'瞑想': {'track': 'up'}, '筋トレ': {'target_per_week': 7}}


def test_historyに行が無い日について行が作られない():
    hist = _history([
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
    ])
    out = habitica.habits_daily(hist, ROSTER, TASKS)
    assert len(out) == 1
    assert (out['date'] == '2026-09-02').sum() == 0
    assert (out['is_due'] == False).sum() == 0  # noqa: E712 捏造行が無いこと


def test_Habit型の行はis_dueとcompletedが空():
    hist = _history([
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'h1',
         'task_type': 'habit', 'task_name': '瞑想', 'value': 1, 'is_due': None,
         'completed': None, 'scored_up': 1, 'scored_down': 0},
    ])
    out = habitica.habits_daily(hist, ROSTER, TASKS)
    assert len(out) == 1
    row = out.iloc[0]
    assert row['is_due'] is None or pd.isna(row['is_due'])
    assert row['completed'] is None or pd.isna(row['completed'])
    # 0 や False が入っていないこと
    assert row['is_due'] != 0
    assert row['completed'] != 0


def test_同日のcron行と完了行は最後のtsに畳まれる():
    hist = _history([
        {'date': '2026-09-01', 'ts': '2026-09-01T05:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 0, 'is_due': True,
         'completed': False, 'scored_up': None, 'scored_down': None},
        {'date': '2026-09-01', 'ts': '2026-09-01T20:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
    ])
    out = habitica.habits_daily(hist, ROSTER, TASKS)
    assert len(out) == 1
    assert out.iloc[0]['completed'] == True  # noqa: E712


def test_rosterに無い習慣は出力に現れない():
    hist = _history([
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'x1',
         'task_type': 'habit', 'task_name': '未登録', 'value': 1, 'is_due': None,
         'completed': None, 'scored_up': 1, 'scored_down': 0},
    ])
    out = habitica.habits_daily(hist, ROSTER, TASKS)
    assert out.empty


def test_habit列にはrosterの名前が入る_リネームされていても():
    tasks = {
        'habits': [{'id': 'h1', 'text': 'リネーム後', 'value': 1.0}],
        'dailys': [],
        'tags': [],
    }
    roster = {'リネーム後': {'track': 'up'}}
    hist = _history([
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'h1',
         'task_type': 'habit', 'task_name': 'リネーム前', 'value': 1, 'is_due': None,
         'completed': None, 'scored_up': 1, 'scored_down': 0},
    ])
    out = habitica.habits_daily(hist, roster, tasks)
    assert out.iloc[0]['habit'] == 'リネーム後'


def test_空入力では空のDataFrameを返す():
    out = habitica.habits_daily(_history([]), ROSTER, TASKS)
    assert out.empty
    assert list(out.columns) == habitica.HABITS_DAILY_COLUMNS


# --- show の3指標 ---

def test_daily_tableは週ごとの達成率を出しis_due合計0の週はハイフン():
    hist = _history([
        {'date': '2026-08-31', 'ts': '2026-08-31T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 0, 'is_due': True,
         'completed': False, 'scored_up': None, 'scored_down': None},
    ])
    weeks = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'week', 2)
    table = habitica.daily_table(hist, weeks, TASKS['dailys'])
    # is_due 2件・completed 1件 -> 1/2 (50%)
    cur_week = habitica._bucket(pd.Series(['2026-09-01']), 'week').iloc[0]
    assert '50%' in table.loc['筋トレ', cur_week]
    other_week = [w for w in weeks if w != cur_week][0]
    assert table.loc['筋トレ', other_week] == '-'


def test_minutes_since_day_startは深夜またぎの距離を圧縮する():
    ts_raw = pd.Series(['2026-09-01T23:50:00', '2026-09-02T00:10:00'])
    raw_minutes = pd.to_datetime(ts_raw).dt.hour * 60 + pd.to_datetime(ts_raw).dt.minute
    shifted = habitica.minutes_since_day_start(ts_raw, day_start_hour=5)
    assert raw_minutes.std() > shifted.std()


def test_変動性はdayStart起点で計算され深夜またぎで小さくなる():
    """23:50 と 00:10 が最大距離にならないこと。素の HH:MM 換算と突き合わせる。"""
    times = ['23:50', '00:10'] * 4          # 8点（VARIABILITY_MIN_POINTS ちょうど）
    rows = []
    for i, hhmm in enumerate(times):
        # 00:10 の押下は暦日が翌日になる
        day = 20 + i // 2 + (1 if hhmm == '00:10' else 0)
        date = f'2026-08-{day:02d}'
        rows.append({'date': date, 'ts': f'{date}T{hhmm}:00',
                     'task_id': 'h1', 'task_type': 'habit', 'task_name': '瞑想',
                     'value': 1, 'is_due': None, 'completed': None,
                     'scored_up': 1, 'scored_down': 0})
    hist = _history(rows)
    weeks = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'week', 4)
    table = habitica.rhythm_table(hist, weeks, TASKS['habits'])

    raw = pd.Series([r['ts'] for r in rows])
    raw_std = round((pd.to_datetime(raw).dt.hour * 60 + pd.to_datetime(raw).dt.minute).std())
    shifted_std = round(habitica.minutes_since_day_start(raw).std())
    assert table.loc['瞑想', 'n'] == 8
    assert table.loc['瞑想', 'time SD'] == f'{shifted_std}min'
    assert shifted_std < raw_std


def test_rhythm_tableは点数8未満で変動性がハイフン():
    rows = []
    for i in range(5):
        rows.append({'date': f'2026-08-{20+i:02d}', 'ts': f'2026-08-{20+i:02d}T08:00:00',
                     'task_id': 'h1', 'task_type': 'habit', 'task_name': '瞑想',
                     'value': 1, 'is_due': None, 'completed': None,
                     'scored_up': 1, 'scored_down': 0})
    hist = _history(rows)
    weeks = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'week', 4)
    table = habitica.rhythm_table(hist, weeks, TASKS['habits'])
    assert table.loc['瞑想', 'n'] == 5
    assert table.loc['瞑想', 'time SD'] == '-'


def test_rhythm_tableはIRTの中央値と最大を出す():
    # 間隔: 1日, 1日, 3日 -> 中央値1.0日、最大3.0日
    dates = ['2026-08-20', '2026-08-21', '2026-08-22', '2026-08-25']
    rows = []
    for i, d in enumerate(dates):
        rows.append({'date': d, 'ts': f'{d}T08:{10+i:02d}:00',
                     'task_id': 'h1', 'task_type': 'habit', 'task_name': '瞑想',
                     'value': 1, 'is_due': None, 'completed': None,
                     'scored_up': 1, 'scored_down': 0})
    hist = _history(rows)
    weeks = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'week', 4)
    table = habitica.rhythm_table(hist, weeks, TASKS['habits'])
    assert table.loc['瞑想', 'IRT median'] == '1.0d'
    assert table.loc['瞑想', 'IRT max'] == '3.0d'


def test_render_showの出力にstreakや連続日数が含まれない(monkeypatch, tmp_path):
    hist = _history([
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
    ])
    monkeypatch.setattr(habitica, 'CRON_LOG', tmp_path / 'cron_log.csv')
    config = {'habits': ROSTER}
    weeks = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'week', 2)
    out = habitica.render_show(hist, TASKS, config, weeks, pd.Timestamp('2026-09-06').date())
    assert 'streak' not in out
    assert '連続日数' not in out


# --- cmd_fetch ---

class FakeFetchClient:
    def __init__(self, tasks):
        self._tasks = tasks

    def get_tasks(self, kind):
        return self._tasks.get(kind, [])

    def get_tags(self):
        return self._tasks.get('tags', [])


def test_cmd_fetchはHABITS_DAILY_CSVをreports配下に書きdata配下ではない(monkeypatch, tmp_path):
    history_csv = tmp_path / 'data' / 'habitica' / 'history.csv'
    tasks_json = tmp_path / 'data' / 'habitica' / 'tasks.json'
    habits_daily_csv = tmp_path / 'reports' / 'habits_daily.csv'

    monkeypatch.setattr(habitica, 'HISTORY_CSV', history_csv)
    monkeypatch.setattr(habitica, 'TASKS_JSON', tasks_json)
    monkeypatch.setattr(habitica, 'HABITS_DAILY_CSV', habits_daily_csv)
    monkeypatch.setattr(habitica, 'require_private_path', lambda p: p)
    monkeypatch.setattr(habitica, 'load_config', lambda: {'habits': ROSTER})

    fake_client = FakeFetchClient(TASKS)
    monkeypatch.setattr(habitica.HabiticaClient, 'from_config', staticmethod(lambda _p: fake_client))

    rc = habitica.cmd_fetch(None)
    assert rc == 0
    assert habits_daily_csv.exists()
    # data/ 配下に派生を落としていないこと（あちらは取得の正本）
    assert not list((tmp_path / 'data').rglob('habits_daily.csv'))


def test_HABITS_DAILY_CSVはreports配下でありdata配下ではない():
    """monkeypatch されていない実定数で置き場を検証する（派生は data/ に置かない）"""
    parts = REAL_HABITS_DAILY_CSV.relative_to(BASE_DIR).parts
    assert parts[0] == 'reports'
    assert 'data' not in parts


# --- 期間キー（週 / 月） ---

def test_period_keysは月単位で年をまたいでも正しく遡る():
    keys = habitica.period_keys(pd.Timestamp('2026-01-15').date(), 'month', 3)
    assert keys == ['2025-11', '2025-12', '2026-01']


def test_period_daysは暦日数を返す():
    """被覆の分母。月ごとに違うので 7 固定にできない"""
    assert habitica.period_days('2026-W37', 'week') == 7
    assert habitica.period_days('2026-02', 'month') == 28
    assert habitica.period_days('2024-02', 'month') == 29
    assert habitica.period_days('2026-09', 'month') == 30


def test_月単位では暦月で畳まれる():
    hist = _history([
        {'date': '2026-08-31', 'ts': '2026-08-31T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 0, 'is_due': True,
         'completed': False, 'scored_up': None, 'scored_down': None},
    ])
    periods = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'month', 2)
    table = habitica.daily_table(hist, periods, TASKS['dailys'], 'month')
    assert table.loc['筋トレ', '2026-08'] == '1/1 (100%)'
    assert table.loc['筋トレ', '2026-09'] == '0/1 (0%)'
