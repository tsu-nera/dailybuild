#!/usr/bin/env python
# coding: utf-8
"""
RISE方式の重み付けテスト
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from src.lib.analytics.sleep.sleep_debt_clean import SleepDebtCalculator
from src.lib.analytics.sleep.sleep_need_estimator import SleepNeedEstimator

# サンプル睡眠データを作成
def create_sample_data():
    """過去14日間の睡眠データを作成"""
    dates = pd.date_range(end=datetime.now().date(), periods=14, freq='D')

    # 実際のレポートに近いデータ
    sleep_minutes = [
        7.5 * 60,  # 12/24
        6.0 * 60,  # 12/25
        6.7 * 60,  # 12/26
        6.4 * 60,  # 12/27
        6.0 * 60,  # 12/28
        6.6 * 60,  # 12/29
        7.2 * 60,  # 12/30
        7.5 * 60,  # 12/31
        6.0 * 60,  # 01/01
        6.7 * 60,  # 01/02
        6.4 * 60,  # 01/03
        6.0 * 60,  # 01/04
        6.6 * 60,  # 01/05
        4.8 * 60,  # 01/06 (昨晩)
    ]

    df = pd.DataFrame({
        'dateOfSleep': dates,
        'minutesAsleep': sleep_minutes
    })

    return df

def test_weights():
    """重み付けのテスト"""
    print("=" * 60)
    print("重み付けテスト")
    print("=" * 60)
    print()

    # テスト用のダミーデータ
    dummy_df = create_sample_data()
    calculator = SleepDebtCalculator(
        sleep_data=dummy_df,
        sleep_need_hours=8.2,
        window_days=14
    )

    # 各方式の重みを計算
    methods = ['linear', 'rise']

    for method in methods:
        weights = calculator._calculate_weights(14, method)
        print(f"■ {method.upper()} 方式")
        print(f"  合計重み: {weights.sum():.3f}")
        print(f"  最新日の重み: {weights[-1]:.3f} ({weights[-1] / weights.sum() * 100:.1f}%)")
        print(f"  残り13日の重み合計: {weights[:-1].sum():.3f} ({weights[:-1].sum() / weights.sum() * 100:.1f}%)")
        print()
        print(f"  重み配列:")
        for i, w in enumerate(weights, 1):
            print(f"    {i:2d}日前: {w:.4f}")
        print()

def test_sleep_debt():
    """睡眠負債計算のテスト"""
    print("=" * 60)
    print("睡眠負債計算テスト")
    print("=" * 60)
    print()

    # 実データを読み込み
    data_path = Path(__file__).parent.parent / 'data' / 'fitbit' / 'sleep.csv'

    if not data_path.exists():
        print("睡眠データが見つかりません")
        return

    sleep_df = pd.read_csv(data_path)
    sleep_df['dateOfSleep'] = pd.to_datetime(sleep_df['dateOfSleep'])

    # 最適睡眠時間を推定
    estimator = SleepNeedEstimator(
        sleep_data=sleep_df,
        lookback_days=365,
        rebound_top_percentile=4.0
    )

    result = estimator.estimate()
    sleep_need_hours = result.recommended_hours

    print(f"最適睡眠時間: {sleep_need_hours}h")
    print()

    # 各方式で睡眠負債を計算
    methods = ['linear', 'rise']

    for method in methods:
        calculator = SleepDebtCalculator(
            sleep_data=sleep_df,
            sleep_need_hours=sleep_need_hours,
            window_days=14
        )

        debt_result = calculator.calculate(weight_method=method)

        print(f"■ {method.upper()} 方式")
        print(f"  睡眠負債: {debt_result.sleep_debt_hours:.1f}h")
        print(f"  カテゴリ: {debt_result.category}")
        print(f"  回復日数: {debt_result.recovery_days_estimate}日")
        print(f"  平均睡眠: {debt_result.avg_sleep_hours:.1f}h")
        print(f"  昨晩の睡眠: {debt_result.actual_sleep_hours:.1f}h")
        print()

if __name__ == '__main__':
    test_weights()
    print()
    test_sleep_debt()
