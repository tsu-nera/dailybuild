"""
lib.exercise_source のテスト（Issue #96）

exercise.csv は Fitbit と Health Connect の両方からセッションが届き、
時間が重なるものがある。push とレポートの両方が同じ集合を見るように
重複解決をここへ寄せたので、その振る舞いだけをテストする。
"""

import datetime as dt

import pandas as pd

from lib import exercise_source

HEADER = (
    'id,start,end,duration_sec,exercise_type,display_name,platform,'
    'calories,distance_m,average_heart_rate\n'
)


def write_csv(tmp_path, monkeypatch, body):
    csv_path = tmp_path / 'exercise.csv'
    csv_path.write_text(HEADER + body)
    monkeypatch.setattr(exercise_source, 'EXERCISE_CSV_FILE', csv_path)
    return csv_path


def test_overlapping_sessions_drop_lower_priority_platform(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:40:00+09:00,2026-08-20 07:13:00+09:00,'
        '1980,WEIGHTS,リフティング,FITBIT,300,,120\n'
        '2222222222222222222,2026-08-20 06:45:00+09:00,2026-08-20 07:12:00+09:00,'
        '1620,STRENGTH_TRAINING,ウェイトトレーニング,HEALTH_CONNECT,280,,118\n'
    ))
    df = exercise_source.load_sessions()
    assert list(df['id']) == ['1111111111111111111']


def test_non_overlapping_sessions_are_both_kept_regardless_of_platform(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT,200,5000,110\n'
        '2222222222222222222,2026-08-20 18:00:00+09:00,2026-08-20 18:30:00+09:00,'
        '1800,BIKING,サイクリング,HEALTH_CONNECT,180,4000,105\n'
    ))
    df = exercise_source.load_sessions()
    assert len(df) == 2


def test_period_filter_is_inclusive_on_both_ends(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-19 06:00:00+09:00,2026-08-19 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT,200,5000,110\n'
        '2222222222222222222,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT,200,5000,110\n'
        '3333333333333333333,2026-08-21 06:00:00+09:00,2026-08-21 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT,200,5000,110\n'
    ))
    df = exercise_source.load_sessions(dt.date(2026, 8, 19), dt.date(2026, 8, 20))
    assert list(df['id']) == ['1111111111111111111', '2222222222222222222']


def test_id_is_returned_as_str_without_precision_loss(tmp_path, monkeypatch):
    # 19桁のidがfloat化すると精度が飛ぶ
    write_csv(tmp_path, monkeypatch, (
        '1234567890123456789,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT,200,5000,110\n'
    ))
    df = exercise_source.load_sessions()
    assert df['id'].iloc[0] == '1234567890123456789'
    assert isinstance(df['id'].iloc[0], str)


def test_duration_and_distance_are_converted_to_min_and_km(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT,200,5000,110\n'
    ))
    df = exercise_source.load_sessions()
    row = df.iloc[0]
    assert row['duration_min'] == 30
    assert row['distance_km'] == 5.0


def test_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(exercise_source, 'EXERCISE_CSV_FILE', tmp_path / 'nonexistent.csv')
    assert exercise_source.load_sessions() is None


def test_no_rows_in_period_returns_none(tmp_path, monkeypatch):
    write_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT,200,5000,110\n'
    ))
    df = exercise_source.load_sessions(dt.date(2026, 9, 1), dt.date(2026, 9, 2))
    assert df is None
