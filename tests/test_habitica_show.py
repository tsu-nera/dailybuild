"""habitica.py show の指標（達成率・IRT・期間キー）のテスト

habits_daily.csv の書き手は Toggl 起点の scripts/habits.py に移った
（tests/test_habits_daily.py）。こちらは Habitica の history を読む show だけを見る。
実 API は叩かない（fixture のみ）。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))


def _load_script():
    path = BASE_DIR / 'scripts' / 'habitica.py'
    spec = importlib.util.spec_from_file_location('habitica_script_show', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['habitica_script_show'] = module
    spec.loader.exec_module(module)
    return module


habitica = _load_script()


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


# --- show の3指標 ---

TODAY = pd.Timestamp('2026-09-06').date()   # 日曜 = 週の最終日


def _two_weeks():
    """2026-08-31(月) と 2026-09-01(火) は同じ ISO 週。前の週には行が無い"""
    hist = _history([
        {'date': '2026-08-31', 'ts': '2026-08-31T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 0, 'is_due': True,
         'completed': False, 'scored_up': None, 'scored_down': None},
    ])
    weeks = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'week', 2)
    cur = habitica._bucket(pd.Series(['2026-09-01']), 'week').iloc[0]
    return hist, weeks, cur, [w for w in weeks if w != cur][0]


def test_targetとphaseはyamlの値をそのまま出す():
    hist, weeks, cur, _ = _two_weeks()
    roster = {'筋トレ': {'target_per_week': 4, 'phase': 'acquisition'}}
    table = habitica.daily_table(hist, weeks, roster, TASKS['dailys'], TODAY)

    assert table.loc['筋トレ', 'target'] == 4
    assert table.loc['筋トレ', 'phase'] == 'acquisition'


def test_目標が無い習慣のtargetとphaseはハイフン():
    """CLI は判定しない。yaml が空なら空のまま出す"""
    hist, weeks, cur, _ = _two_weeks()
    table = habitica.daily_table(hist, weeks, {}, TASKS['dailys'], TODAY)

    assert table.loc['筋トレ', 'target'] == '-'
    assert table.loc['筋トレ', 'phase'] == '-'
    assert table.loc['筋トレ', 'clear'] == '-'


def test_行が1件も無い期間はclearの分母に入らない():
    """まだ作っていない期間を 0 として数えると欠測の捏造になる"""
    hist, weeks, cur, prev = _two_weeks()
    roster = {'筋トレ': {'target_per_week': 1}}
    table = habitica.daily_table(hist, weeks, roster, TASKS['dailys'], TODAY)

    # 2週の窓だが、行があるのは1週だけ
    assert table.loc['筋トレ', 'clear'] == '1/1'


def test_行があって未完了なら分母に入って分子に入らない():
    """行が無い(欠測)と、行があって未完了(不生起)は別物"""
    hist, weeks, cur, _ = _two_weeks()
    hist = hist[hist['date'] == '2026-09-01']  # completed=False の行だけ残す
    roster = {'筋トレ': {'target_per_week': 1}}
    table = habitica.daily_table(hist, weeks, roster, TASKS['dailys'], TODAY)

    assert table.loc['筋トレ', 'clear'] == '0/1'


def test_進行中の期間だけpartialになる():
    sunday = pd.Timestamp('2026-09-06').date()      # 日曜 = 週の最終日
    wednesday = pd.Timestamp('2026-09-09').date()
    assert habitica.is_partial('2026-W37', 'week', wednesday) is True
    assert habitica.is_partial('2026-W36', 'week', sunday) is False   # 当該週の最終日
    assert habitica.is_partial('2026-W35', 'week', wednesday) is False  # 過去の週
    assert habitica.is_partial('2026-09', 'month', wednesday) is True
    assert habitica.is_partial('2026-09', 'month',
                               pd.Timestamp('2026-09-30').date()) is False


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
    assert table.loc['瞑想', 'n'] == 4
    assert table.loc['瞑想', 'IRT median'] == '1d'
    assert table.loc['瞑想', 'IRT max'] == '3d'


def test_IRTは押した時刻に影響されない():
    """朝やって夜押した日があっても、日付が同じなら間隔は変わらない。

    Habitica の timestamp は押した時刻で、編集もできない。時刻を使うと
    「忙しい朝ほど押し忘れて遅くなる」偏りを間隔として拾ってしまう。
    """
    def _rows(times):
        return _history([
            {'date': d, 'ts': f'{d}T{t}:00', 'task_id': 'h1', 'task_type': 'habit',
             'task_name': '瞑想', 'value': 1, 'is_due': None, 'completed': None,
             'scored_up': 1, 'scored_down': 0}
            for d, t in zip(['2026-08-20', '2026-08-21', '2026-08-24'], times)])

    weeks = habitica.period_keys(pd.Timestamp('2026-09-06').date(), 'week', 4)
    morning = habitica.rhythm_table(_rows(['07:00', '07:05', '07:10']), weeks, TASKS['habits'])
    mixed = habitica.rhythm_table(_rows(['07:00', '23:50', '06:10']), weeks, TASKS['habits'])

    assert morning.loc['瞑想', 'IRT median'] == mixed.loc['瞑想', 'IRT median'] == '2d'
    assert morning.loc['瞑想', 'IRT max'] == mixed.loc['瞑想', 'IRT max'] == '3d'


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
    roster = {'筋トレ': {'target_per_week': 1}}
    table = habitica.daily_table(hist, periods, roster, TASKS['dailys'], TODAY, 'month')
    # 08 は1日実施でクリア、09 は進行中なので数えない
    assert table.loc['筋トレ', 'clear'] == '1/1'


def test_目標を満たした完了期間がclearに数えられる():
    """CLI がするのは実測と目標の比較まで。何期間そろえば昇格かは docs が持つ"""
    hist = _history([
        {'date': '2026-08-31', 'ts': '2026-08-31T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
        {'date': '2026-09-01', 'ts': '2026-09-01T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
    ])
    weeks = habitica.period_keys(TODAY, 'week', 2)
    cur = habitica._bucket(pd.Series(['2026-09-01']), 'week').iloc[0]
    roster = {'筋トレ': {'target_per_week': 2}}
    table = habitica.daily_table(hist, weeks, roster, TASKS['dailys'], TODAY)

    assert table.loc['筋トレ', 'clear'] == '1/1'    # 観測できた完了週1のうち1つクリア


def test_進行中の期間はclearに数えない():
    """経過日数ぶんしか無い期間を completed 扱いすると昇格が早まる"""
    hist = _history([
        {'date': '2026-09-07', 'ts': '2026-09-07T08:00:00', 'task_id': 'd1',
         'task_type': 'daily', 'task_name': '筋トレ', 'value': 1, 'is_due': True,
         'completed': True, 'scored_up': None, 'scored_down': None},
    ])
    wednesday = pd.Timestamp('2026-09-09').date()
    weeks = habitica.period_keys(wednesday, 'week', 1)
    roster = {'筋トレ': {'target_per_week': 1}}
    table = habitica.daily_table(hist, weeks, roster, TASKS['dailys'], wednesday)

    assert table.loc['筋トレ', 'clear'] == '0/0'      # 目標は満たしたが進行中なので数えない


