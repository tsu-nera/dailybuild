"""reports/habits_daily.csv（Toggl Focus 起点）と habits.py show のテスト

最も危険な故障は「欠測の捏造」。プロジェクトが観測されていない日（created_at /
切替日より前、archived_at より後）に completed=False の行を作らないことを中心に見る。
実 API は叩かない（フェイクのエントリ・プロジェクト一覧のみ）。習慣名は架空。
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.habits.daily import HABITS_DAILY_COLUMNS, build_habits_daily  # noqa: E402
from lib.habits.show import bad_table, drift, good_table, render_show, week_keys  # noqa: E402
from lib.toggl import focus  # noqa: E402
from lib.toggl.store import CUTOVER_DATE  # noqa: E402


def _load_script(name, module_name):
    spec = importlib.util.spec_from_file_location(module_name, BASE_DIR / 'scripts' / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


habits_script = _load_script('habits.py', 'habits_script_daily')
habitica = _load_script('habitica.py', 'habitica_script_daily')

CLIENTS = {'good': '良い習慣', 'bad': '悪い習慣'}
TODAY = dt.date(2026, 11, 22)   # 日曜 = ISO 週 2026-W47 の最終日


def _project(pid, name, client='良い習慣', created='2026-11-16T00:00:00Z', archived=''):
    return {'id': pid, 'name': name, 'client_id': 1 if client == '良い習慣' else 2,
            'client_name': client, 'created_at': created, 'archived_at': archived}


def _projects(*rows):
    df = pd.DataFrame(list(rows), columns=focus.PROJECT_COLUMNS)
    df['client_id'] = df['client_id'].astype('Int64')
    return df


def _entries(*rows):
    """(project_id, start JST naive)。focus_entries.csv と同じ形"""
    return pd.DataFrame([{'id': i, 'project_id': pid, 'start': start}
                         for i, (pid, start) in enumerate(rows)])


def _rows(out, habit):
    return out[out['habit'] == habit].set_index('date')['completed']


# --- 行を作る範囲 ---

def test_created_atより前とarchived_atより後の日には行が無い():
    projects = _projects(_project(1, '架空A', created='2026-11-17T03:00:00Z',
                                  archived='2026-11-20T03:00:00Z'))
    out = build_habits_daily(_entries(), projects, CLIENTS, TODAY)
    days = _rows(out, '架空A')
    assert list(days.index) == ['2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20']
    assert not days.any()   # 範囲内でエントリが無い日は False


def test_範囲内でエントリがある日はTrueで無い日はFalse():
    projects = _projects(_project(1, '架空A', created='2026-11-20T00:00:00Z'))
    out = build_habits_daily(_entries((1, '2026-11-21 07:30:00')), projects, CLIENTS, TODAY)
    assert _rows(out, '架空A').to_dict() == {
        '2026-11-20': False, '2026-11-21': True, '2026-11-22': False}


def test_アーカイブ済みのアーカイブ前のエントリはTrueで残る():
    projects = _projects(_project(1, '架空A', created='2026-11-16T00:00:00Z',
                                  archived='2026-11-19T00:00:00Z'))
    out = build_habits_daily(_entries((1, '2026-11-17 21:00:00')), projects, CLIENTS, TODAY)
    days = _rows(out, '架空A')
    assert days['2026-11-17'] == True  # noqa: E712
    assert days.index.max() == '2026-11-19'


def test_created_atが切替日より前なら起点は切替日():
    """移行済みプロジェクトの created_at は Track からの移行時刻。切替日前の Focus は未観測"""
    projects = _projects(_project(1, '架空A', created='2026-01-13T23:18:27Z'))
    out = build_habits_daily(_entries(), projects, CLIENTS, dt.date(2026, 10, 29))
    assert out['date'].min() == CUTOVER_DATE.isoformat()
    assert len(out) == 3


def test_created_atは_JSTの暦日で起点になる():
    """UTC では前日・JST では当日（15:00Z 以降は JST の翌日）"""
    projects = _projects(_project(1, '架空A', created='2026-11-19T15:30:00Z'))
    out = build_habits_daily(_entries(), projects, CLIENTS, TODAY)
    assert out['date'].min() == '2026-11-20'


def test_対象外のクライアントのプロジェクトは出ない():
    projects = _projects(_project(1, '架空A'), _project(2, '架空仕事', client='仕事'),
                         _project(3, '架空B', client='悪い習慣'))
    out = build_habits_daily(_entries((2, '2026-11-18 10:00:00')), projects, CLIENTS, TODAY)
    assert set(out['habit']) == {'架空A', '架空B'}


def test_対応はproject_idで_habit列は現在のプロジェクト名():
    projects = _projects(_project(1, '改名後', created='2026-11-21T00:00:00Z'))
    entries = pd.DataFrame([{'id': 1, 'project_id': 1, 'start': '2026-11-21 08:00:00',
                             'project_name': '改名前'}])
    out = build_habits_daily(entries, projects, CLIENTS, TODAY)
    assert set(out['habit']) == {'改名後'}
    assert _rows(out, '改名後')['2026-11-21'] == True  # noqa: E712


def test_列とtask_typeとis_due():
    projects = _projects(_project(1, '架空A', created='2026-11-22T00:00:00Z'))
    out = build_habits_daily(_entries(), projects, CLIENTS, TODAY)
    assert list(out.columns) == HABITS_DAILY_COLUMNS
    assert (out['task_type'] == 'toggl').all()
    assert out['is_due'].isna().all()


# --- build（CSV の全上書きと冪等性） ---

@pytest.fixture
def build_env(monkeypatch, tmp_path):
    entries_csv = tmp_path / 'focus_entries.csv'
    projects_csv = tmp_path / 'focus_projects.csv'
    daily_csv = tmp_path / 'reports' / 'habits_daily.csv'
    _entries((1, '2026-11-18 07:00:00'), (2, '2026-11-20 23:00:00')).to_csv(entries_csv, index=False)
    focus.save_projects(_projects(_project(1, '架空A'), _project(2, '架空B', client='悪い習慣')),
                        projects_csv)
    monkeypatch.setattr(habits_script.store, 'FOCUS_CSV_FILE', entries_csv)
    monkeypatch.setattr(focus, 'PROJECTS_CSV_FILE', projects_csv)
    monkeypatch.setattr(habits_script, 'HABITS_DAILY_CSV', daily_csv)
    monkeypatch.setattr(habits_script, 'require_private_path', lambda p: p)
    monkeypatch.setattr(habits_script, 'today', lambda: TODAY)
    return daily_csv


def test_buildを2回実行しても結果が同じ(build_env):
    assert habits_script.cmd_build(None) == 0
    first = build_env.read_bytes()
    assert habits_script.cmd_build(None) == 0
    assert build_env.read_bytes() == first
    df = pd.read_csv(build_env)
    assert len(df) == 14  # 2習慣 × 2026-11-16〜22


# --- show ---

def _daily(*rows):
    return pd.DataFrame([{'date': d, 'habit': h, 'task_type': 'toggl', 'is_due': None,
                          'completed': c} for d, h, c in rows], columns=HABITS_DAILY_COLUMNS)


def _week(habit, start, done_days):
    first = dt.date.fromisoformat(start)
    return [((first + dt.timedelta(days=i)).isoformat(), habit, i in done_days) for i in range(7)]


def test_悪い習慣は週ごとに7日中何日で出る():
    daily = _daily(*_week('架空B', '2026-11-09', {0, 3}), *_week('架空B', '2026-11-16', {6}))
    table = bad_table(daily, ['架空B'], week_keys(TODAY, 3))
    assert table.loc['架空B'].tolist() == ['-', '2/7', '1/7']   # 行が無い週は欠測の -


def test_良い習慣は目標以上の週に印が付きclearを数える():
    daily = _daily(*_week('架空A', '2026-11-09', {0, 1, 2}), *_week('架空A', '2026-11-16', {0}))
    table = good_table(daily, ['架空A'], {'架空A': {'target_per_week': 3}},
                       week_keys(TODAY, 2), TODAY)
    assert table.loc['架空A', '2026-W46'] == '3/7*'
    assert table.loc['架空A', '2026-W47'] == '1/7'
    assert table.loc['架空A', 'clear'] == '1/2'


def test_アーカイブ済みの習慣はshowの表から外れる():
    projects = _projects(_project(1, '架空A'), _project(2, '架空済', archived='2026-11-18T00:00:00Z'))
    daily = _daily(*_week('架空A', '2026-11-16', {0}), ('2026-11-16', '架空済', True))
    out = render_show(daily, projects, CLIENTS, {'架空A': {'target_per_week': 1}}, TODAY, 2)
    assert '架空A' in out
    assert '架空済' not in out


def test_ずれa_目標の無い良い習慣():
    projects = _projects(_project(1, '架空A'), _project(2, '架空B', client='悪い習慣'))
    assert drift(projects, CLIENTS, {}) == (['架空A'], [])


def test_ずれb_yamlにあって良い習慣のアーカイブされていないプロジェクトに無い名前():
    projects = _projects(_project(1, '架空A'), _project(2, '架空済', archived='2026-11-18T00:00:00Z'))
    roster = {'架空A': {'target_per_week': 1}, '架空済': {'target_per_week': 1},
              '架空消': {'target_per_week': 2}}
    assert drift(projects, CLIENTS, roster) == ([], ['架空消', '架空済'])


@pytest.mark.parametrize('roster, name', [
    ({}, '架空A'),                                                           # (a)
    ({'架空A': {'target_per_week': 1}, '架空消': {'target_per_week': 1}}, '架空消'),  # (b)
])
def test_ずれがあるとshowは習慣名を出して非ゼロ(build_env, monkeypatch, capsys, roster, name):
    habits_script.cmd_build(None)
    monkeypatch.setattr(habits_script, 'load_roster', lambda: roster)
    rc = habits_script.cmd_show(type('Args', (), {'weeks': 2})())
    assert rc != 0
    assert name in capsys.readouterr().err


def test_ずれが無ければshowは0(build_env, monkeypatch):
    habits_script.cmd_build(None)
    monkeypatch.setattr(habits_script, 'load_roster', lambda: {'架空A': {'target_per_week': 1}})
    assert habits_script.cmd_show(type('Args', (), {'weeks': 2})()) == 0


# --- 書き手は1本（habitica.py fetch は書かない） ---

class FakeFetchClient:
    def get_tasks(self, kind):
        return [{'id': 'd1', 'text': '架空D', 'value': 1.0, 'history': []}] if kind == 'dailys' else []

    def get_tags(self):
        return []


def test_habitica_fetchはhabits_daily_csvを書かない(monkeypatch, tmp_path):
    monkeypatch.setattr(habitica, 'HISTORY_CSV', tmp_path / 'data' / 'habitica' / 'history.csv')
    monkeypatch.setattr(habitica, 'TASKS_JSON', tmp_path / 'data' / 'habitica' / 'tasks.json')
    monkeypatch.setattr(habitica, 'require_private_path', lambda p: p)
    monkeypatch.setattr(habitica.HabiticaClient, 'from_env', staticmethod(FakeFetchClient))
    (tmp_path / 'data' / 'habitica').mkdir(parents=True)

    assert habitica.cmd_fetch(None) == 0
    assert not list(tmp_path.rglob('habits_daily.csv'))
    assert not hasattr(habitica, 'HABITS_DAILY_CSV')


def test_HABITS_DAILY_CSVはreports配下でありdata配下ではない():
    parts = habits_script.HABITS_DAILY_CSV.relative_to(BASE_DIR).parts
    assert parts[0] == 'reports'
    assert 'data' not in parts


# --- focus_projects.csv ---

def test_プロジェクト一覧は通常分とアーカイブ済みの両方を引く(monkeypatch):
    calls = []

    def fake_get(token, path, params):
        calls.append(params.get('archived'))
        data = ([{'id': 2, 'name': '架空済', 'client': {'id': 1, 'name': '良い習慣'},
                  'created_at': 'x', 'archived_at': '2026-11-18T00:00:00Z'}]
                if params.get('archived') == 'true' else
                [{'id': 1, 'name': '架空A', 'client': {'id': 1, 'name': '良い習慣'},
                  'created_at': 'x', 'archived_at': None}])
        return type('R', (), {'json': lambda self: {'data': data}})()

    monkeypatch.setattr(focus, '_get', fake_get)
    ws = focus.Workspace('t', 'o', 'w')
    df = focus.build_projects_dataframe(focus.fetch_project_records(ws))
    assert sorted(calls, key=str) == [None, 'true']
    assert df['id'].tolist() == [1, 2]
    assert df['archived_at'].tolist() == ['', '2026-11-18T00:00:00Z']
    assert focus.client_id_by_name(df, '良い習慣') == 1
    assert focus.client_id_by_name(df, '悪い習慣') is None
