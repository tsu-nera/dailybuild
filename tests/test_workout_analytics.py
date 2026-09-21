"""
lib.analytics.workout のテスト（Issue #174）

部位別セット数・種目別 e1RM・腹囲の週次推移が「欠測を捏造しない」方針を
守っているかを検査する。具体的には:
- 未マッピング種目を黙って集計から消さない
- 自重セット（weight_kg 空）を e1RM から除外する
- 記録の無い週を表から消さない
- 腹囲は前週の値で埋めない
"""

import pandas as pd
import pytest

from lib.analytics import workout


def make_workout_df(rows):
    """rows: [(start_dt_str, exercise_title, weight_kg, reps), ...]"""
    df = pd.DataFrame(rows, columns=['start_dt', 'exercise_title', 'weight_kg', 'reps'])
    df['start_dt'] = pd.to_datetime(df['start_dt'])
    return df


def test_weekly_muscle_sets_counts_by_mapped_muscle():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),  # 2026-W35
        ('2026-08-24 10:05', 'ベンチプレス (ダンベル)', 30, 10),
        ('2026-08-25 10:00', 'デッドリフト (ダンベル)', 40, 6),
    ])
    muscle_map = {'ベンチプレス (ダンベル)': 'chest', 'デッドリフト (ダンベル)': 'back'}
    week_labels = ['2026-W35']

    sets_table, unmapped = workout.weekly_muscle_sets(df, muscle_map, week_labels)

    assert sets_table.loc['2026-W35', 'chest'] == 2
    assert sets_table.loc['2026-W35', 'back'] == 1
    assert sets_table.loc['2026-W35', 'training_days'] == 2
    assert unmapped.empty


def test_weekly_muscle_sets_reports_unmapped_exercises_instead_of_dropping_them():
    df = make_workout_df([
        ('2026-08-24 10:00', '新しいマシン', 20, 10),
        ('2026-08-24 10:05', '新しいマシン', 20, 10),
    ])
    muscle_map = {}  # yaml に無い
    week_labels = ['2026-W35']

    sets_table, unmapped = workout.weekly_muscle_sets(df, muscle_map, week_labels)

    # 未マッピング種目は集計表のどの列にも現れないが、unmapped に必ず出る
    assert 'chest' not in sets_table.columns
    assert list(unmapped['exercise_title']) == ['新しいマシン']
    assert unmapped['sets'].iloc[0] == 2


def test_weekly_muscle_sets_keeps_weeks_with_no_training():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),  # 2026-W35 のみ記録あり
    ])
    muscle_map = {'ベンチプレス (ダンベル)': 'chest'}
    week_labels = ['2026-W34', '2026-W35', '2026-W36']

    sets_table, _ = workout.weekly_muscle_sets(df, muscle_map, week_labels)

    assert list(sets_table.index) == week_labels
    assert sets_table.loc['2026-W34', 'chest'] == 0
    assert sets_table.loc['2026-W36', 'chest'] == 0
    assert sets_table.loc['2026-W34', 'training_days'] == 0


def test_weekly_e1rm_uses_epley_formula_and_weekly_max():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),  # 40.0
        ('2026-08-25 10:00', 'ベンチプレス (ダンベル)', 32, 8),   # 32 * (1 + 8/30) = 40.53...
    ])
    week_labels = ['2026-W35']

    result = workout.weekly_e1rm(df, week_labels)

    assert result.loc['2026-W35', 'ベンチプレス (ダンベル)'] == pytest.approx(40.53, abs=0.01)


def test_weekly_e1rm_excludes_bodyweight_sets():
    df = make_workout_df([
        ('2026-08-24 10:00', 'プランク', None, 60),  # 自重
        ('2026-08-24 10:05', 'ベンチプレス (ダンベル)', 30, 10),
    ])
    week_labels = ['2026-W35']

    result = workout.weekly_e1rm(df, week_labels)

    assert 'プランク' not in result.columns
    assert result.loc['2026-W35', 'ベンチプレス (ダンベル)'] == pytest.approx(40.0)


def test_weekly_e1rm_omits_exercises_never_done_in_the_window():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),
    ])
    week_labels = ['2026-W35']

    result = workout.weekly_e1rm(df, week_labels)

    assert list(result.columns) == ['ベンチプレス (ダンベル)']


def test_weekly_waist_does_not_forward_fill_missing_weeks():
    measurements = pd.DataFrame({
        'date': pd.to_datetime(['2026-08-24', '2026-09-07']),
        'waist_cm': [75.0, 74.0],
    })
    week_labels = ['2026-W35', '2026-W36', '2026-W37']

    result = workout.weekly_waist(measurements, week_labels)

    assert result['2026-W35'] == 75.0
    assert pd.isna(result['2026-W36'])  # 測定なし。前週の75.0で埋めない
    assert result['2026-W37'] == 74.0


def test_weekly_waist_uses_last_measurement_when_multiple_in_the_same_week():
    measurements = pd.DataFrame({
        'date': pd.to_datetime(['2026-08-24', '2026-08-26']),
        'waist_cm': [75.0, 76.0],
    })
    week_labels = ['2026-W35']

    result = workout.weekly_waist(measurements, week_labels)

    assert result['2026-W35'] == 76.0


def test_recent_iso_weeks_returns_n_labels_ending_at_the_given_week():
    labels = workout.recent_iso_weeks(4, today=pd.Timestamp('2026-09-19'))  # 2026-W38
    assert labels == ['2026-W35', '2026-W36', '2026-W37', '2026-W38']


def test_load_muscle_mapping_reads_the_yaml(tmp_path):
    yaml_path = tmp_path / 'exercise_muscles.yaml'
    yaml_path.write_text(
        'exercises:\n'
        '  ベンチプレス (ダンベル):\n'
        '    muscle: chest\n'
    )
    mapping = workout.load_muscle_mapping(yaml_path)
    assert mapping == {'ベンチプレス (ダンベル)': 'chest'}


def test_load_weekly_set_targets_returns_empty_dict_without_weekly_sets_key(tmp_path):
    yaml_path = tmp_path / 'exercise_muscles.yaml'
    yaml_path.write_text(
        'exercises:\n'
        '  ベンチプレス (ダンベル):\n'
        '    muscle: chest\n'
    )
    targets = workout.load_weekly_set_targets(yaml_path)
    assert targets == {}


def test_load_weekly_set_targets_reads_target_as_int_and_drops_since(tmp_path):
    yaml_path = tmp_path / 'exercise_muscles.yaml'
    yaml_path.write_text(
        'weekly_sets:\n'
        '  chest: {target: 6, since: 2026-09-21}\n'
        '  legs: {target: 4, since: 2026-09-21}\n'
    )
    targets = workout.load_weekly_set_targets(yaml_path)
    assert targets == {'chest': 6, 'legs': 4}
    assert all(isinstance(v, int) for v in targets.values())


def test_weekly_set_progress_returns_actual_target_and_remaining():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),
        ('2026-08-24 10:05', 'ベンチプレス (ダンベル)', 30, 10),
    ])
    muscle_map = {'ベンチプレス (ダンベル)': 'chest'}
    week_labels = ['2026-W35']
    sets_table, _ = workout.weekly_muscle_sets(df, muscle_map, week_labels)

    rows = workout.weekly_set_progress(sets_table, '2026-W35', {'chest': 6})

    assert rows == [{'muscle': 'chest', 'label': '胸', 'actual': 2, 'target': 6, 'remaining': 4}]


def test_weekly_set_progress_remaining_does_not_go_negative_when_actual_exceeds_target():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),
        ('2026-08-24 10:05', 'ベンチプレス (ダンベル)', 30, 10),
        ('2026-08-24 10:10', 'ベンチプレス (ダンベル)', 30, 10),
    ])
    muscle_map = {'ベンチプレス (ダンベル)': 'chest'}
    week_labels = ['2026-W35']
    sets_table, _ = workout.weekly_muscle_sets(df, muscle_map, week_labels)

    rows = workout.weekly_set_progress(sets_table, '2026-W35', {'chest': 2})

    assert rows[0]['actual'] == 3
    assert rows[0]['remaining'] == 0


def test_weekly_set_progress_omits_muscles_not_in_targets():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),
        ('2026-08-25 10:00', 'デッドリフト (ダンベル)', 40, 6),
    ])
    muscle_map = {'ベンチプレス (ダンベル)': 'chest', 'デッドリフト (ダンベル)': 'back'}
    week_labels = ['2026-W35']
    sets_table, _ = workout.weekly_muscle_sets(df, muscle_map, week_labels)

    rows = workout.weekly_set_progress(sets_table, '2026-W35', {'chest': 6})

    assert [r['muscle'] for r in rows] == ['chest']


def test_weekly_set_progress_treats_missing_column_as_zero_actual():
    df = make_workout_df([
        ('2026-08-24 10:00', 'ベンチプレス (ダンベル)', 30, 10),
    ])
    muscle_map = {'ベンチプレス (ダンベル)': 'chest'}
    week_labels = ['2026-W35']
    sets_table, _ = workout.weekly_muscle_sets(df, muscle_map, week_labels)

    # sets_table に legs 列は無い（legs の種目が1件も無いため）
    rows = workout.weekly_set_progress(sets_table, '2026-W35', {'legs': 4})

    assert rows == [{'muscle': 'legs', 'label': '脚', 'actual': 0, 'target': 4, 'remaining': 4}]
