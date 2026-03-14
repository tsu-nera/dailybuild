#!/usr/bin/env python3
"""MoneyForward ME 月次家計簿分析スクリプト"""

import pandas as pd
from pathlib import Path

def analyze_monthly_budget(year: int, month: int):
    """指定月の家計簿を分析"""

    # データ読み込み
    data_path = Path(__file__).parent.parent / f"data/mf/収入・支出詳細_{year}.csv"
    df = pd.read_csv(data_path)

    # 日付をdatetime型に変換
    df['日付'] = pd.to_datetime(df['日付'])

    # 指定月のデータを抽出（計算対象=1のみ）
    df_month = df[
        (df['日付'].dt.year == year) &
        (df['日付'].dt.month == month) &
        (df['計算対象'] == 1)
    ].copy()

    print(f"\n{'='*60}")
    print(f"  {year}年{month}月 家計簿レビュー")
    print(f"{'='*60}\n")

    # 収支サマリー
    print("【収支サマリー】")
    income = df_month[df_month['金額（円）'] > 0]['金額（円）'].sum()
    expense = abs(df_month[df_month['金額（円）'] < 0]['金額（円）'].sum())
    balance = income - expense

    print(f"  収入:   ¥{income:,}")
    print(f"  支出:   ¥{expense:,}")
    print(f"  収支:   ¥{balance:,}")
    print(f"  貯蓄率: {(balance/income*100) if income > 0 else 0:.1f}%")

    # カテゴリ別支出（大項目）
    print(f"\n{'='*60}")
    print("【カテゴリ別支出（上位10項目）】")
    print(f"{'='*60}")

    category_expense = df_month[df_month['金額（円）'] < 0].groupby('大項目')['金額（円）'].sum().abs().sort_values(ascending=False)

    for i, (category, amount) in enumerate(category_expense.head(10).items(), 1):
        percentage = (amount / expense * 100) if expense > 0 else 0
        print(f"{i:2d}. {category:15s} ¥{amount:>8,.0f}  ({percentage:5.1f}%)")

    # 中項目別の詳細（上位10項目）
    print(f"\n{'='*60}")
    print("【中項目別支出（上位10項目）】")
    print(f"{'='*60}")

    subcategory_expense = df_month[df_month['金額（円）'] < 0].groupby(['大項目', '中項目'])['金額（円）'].sum().abs().sort_values(ascending=False)

    for i, ((cat, subcat), amount) in enumerate(subcategory_expense.head(10).items(), 1):
        percentage = (amount / expense * 100) if expense > 0 else 0
        print(f"{i:2d}. {cat} > {subcat:20s} ¥{amount:>8,.0f}  ({percentage:5.1f}%)")

    # よく使った店舗
    print(f"\n{'='*60}")
    print("【よく使った店舗（上位10店舗）】")
    print(f"{'='*60}")

    store_expense = df_month[df_month['金額（円）'] < 0].groupby('内容')['金額（円）'].sum().abs().sort_values(ascending=False)

    for i, (store, amount) in enumerate(store_expense.head(10).items(), 1):
        count = len(df_month[(df_month['内容'] == store) & (df_month['金額（円）'] < 0)])
        print(f"{i:2d}. {store:40s} ¥{amount:>8,.0f}  ({count}回)")

    # カード別利用額
    print(f"\n{'='*60}")
    print("【カード別利用額】")
    print(f"{'='*60}")

    card_expense = df_month[df_month['金額（円）'] < 0].groupby('保有金融機関')['金額（円）'].sum().abs().sort_values(ascending=False)

    for card, amount in card_expense.items():
        percentage = (amount / expense * 100) if expense > 0 else 0
        print(f"  {card:20s} ¥{amount:>8,.0f}  ({percentage:5.1f}%)")

    # サブスクリプション
    print(f"\n{'='*60}")
    print("【サブスクリプション】")
    print(f"{'='*60}")

    subscriptions = df_month[df_month['中項目'] == 'サブスクリプション']
    if len(subscriptions) > 0:
        sub_total = abs(subscriptions['金額（円）'].sum())
        print(f"  合計: ¥{sub_total:,}")
        print()
        for _, row in subscriptions.iterrows():
            print(f"  {row['内容']:30s} ¥{abs(row['金額（円）']):>6,.0f}")
    else:
        print("  サブスクリプション支出なし")

    # 特別な支出（高額取引）
    print(f"\n{'='*60}")
    print("【高額支出（10,000円以上）】")
    print(f"{'='*60}")

    large_expenses = df_month[df_month['金額（円）'] < -10000].sort_values('金額（円）')

    if len(large_expenses) > 0:
        for _, row in large_expenses.iterrows():
            print(f"  {row['日付'].strftime('%m/%d')} {row['内容']:30s} {row['大項目']:15s} ¥{abs(row['金額（円）']):>8,.0f}")
    else:
        print("  高額支出なし")

    print(f"\n{'='*60}\n")

if __name__ == "__main__":
    analyze_monthly_budget(2026, 1)
