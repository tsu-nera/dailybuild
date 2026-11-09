"""
dashboard.py の CSV 出力のテスト

Grafana は表を読むだけで判定をしない。欠測の夜を0として足す、目標を書き換えても
表示が追随しない、といった壊れ方は例外にならず、画面上は正常な数字に見える。
"""

import csv
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import dashboard
import journal_skeleton as js
from lib.utils import private_data, targets

TODAY = dt.date(2026, 11, 7)  # 土曜（W45 は 11-02 から6日）。先週 W44 は 10-26〜11-01
MISSING = dt.date(2026, 11, 4)


def _targets_yaml(path, bed='22:30'):
    path.write_text(
        'targets:\n'
        f'  - {{key: bed_time, target: "{bed}"}}\n'
        '  - {key: rise_time, target: "05:45"}\n'
        '  - {key: sleep_debt_h, target: 0}\n')
    return path


@pytest.fixture
def fake(tmp_path, monkeypatch):
    """直近3週ぶんのフェイク sleep.csv（11-04 だけ欠測）と targets.yaml"""
    rows = []
    for i in range(21):
        day = TODAY - dt.timedelta(days=i)
        if day == MISSING:
            continue
        # 22:00 就寝 → 06:00 起床、睡眠 7.5h
        rows.append({
            'dateOfSleep': day.isoformat(),
            'startTime': f'{(day - dt.timedelta(days=1)).isoformat()}T22:00:00.000',
            'endTime': f'{day.isoformat()}T06:00:00.000',
            'minutesAsleep': 450, 'minutesAfterWakeup': 0, 'timeInBed': 480, 'isMainSleep': True,
        })
    sleep_csv = tmp_path / 'sleep.csv'
    pd.DataFrame(rows).to_csv(sleep_csv, index=False)
    monkeypatch.setattr(targets, 'TARGETS_YAML', _targets_yaml(tmp_path / 'targets.yaml'))
    monkeypatch.setattr(dashboard, 'collect_pipeline', lambda today: [])
    return {'sleep_csv': sleep_csv, 'tmp': tmp_path}


def _build(fake, weeks=3):
    return dashboard.build_tables(
        TODAY, weeks, sleep_csv=fake['sleep_csv'],
        steps_csv=fake['tmp'] / 'none.csv', workouts_csv=fake['tmp'] / 'none_workouts.csv')


def _read(path):
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def test_欠測の夜は空欄で合計に0として足されない(fake):
    t = _build(fake)
    out = fake['tmp'] / 'out'
    dashboard.write_csvs(t, out)

    row = next(r for r in _read(out / 'nights.csv') if r['date'] == MISSING.isoformat())
    assert row['sleep_h'] == '' and row['bed'] == '' and row['bed_late_min'] == ''

    cur = next(r for r in _read(out / 'weeks.csv') if r['week'] == '2026-W45')
    # 月〜土の6日のうち記録は5夜。欠測を0として足さず、目安も記録のある夜だけ
    assert cur['nights'] == '5'
    assert float(cur['total_h']) == 37.5
    assert float(cur['goal_h']) == 5 * 7


def test_bed_time_の目標を変えると_status_と_bed_late_min_が追随する(fake, monkeypatch):
    before = _build(fake)
    monkeypatch.setattr(targets, 'TARGETS_YAML', _targets_yaml(fake['tmp'] / 't2.yaml', bed='21:30'))
    after = _build(fake)

    assert before['status'][0]['bed_target'] == '22:30'
    assert after['status'][0]['bed_target'] == '21:30'
    pick = lambda t: next(n for n in t['nights'] if n['date'] == '2026-11-07')['bed_late_min']
    assert pick(before) == -30  # 22:00 就寝は 22:30 より30分早い
    assert pick(after) == 30


def test_freshness_は_collect_pipeline_の結果と一致する(fake, monkeypatch):
    rows = [
        {'name': 'A', 'last': pd.Timestamp('2026-11-06'), 'behind': 1, 'tolerance': 2,
         'ok': True, 'status': '', 'note': ''},
        {'name': 'B', 'last': None, 'behind': None, 'tolerance': 1,
         'ok': False, 'status': '', 'note': ''},
    ]
    monkeypatch.setattr(dashboard, 'collect_pipeline', lambda today: rows)
    out = fake['tmp'] / 'out'
    dashboard.write_csvs(_build(fake), out)
    got = _read(out / 'freshness.csv')
    assert got == [
        {'name': 'A', 'last': '2026-11-06', 'behind': '1', 'tolerance': '2'},
        {'name': 'B', 'last': '', 'behind': '', 'tolerance': '1'},
    ]


def test_collect_pipeline_は許容日数を返す():
    assert all('tolerance' in r for r in js.collect_pipeline(dt.date(2026, 11, 7)))


def test_current_は今週の行と先週の値_gap_h_を持つ(fake):
    t = _build(fake)
    weeks = {w['week']: w for w in t['weeks']}
    (cur,) = t['current']
    this, prev = weeks['2026-W45'], weeks['2026-W44']
    for k, v in this.items():
        assert cur[k] == v
    for k, v in prev.items():
        assert cur[f'prev_{k}'] == v
    assert cur['gap_h'] == round(this['total_h'] - this['goal_h'], 1)
    assert cur['gap_h'] == 2.5


def test_未マウントの_reports_へは書かずに落ちる(tmp_path, monkeypatch):
    repo = tmp_path / 'dailybuild'
    (repo / 'reports').mkdir(parents=True)
    monkeypatch.setattr(private_data, 'REPO_ROOT', repo)
    target = repo / 'reports' / 'dashboard'
    with pytest.raises(FileNotFoundError):
        dashboard.write_csvs({'status': []}, target)
    assert not target.exists()




def test_grafana_画面ごとの_json_は全クエリに_url_options_を持つ():
    """url_options が無いと画面側の Infinity が落ちて全パネルが空になる（API だけでは見つからない）"""
    for uid in ('goals', 'body', 'sleep', 'mind'):
        path = Path(__file__).parent.parent / f'scripts/ops/grafana/dashboards/{uid}.json'
        d = json.loads(path.read_text(encoding='utf-8'))
        assert d['uid'] == uid
        for p in d['panels']:
            for t in p.get('targets', []):
                assert t['url_options'] == {'method': 'GET'}, (uid, p['title'])


def test_daily_は記録の無い日を空欄にし0で埋めない(fake, monkeypatch):
    """体重計に乗らない日・運動しない日・栄養の 0 kcal 行を 0 として書くと推移に偽の谷ができる"""
    tmp = fake['tmp']
    pd.DataFrame([{'date': '2026-11-07', 'weight': 60.9, 'body_fat_rate': 13.6, 'body_fat_mass': 8.28,
                   'muscle_mass': 49.9, 'body_water_rate': 60.3}]).to_csv(tmp / 'inner.csv', index=False)
    pd.DataFrame([{'date': '2026-11-06', 'calories': 0, 'protein': 0.0},
                  {'date': '2026-11-07', 'calories': 1521, 'protein': 110.3}]).to_csv(tmp / 'nut.csv', index=False)
    monkeypatch.setattr(dashboard, 'collect_daily_detail', lambda hi, days: [])
    rows = dashboard.build_daily(
        dt.date(2026, 11, 3), TODAY, sleep_csv=fake['sleep_csv'], innerscan_csv=tmp / 'inner.csv',
        spo2_csv=tmp / 'none.csv', nutrition_csv=tmp / 'nut.csv', exercise_csv=tmp / 'none_ex.csv')
    by = {r['date']: r for r in rows}

    assert by['2026-11-07']['weight'] == 60.9
    assert by['2026-11-07']['protein_g'] == 110.3
    assert by['2026-11-06']['weight'] is None
    assert by['2026-11-06']['protein_g'] is None          # 0 kcal の行は記録なし
    assert by['2026-11-07']['cycling_min'] is None        # セッションの無い日
    assert by[MISSING.isoformat()]['bed_h'] is None       # 睡眠の欠測日
    assert by['2026-11-07']['bed_h'] == 22.0
    assert set(rows[0]) == set(dashboard.COLUMNS['daily'])
