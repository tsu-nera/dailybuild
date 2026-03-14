#!/usr/bin/env python3
"""食費分析スクリプト - 定期購入と日常食費を分離"""

import pandas as pd
from pathlib import Path

def analyze_food_expenses(year: int):
    """食費の詳細分析（定期購入を分離）"""

    data_path = Path(__file__).parent.parent / f"data/mf/収入・支出詳細_{year}.csv"
    df = pd.read_csv(data_path)
    df['日付'] = pd.to_datetime(df['日付'])

    # 食費のみ抽出
    food = df[
        (df['大項目'] == '食費') &
        (df['計算対象'] == 1)
    ].copy()

    print(f"\n{'='*60}")
    print(f"  {year}年 食費分析")
    print(f"{'='*60}\n")

    # 定期購入の識別（高額かつ頻度が低いもの）
    # マイプロテインなどの定期購入を抽出
    recurring_keywords = ['MYPROTEIN', 'マイプロテイン', 'iHerb', 'アイハーブ']

    food['is_recurring'] = food['内容'].str.upper().str.contains('|'.join([k.upper() for k in recurring_keywords]), na=False)

    # 金額が大きい食品購入も定期扱い（5,000円以上）
    food.loc[food['金額（円）'] < -5000, 'is_recurring'] = True

    recurring = food[food['is_recurring']]
    daily = food[~food['is_recurring']]

    print("【定期購入（5,000円以上 or サプリメント）】")
    if len(recurring) > 0:
        total_recurring = abs(recurring['金額（円）'].sum())
        print(f"  合計: ¥{total_recurring:,}")
        print()
        for _, row in recurring.sort_values('日付').iterrows():
            print(f"  {row['日付'].strftime('%m/%d')} {row['内容']:35s} {row['中項目']:15s} ¥{abs(row['金額（円）']):>7,.0f}")

        # 月数を計算（データの期間）
        months = (food['日付'].max() - food['日付'].min()).days / 30
        if months > 0:
            monthly_avg = total_recurring / max(months, 1)
            print(f"\n  月割り平均: ¥{monthly_avg:,.0f}/月")
    else:
        print("  該当なし")

    print(f"\n{'='*60}")
    print("【日常食費（通常の食材・外食）】")
    print(f"{'='*60}")

    # 月別集計
    daily['年月'] = daily['日付'].dt.to_period('M')
    monthly_daily = daily.groupby('年月')['金額（円）'].sum().abs()

    print("\n【月別日常食費】")
    for period, amount in monthly_daily.items():
        print(f"  {period}: ¥{amount:>6,.0f}")

    if len(monthly_daily) > 0:
        print(f"\n  月平均: ¥{monthly_daily.mean():>6,.0f}")
        print(f"  最大月: ¥{monthly_daily.max():>6,.0f}")
        print(f"  最小月: ¥{monthly_daily.min():>6,.0f}")

    # 中項目別（日常食費）
    print(f"\n【中項目別内訳（日常食費）】")
    subcategory = daily.groupby('中項目')['金額（円）'].sum().abs().sort_values(ascending=False)
    total_daily = subcategory.sum()

    for cat, amount in subcategory.items():
        percentage = (amount / total_daily * 100) if total_daily > 0 else 0
        print(f"  {cat:15s} ¥{amount:>7,.0f}  ({percentage:5.1f}%)")

    # 合計サマリー
    print(f"\n{'='*60}")
    print("【食費サマリー】")
    print(f"{'='*60}")

    total_food = abs(food['金額（円）'].sum())
    total_recurring_sum = abs(recurring['金額（円）'].sum()) if len(recurring) > 0 else 0
    total_daily_sum = abs(daily['金額（円）'].sum()) if len(daily) > 0 else 0

    # データ期間の月数
    months = len(food['日付'].dt.to_period('M').unique())

    print(f"\n  定期購入:   ¥{total_recurring_sum:>8,.0f}  (月割り: ¥{total_recurring_sum/max(months, 1):>6,.0f})")
    print(f"  日常食費:   ¥{total_daily_sum:>8,.0f}  (月平均: ¥{total_daily_sum/max(months, 1):>6,.0f})")
    print(f"  {'─'*40}")
    print(f"  合計:       ¥{total_food:>8,.0f}  (月平均: ¥{total_food/max(months, 1):>6,.0f})")

    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    analyze_food_expenses(2026)
