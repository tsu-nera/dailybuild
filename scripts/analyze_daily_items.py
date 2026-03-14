#!/usr/bin/env python3
"""日用品支出の分析スクリプト"""

import pandas as pd
from pathlib import Path

def analyze_daily_items(year: int):
    """日用品の支出パターンを分析"""

    data_path = Path(__file__).parent.parent / f"data/mf/収入・支出詳細_{year}.csv"
    df = pd.read_csv(data_path)
    df['日付'] = pd.to_datetime(df['日付'])

    # 日用品のみ抽出
    daily_items = df[
        (df['大項目'] == '日用品') &
        (df['計算対象'] == 1)
    ].copy()

    print(f"\n{'='*60}")
    print(f"  {year}年 日用品支出分析")
    print(f"{'='*60}\n")

    # 月別集計
    daily_items['年月'] = daily_items['日付'].dt.to_period('M')
    monthly = daily_items.groupby('年月')['金額（円）'].sum().abs()

    print("【月別日用品支出】")
    for period, amount in monthly.items():
        print(f"  {period}:  ¥{amount:>6,.0f}")

    if len(monthly) > 0:
        print(f"\n  月平均:  ¥{monthly.mean():>6,.0f}")
        print(f"  最大月:  ¥{monthly.max():>6,.0f}")
        print(f"  最小月:  ¥{monthly.min():>6,.0f}")
        print(f"  標準偏差: ¥{monthly.std():>6,.0f}")

    # 中項目別集計
    print(f"\n{'='*60}")
    print("【中項目別内訳】")
    print(f"{'='*60}")

    subcategory = daily_items.groupby('中項目')['金額（円）'].sum().abs().sort_values(ascending=False)
    total = subcategory.sum()

    for cat, amount in subcategory.items():
        percentage = (amount / total * 100) if total > 0 else 0
        count = len(daily_items[daily_items['中項目'] == cat])
        print(f"  {cat:20s} ¥{amount:>7,.0f}  ({percentage:5.1f}%)  {count}回")

    # 店舗別
    print(f"\n{'='*60}")
    print("【主な購入店舗】")
    print(f"{'='*60}")

    stores = daily_items.groupby('内容')['金額（円）'].agg(['sum', 'count']).sort_values('sum')
    stores['sum'] = stores['sum'].abs()

    for store, row in stores.tail(10).iterrows():
        print(f"  {store:40s} ¥{row['sum']:>6,.0f}  ({int(row['count'])}回)")

    # 高額支出（5,000円以上）
    print(f"\n{'='*60}")
    print("【高額支出（5,000円以上）】")
    print(f"{'='*60}")

    large = daily_items[daily_items['金額（円）'] < -5000].sort_values('日付')

    if len(large) > 0:
        for _, row in large.iterrows():
            print(f"  {row['日付'].strftime('%Y/%m/%d')} {row['内容']:30s} {row['中項目']:15s} ¥{abs(row['金額（円）']):>7,.0f}")
    else:
        print("  該当なし")

    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    analyze_daily_items(2026)
