#!/usr/bin/env python
# coding: utf-8
"""
睡眠負債分析のテストスクリプト（クリーン版）

最適睡眠時間の推定と睡眠負債の計算を分離した実装のテスト
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

import pandas as pd
from datetime import timedelta

from lib.analytics.sleep.sleep_need_estimator import (
    SleepNeedEstimator,
    print_sleep_need_report,
)
from lib.analytics.sleep.sleep_debt_clean import (
    SleepDebtCalculator,
    print_debt_report,
    plot_sleep_debt_trend,
)


def main():
    """メイン処理"""
    print("=" * 80)
    print("  睡眠負債分析テスト（クリーン版）")
    print("=" * 80)
    print()

    # ================================
    # データ読み込み
    # ================================
    data_dir = PROJECT_ROOT / 'data' / 'fitbit'

    print("データ読み込み中...")
    df_sleep = pd.read_csv(data_dir / 'sleep.csv')
    df_hrv = pd.read_csv(data_dir / 'hrv.csv')

    df_sleep['dateOfSleep'] = pd.to_datetime(df_sleep['dateOfSleep'])
    df_hrv['date'] = pd.to_datetime(df_hrv['date'])

    print(f"  睡眠データ: {len(df_sleep)}件")
    print(f"  HRVデータ: {len(df_hrv)}件")
    print()

    # ================================
    # ステップ1: 最適睡眠時間の推定
    # ================================
    print("=" * 80)
    print("ステップ1: 最適睡眠時間の推定")
    print("=" * 80)
    print()

    estimator = SleepNeedEstimator(
        sleep_data=df_sleep,
        hrv_data=df_hrv,
        lookback_days=90
    )

    sleep_need_result = estimator.estimate()
    print_sleep_need_report(sleep_need_result)
    print()

    # ================================
    # ステップ2: 睡眠負債の計算
    # ================================
    print("=" * 80)
    print("ステップ2: 睡眠負債の計算")
    print("=" * 80)
    print()

    calculator = SleepDebtCalculator(
        sleep_data=df_sleep,
        sleep_need_hours=sleep_need_result.recommended_hours,
        window_days=14
    )

    debt_result = calculator.calculate(weight_method='linear')
    print_debt_report(debt_result)
    print()

    # ================================
    # ステップ3: 履歴分析
    # ================================
    print("=" * 80)
    print("ステップ3: 過去30日間の履歴分析")
    print("=" * 80)
    print()

    end_date = df_sleep['dateOfSleep'].max()
    start_date = end_date - timedelta(days=29)

    history_df = calculator.get_history(
        start_date=start_date,
        end_date=end_date,
        weight_method='linear'
    )

    if len(history_df) > 0:
        print(f"データ点数: {len(history_df)}日")
        print()
        print("統計サマリー:")
        print(f"  平均睡眠負債: {history_df['sleep_debt_hours'].mean():.2f}h")
        print(f"  最大睡眠負債: {history_df['sleep_debt_hours'].max():.2f}h")
        print(f"  最小睡眠負債: {history_df['sleep_debt_hours'].min():.2f}h")
        print()

        # カテゴリ分布
        category_counts = history_df['category'].value_counts()
        print("カテゴリ分布:")
        for category in ['None', 'Low', 'Moderate', 'High']:
            count = category_counts.get(category, 0)
            percentage = count / len(history_df) * 100
            print(f"  {category:10s}: {count:2d}日 ({percentage:5.1f}%)")
        print()

    # ================================
    # ステップ4: 可視化
    # ================================
    print("=" * 80)
    print("ステップ4: 可視化の生成")
    print("=" * 80)
    print()

    output_dir = PROJECT_ROOT / 'issues' / '002_sleep_debt' / 'prototype_clean'
    output_dir.mkdir(parents=True, exist_ok=True)

    # トレンドグラフ
    print("トレンドグラフを生成中...")
    fig = plot_sleep_debt_trend(
        history_df=history_df,
        save_path=output_dir / 'sleep_debt_trend.png'
    )
    print(f"  ✓ 保存: {output_dir / 'sleep_debt_trend.png'}")
    import matplotlib.pyplot as plt
    plt.close(fig)

    # CSVに保存
    csv_path = output_dir / 'sleep_debt_history.csv'
    history_df.to_csv(csv_path, index=False)
    print(f"  ✓ 保存: {csv_path}")
    print()

    # ================================
    # サマリー
    # ================================
    print("=" * 80)
    print("分析完了サマリー")
    print("=" * 80)
    print()
    print(f"推奨睡眠時間: {sleep_need_result.recommended_hours:.1f}h")
    print(f"  信頼度: {sleep_need_result.confidence.upper()}")
    print(f"  習慣的睡眠: {sleep_need_result.habitual_hours:.1f}h")
    print(f"  潜在的負債: {sleep_need_result.potential_debt_hours:.1f}h/日")
    print()
    print(f"現在の睡眠負債: {debt_result.sleep_debt_hours:.1f}h ({debt_result.category})")
    print(f"  回復予測: {debt_result.recovery_days_estimate}日")
    print()

    if sleep_need_result.potential_debt_hours > 0.5:
        print("⚠ 推奨アクション:")
        print(f"  毎晩{sleep_need_result.recommended_hours:.0f}時間の睡眠を目標にしてください")
        print(f"  現在より約{sleep_need_result.potential_debt_hours * 60:.0f}分多く眠る必要があります")
    else:
        print("✓ 現在の睡眠習慣は適切です。維持してください。")

    print()
    print(f"出力ディレクトリ: {output_dir}")
    print()


if __name__ == '__main__':
    main()
