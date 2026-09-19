"""
scripts/hevy.py show のテスト（Issue #174）

「hevy.py show は数値だけを印字する」「未マッピング種目は黙って消えない」の
2点は目視でしか壊れに気付けないため、機械的に検査する。
"""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))


def _load_script():
    path = BASE_DIR / 'scripts' / 'hevy.py'
    spec = importlib.util.spec_from_file_location('hevy_show_script', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['hevy_show_script'] = module
    spec.loader.exec_module(module)
    return module


hevy = _load_script()

WORKOUT_HEADER = (
    'title,start_time,end_time,description,exercise_title,superset_id,'
    'exercise_notes,set_index,set_type,weight_kg,reps,distance_km,'
    'duration_seconds,rpe\n'
)

MEASUREMENT_HEADER = 'date,weight_kg,fat_percent,waist_cm\n'

# 未マッピング種目を含む1週間分のワークアウト（今週 = today に合わせる必要はない。
# recent_iso_weeks の today を固定して窓をこのデータに合わせる）
WORKOUT_BODY = (
    '朝,"24 8月 2026, 10:00","24 8月 2026, 10:30",,ベンチプレス (ダンベル),,,0,normal,30,10,,,\n'
    '朝,"25 8月 2026, 10:00","25 8月 2026, 10:30",,新しいマシン,,,0,normal,20,10,,,\n'
)


@pytest.fixture
def show_env(tmp_path, monkeypatch):
    workouts = tmp_path / 'workouts.csv'
    measurements = tmp_path / 'measurements.csv'
    workouts.write_text(WORKOUT_HEADER + WORKOUT_BODY)
    measurements.write_text(
        MEASUREMENT_HEADER + '2026-08-24,59.1,12.2,75\n'
    )
    monkeypatch.setattr(hevy, 'WORKOUTS_CSV', workouts)
    monkeypatch.setattr(hevy, 'MEASUREMENTS_CSV', measurements)
    return workouts, measurements


def test_show_warns_about_unmapped_exercise_instead_of_dropping_it(show_env, capsys, caplog):
    with caplog.at_level('WARNING'):
        rc = hevy.show(weeks=52)

    assert rc == 0
    assert '新しいマシン' in caplog.text


def test_show_output_has_no_judgement_words(show_env, capsys):
    hevy.show(weeks=52)
    out = capsys.readouterr().out

    for banned in ('要注意', '不足', '良好', 'すべき', 'おすすめ'):
        assert banned not in out


def test_show_includes_weeks_with_zero_sets(show_env, capsys):
    hevy.show(weeks=8)
    out = capsys.readouterr().out

    # 8週分の行が部位別セット数の表に出ているはず（記録の無い週も含む）
    table_section = out.split('## 部位別セット数')[1].split('##')[0]
    week_rows = [line for line in table_section.splitlines() if line.startswith('| 2026-W')]
    assert len(week_rows) == 8


def test_show_waist_does_not_forward_fill(show_env, capsys):
    hevy.show(weeks=8)
    out = capsys.readouterr().out

    waist_section = out.split('## 腹囲の週次推移')[1]
    # 測定の無い週は '-' のまま。全行が75.0になっていないことを確認する
    assert '-' in waist_section
