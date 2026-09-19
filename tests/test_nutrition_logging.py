"""
lib.analytics.nutrition_logging のテスト（Issue #25）

栄養記録の完全性は日単位で検証できないため、`config/nutrition_logging.yaml`
で期間ごとに記録モードを宣言する。モード適用は欠測化であって0埋めではない
（protein_only の日の calories を 0 にすると、直そうとしている誤表示その
ものになる）。yaml が無い/宣言の外側は安全側（unknown）に倒れることを守る。
"""

import numpy as np
import pandas as pd
import yaml

from lib.analytics.nutrition_logging import load_nutrition_with_logging_mode

NUTRITION_HEADER = 'date,calories,carbs,fat,fiber,protein,sodium,water\n'


def write_nutrition_csv(tmp_path, body):
    path = tmp_path / 'nutrition.csv'
    path.write_text(NUTRITION_HEADER + body)
    return path


def write_config(tmp_path, periods):
    path = tmp_path / 'nutrition_logging.yaml'
    path.write_text(yaml.safe_dump({'periods': periods}, allow_unicode=True))
    return path


def test_complete_mode_keeps_all_columns(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, '2026-01-01,2000,200,60,20,100,3000,2000\n')
    config_path = write_config(tmp_path, [
        {'from': '2026-01-01', 'to': '2026-01-31', 'mode': 'complete'},
    ])

    df = load_nutrition_with_logging_mode(csv_path, config_path)

    assert len(df) == 1
    row = df.iloc[0]
    assert row['calories'] == 2000
    assert row['carbs'] == 200
    assert row['protein'] == 100


def test_protein_only_blanks_non_protein_columns_not_zero(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, '2026-09-20,2000,200,60,20,100,3000,2000\n')
    config_path = write_config(tmp_path, [
        {'from': '2026-09-20', 'mode': 'protein_only'},
    ])

    df = load_nutrition_with_logging_mode(csv_path, config_path)

    assert len(df) == 1
    row = df.iloc[0]
    assert row['protein'] == 100
    # NaN であって 0 ではないこと（0 は「摂取ゼロ」という別の主張になる）
    for col in ['calories', 'carbs', 'fat', 'fiber', 'sodium', 'water']:
        assert np.isnan(row[col]), f'{col} should be NaN, got {row[col]}'
        assert row[col] != 0


def test_unknown_mode_drops_the_row(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, (
        '2025-12-01,2000,200,60,20,100,3000,2000\n'
        '2026-01-01,1800,180,50,15,90,2800,1800\n'
    ))
    config_path = write_config(tmp_path, [
        {'from': '2025-12-01', 'to': '2025-12-31', 'mode': 'unknown'},
        {'from': '2026-01-01', 'to': '2026-01-31', 'mode': 'complete'},
    ])

    df = load_nutrition_with_logging_mode(csv_path, config_path)

    assert len(df) == 1
    assert df.iloc[0]['date'] == pd.Timestamp('2026-01-01')


def test_dates_outside_declared_periods_are_unknown(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, (
        '2026-01-01,2000,200,60,20,100,3000,2000\n'
        '2026-06-01,1800,180,50,15,90,2800,1800\n'
    ))
    config_path = write_config(tmp_path, [
        {'from': '2026-01-01', 'to': '2026-01-31', 'mode': 'complete'},
    ])

    df = load_nutrition_with_logging_mode(csv_path, config_path)

    # 2026-06-01 は宣言の外側なので unknown 扱いで落ちる
    assert len(df) == 1
    assert df.iloc[0]['date'] == pd.Timestamp('2026-01-01')


def test_missing_config_file_means_all_unknown(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, '2026-01-01,2000,200,60,20,100,3000,2000\n')
    missing_config_path = tmp_path / 'does_not_exist.yaml'

    df = load_nutrition_with_logging_mode(csv_path, missing_config_path)

    assert len(df) == 0


def test_none_config_path_means_all_unknown(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, '2026-01-01,2000,200,60,20,100,3000,2000\n')

    df = load_nutrition_with_logging_mode(csv_path, None)

    assert len(df) == 0


def test_period_boundaries_are_inclusive(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, (
        '2026-01-01,2000,200,60,20,100,3000,2000\n'
        '2026-01-31,1900,190,55,18,95,2900,1900\n'
        '2026-02-01,1800,180,50,15,90,2800,1800\n'
    ))
    config_path = write_config(tmp_path, [
        {'from': '2026-01-01', 'to': '2026-01-31', 'mode': 'complete'},
    ])

    df = load_nutrition_with_logging_mode(csv_path, config_path)

    # from と to の日そのものは含まれ、範囲外の翌日は含まれない（unknown で落ちる）
    dates = set(df['date'])
    assert pd.Timestamp('2026-01-01') in dates
    assert pd.Timestamp('2026-01-31') in dates
    assert pd.Timestamp('2026-02-01') not in dates
    assert len(df) == 2


def test_open_ended_period_covers_present(tmp_path):
    csv_path = write_nutrition_csv(tmp_path, '2099-01-01,2000,200,60,20,100,3000,2000\n')
    config_path = write_config(tmp_path, [
        {'from': '2026-09-20', 'mode': 'protein_only'},
    ])

    df = load_nutrition_with_logging_mode(csv_path, config_path)

    assert len(df) == 1
    assert np.isnan(df.iloc[0]['calories'])
