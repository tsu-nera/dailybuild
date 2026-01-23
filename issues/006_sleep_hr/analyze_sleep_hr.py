#!/usr/bin/env python3
"""睡眠中の心拍数分析スクリプト"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np

# データ読み込み
sleep_df = pd.read_csv('/home/tsu-nera/repo/dailybuild/data/fitbit/sleep.csv')
hr_intraday_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/data/fitbit/heart_rate_intraday.csv',
    parse_dates=['datetime']
)
hr_daily_df = pd.read_csv('/home/tsu-nera/repo/dailybuild/data/fitbit/heart_rate.csv')

# 対象日のデータを取得
target_date = '2026-01-23'
sleep_record = sleep_df[sleep_df['dateOfSleep'] == target_date].iloc[0]
resting_hr = int(hr_daily_df[hr_daily_df['date'] == target_date]['resting_heart_rate'].iloc[0])

# 睡眠時間帯を取得
sleep_start = pd.to_datetime(sleep_record['startTime'])
sleep_end = pd.to_datetime(sleep_record['endTime'])

print(f"睡眠時間: {sleep_start.strftime('%H:%M')} ～ {sleep_end.strftime('%H:%M')}")
print(f"安静時心拍数: {resting_hr} bpm")

# 睡眠時間帯の心拍数データを抽出
sleep_hr = hr_intraday_df[
    (hr_intraday_df['datetime'] >= sleep_start) &
    (hr_intraday_df['datetime'] <= sleep_end)
].copy()

# 統計値を計算
avg_hr = sleep_hr['heart_rate'].mean()
min_hr = sleep_hr['heart_rate'].min()
max_hr = sleep_hr['heart_rate'].max()

# 安静時心拍数との比較
above_resting = (sleep_hr['heart_rate'] > resting_hr).sum()
below_resting = (sleep_hr['heart_rate'] <= resting_hr).sum()
total = len(sleep_hr)

above_pct = (above_resting / total) * 100
below_pct = (below_resting / total) * 100

print(f"\n平均心拍数: {avg_hr:.0f} bpm")
print(f"最小: {min_hr} bpm, 最大: {max_hr} bpm")
print(f"安静時心拍数より高い: {above_pct:.0f}%")
print(f"安静時心拍数より低い: {below_pct:.0f}%")

# グラフ作成（Fitbitスタイル）
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(12, 6))

# 心拍数グラフ
ax.fill_between(
    sleep_hr['datetime'],
    sleep_hr['heart_rate'],
    alpha=0.6,
    color='#9370DB',
    linewidth=0
)
ax.plot(
    sleep_hr['datetime'],
    sleep_hr['heart_rate'],
    color='#9370DB',
    linewidth=1.5,
    alpha=0.9
)

# 安静時心拍数ライン
ax.axhline(
    y=resting_hr,
    color='gray',
    linestyle='--',
    linewidth=1,
    alpha=0.5,
    label=f'安静時の心拍数 ({resting_hr} bpm)'
)

# 軸設定
ax.set_ylim(40, max_hr + 10)
ax.set_ylabel('心拍数 (bpm)', fontsize=11)
ax.set_title(
    f'睡眠中の心拍数\n{sleep_start.strftime("%H:%M")}～{sleep_end.strftime("%H:%M")}',
    fontsize=14,
    pad=20,
    loc='left'
)

# X軸フォーマット
ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))

# グリッド
ax.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)
ax.set_axisbelow(True)

# 背景色
fig.patch.set_facecolor('#1a1a1a')
ax.set_facecolor('#1a1a1a')

plt.tight_layout()
plt.savefig(
    '/home/tsu-nera/repo/dailybuild/issues/006_sleep_hr/sleep_hr_chart.png',
    dpi=150,
    facecolor='#1a1a1a',
    edgecolor='none'
)
print("\nグラフを保存しました: sleep_hr_chart.png")

# Markdownレポート作成
report = f"""# 睡眠中の心拍数分析

**対象日**: {target_date}
**睡眠時間**: {sleep_start.strftime('%H:%M')} ～ {sleep_end.strftime('%H:%M')}

## サマリー

- **平均心拍数**: {avg_hr:.0f} bpm
- **最小値**: {min_hr} bpm
- **最大値**: {max_hr} bpm
- **安静時心拍数**: {resting_hr} bpm

## 心拍数推移

![睡眠中の心拍数グラフ](sleep_hr_chart.png)

## 安静時の心拍数との比較

睡眠中の心拍数が安静時心拍数（{resting_hr} bpm）と比較してどのくらい高い/低いかを示します。

- **高い**: {above_pct:.0f}% ({above_resting}/{total} 分)
- **低い**: {below_pct:.0f}% ({below_resting}/{total} 分)

## 解釈

ほとんどの人の場合、睡眠中の心拍数は、起きているときの安静時の心拍数よりも平均して低くなります。
睡眠中の心拍数が安静時心拍数より低い時間が {below_pct:.0f}% を占めており、良好な睡眠状態と言えます。

---
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

with open('/home/tsu-nera/repo/dailybuild/issues/006_sleep_hr/REPORT.md', 'w', encoding='utf-8') as f:
    f.write(report)

print("レポートを保存しました: REPORT.md")
