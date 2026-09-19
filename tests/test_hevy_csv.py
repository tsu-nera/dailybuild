"""
lib.hevy_csv のテスト（Issue #153）

Hevy の export はアプリの表示言語で月名が変わる（`13 Dec 2025` / `5 9月 2026`）。
月名を決め打ちすると新しい export で全体が落ち、逆に errors='coerce' で
逃がすと日付の無い行が黙って消える。どちらも「その週のセットが無かった」に
見えるので、両ロケールを解釈することと、解釈できない値で落ちることを守る。
"""

import pandas as pd
import pytest

from lib import hevy_csv

WORKOUT_HEADER = (
    'title,start_time,end_time,description,exercise_title,superset_id,'
    'exercise_notes,set_index,set_type,weight_kg,reps,distance_km,'
    'duration_seconds,rpe\n'
)

MEASUREMENT_HEADER = 'date,weight_kg,fat_percent,waist_cm\n'


def write_workouts(tmp_path, body):
    path = tmp_path / 'workouts.csv'
    path.write_text(WORKOUT_HEADER + body)
    return path


def write_measurements(tmp_path, body):
    path = tmp_path / 'measurements.csv'
    path.write_text(MEASUREMENT_HEADER + body)
    return path


def test_parses_english_month_names(tmp_path):
    path = write_workouts(tmp_path, (
        '朝,"13 Dec 2025, 15:11","13 Dec 2025, 15:49",,ベンチプレス,,,0,normal,30,10,,,\n'
    ))
    df = hevy_csv.parse_hevy_csv(path)
    assert df['start_dt'].iloc[0] == pd.Timestamp('2025-12-13 15:11')
    assert df['end_dt'].iloc[0] == pd.Timestamp('2025-12-13 15:49')


def test_parses_japanese_month_names(tmp_path):
    path = write_workouts(tmp_path, (
        '夜,"5 9月 2026, 20:39","5 9月 2026, 20:43",,ベンチプレス,,,0,normal,30,10,,,\n'
    ))
    df = hevy_csv.parse_hevy_csv(path)
    assert df['start_dt'].iloc[0] == pd.Timestamp('2026-09-05 20:39')


def test_parses_mixed_locales_in_one_column(tmp_path):
    # 言語を切り替えた前後の export が1つの列に混ざっても落とさない
    path = write_workouts(tmp_path, (
        '旧,"13 Dec 2025, 15:11","13 Dec 2025, 15:49",,ベンチプレス,,,0,normal,30,10,,,\n'
        '新,"5 9月 2026, 20:39","5 9月 2026, 20:43",,ベンチプレス,,,0,normal,30,10,,,\n'
        '新,"11 12月 2026, 07:05","11 12月 2026, 07:30",,デッドリフト,,,0,normal,40,6,,,\n'
    ))
    df = hevy_csv.parse_hevy_csv(path)
    assert list(df['start_dt']) == [
        pd.Timestamp('2025-12-13 15:11'),
        pd.Timestamp('2026-09-05 20:39'),
        pd.Timestamp('2026-12-11 07:05'),
    ]


def test_unparsable_date_raises_instead_of_dropping_the_row(tmp_path):
    # NaT で素通しすると、その行のセットが週次集計から黙って消える
    path = write_workouts(tmp_path, (
        '壊れ,"2026/09/05 20:39","2026/09/05 20:43",,ベンチプレス,,,0,normal,30,10,,,\n'
    ))
    with pytest.raises(ValueError, match='start_time'):
        hevy_csv.parse_hevy_csv(path)


def test_rpe_blank_is_missing_not_zero(tmp_path):
    # RPE は 2026-09-15 に有効化したばかりで、それ以前は全て空欄
    path = write_workouts(tmp_path, (
        '旧,"8 9月 2026, 20:39","8 9月 2026, 20:43",,ベンチプレス,,,0,normal,30,10,,,\n'
        '新,"16 9月 2026, 18:48","16 9月 2026, 18:59",,ベンチプレス,,,0,normal,30,10,,,6\n'
    ))
    df = hevy_csv.parse_hevy_csv(path)
    assert pd.isna(df['rpe'].iloc[0])
    assert df['rpe'].iloc[1] == 6


def test_measurements_keep_unmeasured_columns_empty(tmp_path):
    # 周囲径は測った日だけ入る。0 で埋めると「腹囲 0cm」を実測として集計する
    path = write_measurements(tmp_path, (
        '"18 9月 2026, 00:00",,16.8,\n'
        '"19 9月 2026, 00:00",61.9,15.7,74\n'
    ))
    df = hevy_csv.parse_hevy_measurements(path)
    assert pd.isna(df['weight_kg'].iloc[0])
    assert pd.isna(df['waist_cm'].iloc[0])
    assert df['waist_cm'].iloc[1] == 74.0


def test_measurements_are_sorted_by_date(tmp_path):
    path = write_measurements(tmp_path, (
        '"19 9月 2026, 00:00",61.9,15.7,74\n'
        '"11 12月 2025, 00:00",59.1,12.2,\n'
    ))
    df = hevy_csv.parse_hevy_measurements(path)
    assert [str(d) for d in df['date']] == ['2025-12-11', '2026-09-19']
