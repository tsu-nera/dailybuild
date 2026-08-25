#!/usr/bin/env python
# coding: utf-8
"""
Fitbit睡眠サマリの内部矛盾を検出するモジュール

Fitbit APIの睡眠レスポンスには、`deep+light+rem`（ステージ内訳の合計）と
`minutesAsleep`（サマリ値）が大きく乖離するレコードが混在する
（`type=stages` 1,979行中119行、6.0%。乖離量の中央値201分）。

`sleep_levels.csv` の生タイムライン（isShort=Falseのみ）と突き合わせた結果、
壊れているのは `minutesAsleep` と `efficiency` の側であり、ステージ内訳
（deep/light/rem）は生データと整合していることが分かっている
（乖離行での生タイムラインとの差の中央値: minutesAsleepが230分、
ステージ合計が31.5分）。詳細は GitHub Issue #65 を参照。

判定は読み出し時に計算する。Fitbitは過去の値を遡って書き換えるため
（#64参照）、乖離行の集合は再取得のたびに変わりうる。CSVに列として
保存すると陳腐化するので保存しない。
"""

import pandas as pd

# 乖離判定の閾値（分）。正常行では生タイムラインとの差が22分程度に収まる一方、
# 乖離行の中央値は201分と桁違いに大きいため、両者を明確に分離できる値として60分を採用。
STAGE_GAP_THRESHOLD_MINUTES = 60

_REQUIRED_COLUMNS = ['deepMinutes', 'lightMinutes', 'remMinutes', 'minutesAsleep']


def flag_inconsistent(df):
    """
    サマリとステージ内訳が内部矛盾しているレコードを判定する

    `type == 'stages'` の行のみを評価対象とし、`deepMinutes + lightMinutes +
    remMinutes` と `minutesAsleep` の差が `STAGE_GAP_THRESHOLD_MINUTES` 分以上
    ある行を True とする。`type` が 'stages' でない行、必要な列が欠損している
    行は False を返す。

    Args:
        df: sleep.csv（または type=stages の部分集合）を読み込んだDataFrame

    Returns:
        pd.Series: dfと同じindexを持つbool Series
    """
    result = pd.Series(False, index=df.index)

    if 'type' not in df.columns:
        return result

    is_stages = df['type'] == 'stages'
    if not is_stages.any():
        return result

    missing_cols = [col for col in _REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        return result

    stage_sum = df['deepMinutes'] + df['lightMinutes'] + df['remMinutes']
    gap = (stage_sum - df['minutesAsleep']).abs()

    # 必要列のいずれかがNaNの行はFalseのまま（gapもNaNになりTrueとの比較でFalseになる）
    result[is_stages] = gap[is_stages] >= STAGE_GAP_THRESHOLD_MINUTES

    return result


def split_by_integrity(df):
    """
    dfを整合行と乖離行に分割する

    Args:
        df: sleep.csv（または type=stages の部分集合）を読み込んだDataFrame

    Returns:
        tuple[pd.DataFrame, pd.DataFrame]: (df_clean, df_inconsistent)
    """
    flag = flag_inconsistent(df)
    return df[~flag], df[flag]
