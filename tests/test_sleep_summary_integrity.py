"""Fitbit睡眠サマリの内部矛盾（#65）判定ロジックの検証"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lib.analytics.sleep import (
    STAGE_GAP_THRESHOLD_MINUTES,
    calc_sleep_stats,
    flag_inconsistent,
    split_by_integrity,
)


def _row(**overrides):
    base = {
        'dateOfSleep': '2026-01-01',
        'type': 'stages',
        'deepMinutes': 60,
        'lightMinutes': 200,
        'remMinutes': 80,
        'minutesAsleep': 340,
        'wakeMinutes': 20,
        'timeInBed': 400,
        'efficiency': 85,
        'deepCount': 5,
        'lightCount': 10,
        'remCount': 5,
    }
    base.update(overrides)
    return base


def test_stagesで乖離60分以上はTrue():
    # deep+light+rem = 340, minutesAsleep = 280 -> 差60分
    df = pd.DataFrame([_row(minutesAsleep=280)])
    flag = flag_inconsistent(df)
    assert flag.iloc[0] == True


def test_stagesで乖離59分は境界でFalse():
    # deep+light+rem = 340, minutesAsleep = 281 -> 差59分
    df = pd.DataFrame([_row(minutesAsleep=281)])
    flag = flag_inconsistent(df)
    assert flag.iloc[0] == False


def test_classicタイプは常にFalse():
    df = pd.DataFrame([_row(type='classic', minutesAsleep=100)])
    flag = flag_inconsistent(df)
    assert flag.iloc[0] == False


def test_必要列が欠損していればFalse():
    df = pd.DataFrame([_row(minutesAsleep=280)]).drop(columns=['deepMinutes'])
    flag = flag_inconsistent(df)
    assert flag.iloc[0] == False


def test_split_by_integrityは元の行数を保つ():
    df = pd.DataFrame([
        _row(dateOfSleep='2026-01-01', minutesAsleep=340),  # 整合
        _row(dateOfSleep='2026-01-02', minutesAsleep=280),  # 乖離（差60分）
        _row(dateOfSleep='2026-01-03', minutesAsleep=100),  # 乖離（差240分）
    ])
    df_clean, df_inconsistent = split_by_integrity(df)
    assert len(df_clean) + len(df_inconsistent) == len(df)
    assert len(df_clean) == 1
    assert len(df_inconsistent) == 2


def test_calc_sleep_statsは乖離行をduration_efficiencyから除外しstagesには含める():
    df = pd.DataFrame([
        _row(dateOfSleep='2026-01-01', minutesAsleep=340, efficiency=90),  # 整合
        _row(dateOfSleep='2026-01-02', minutesAsleep=340, efficiency=88),  # 整合
        _row(dateOfSleep='2026-01-03', minutesAsleep=100, efficiency=40),  # 乖離（差240分）
    ])
    stats = calc_sleep_stats(df)

    assert stats['integrity']['total'] == 3
    assert stats['integrity']['excluded'] == 1
    assert stats['integrity']['threshold_minutes'] == STAGE_GAP_THRESHOLD_MINUTES
    assert 'fallback' not in stats['integrity']

    # duration/efficiencyは整合する2行のみから計算される（乖離行のefficiency=40, minutesAsleep=100は含まない）
    assert stats['duration']['mean_minutes'] == 340
    assert stats['efficiency']['mean'] == 89
    assert stats['efficiency']['min'] == 88

    # stagesは3行全部から計算される（乖離行のdeep/light/rem=60/200/80も含む）
    assert stats['stages']['deep_minutes'] == 60


def test_calc_sleep_statsは全行乖離でfallbackする():
    df = pd.DataFrame([
        _row(dateOfSleep='2026-01-01', minutesAsleep=100, efficiency=40),
        _row(dateOfSleep='2026-01-02', minutesAsleep=90, efficiency=35),
    ])
    stats = calc_sleep_stats(df)

    assert stats['integrity']['total'] == 2
    assert stats['integrity']['excluded'] == 2
    assert stats['integrity']['fallback'] is True
    # フォールバックでは全行から計算される（NaNを黙って返さない）
    assert stats['duration']['mean_minutes'] == 95
