#!/usr/bin/env python3
"""睡眠中の心拍数と血糖値の関係分析スクリプト"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np
from scipy import stats

# データ読み込み
print("データを読み込み中...")

# 睡眠データ
sleep_df = pd.read_csv('/home/tsu-nera/repo/dailybuild/data/fitbit/sleep.csv')

# 心拍数データ
hr_intraday_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/data/fitbit/heart_rate_intraday.csv',
    parse_dates=['datetime']
)

# CGMデータ
cgm_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/issues/008_cgm_hr/Clarity_エクスポート_2026-02-16_075029.csv',
    skiprows=range(1, 11)  # 2-11行目（設定情報）をスキップ
)

# 対象日のデータを取得
target_date = '2026-02-16'
sleep_record = sleep_df[sleep_df['dateOfSleep'] == target_date].iloc[0]

# 睡眠時間帯を取得
sleep_start = pd.to_datetime(sleep_record['startTime'])
sleep_end = pd.to_datetime(sleep_record['endTime'])

print(f"睡眠時間: {sleep_start.strftime('%Y-%m-%d %H:%M')} ～ {sleep_end.strftime('%Y-%m-%d %H:%M')}")

# CGMデータの前処理（EGVデータのみ抽出）
cgm_df = cgm_df[cgm_df['イベント タイプ'] == 'EGV'].copy()
cgm_df['timestamp'] = pd.to_datetime(cgm_df['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
cgm_df['glucose'] = pd.to_numeric(cgm_df['グルコース値 (mg/dL)'], errors='coerce')
cgm_df = cgm_df[['timestamp', 'glucose']].dropna()

# 睡眠時間帯のデータを抽出
sleep_hr = hr_intraday_df[
    (hr_intraday_df['datetime'] >= sleep_start) &
    (hr_intraday_df['datetime'] <= sleep_end)
].copy()

sleep_cgm = cgm_df[
    (cgm_df['timestamp'] >= sleep_start) &
    (cgm_df['timestamp'] <= sleep_end)
].copy()

print(f"心拍データ: {len(sleep_hr)}件")
print(f"血糖データ: {len(sleep_cgm)}件")

# データマージ（最近傍時刻でマッチング）
merged_data = pd.merge_asof(
    sleep_cgm.sort_values('timestamp'),
    sleep_hr.sort_values('datetime'),
    left_on='timestamp',
    right_on='datetime',
    direction='nearest',
    tolerance=pd.Timedelta('5min')
).dropna()

print(f"マージ後: {len(merged_data)}件")

# 統計分析
hr_mean = sleep_hr['heart_rate'].mean()
hr_std = sleep_hr['heart_rate'].std()
hr_min = sleep_hr['heart_rate'].min()
hr_max = sleep_hr['heart_rate'].max()

glucose_mean = sleep_cgm['glucose'].mean()
glucose_std = sleep_cgm['glucose'].std()
glucose_min = sleep_cgm['glucose'].min()
glucose_max = sleep_cgm['glucose'].max()

# 相関分析
correlation = merged_data['glucose'].corr(merged_data['heart_rate'])
slope, intercept, r_value, p_value, std_err = stats.linregress(
    merged_data['glucose'],
    merged_data['heart_rate']
)

print(f"\n=== 統計サマリー ===")
print(f"心拍数: 平均 {hr_mean:.1f} ± {hr_std:.1f} bpm (範囲: {hr_min}-{hr_max})")
print(f"血糖値: 平均 {glucose_mean:.1f} ± {glucose_std:.1f} mg/dL (範囲: {glucose_min:.0f}-{glucose_max:.0f})")
print(f"相関係数: {correlation:.3f} (p={p_value:.4f})")

# グラフ作成
plt.style.use('dark_background')
fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10))

# 1. 時系列グラフ（2軸）
color_hr = '#9370DB'
color_glucose = '#FF6B6B'

ax1_twin = ax1.twinx()

# 心拍数
ax1.plot(
    sleep_hr['datetime'],
    sleep_hr['heart_rate'],
    color=color_hr,
    linewidth=1.5,
    alpha=0.8,
    label='心拍数'
)
ax1.fill_between(
    sleep_hr['datetime'],
    sleep_hr['heart_rate'],
    alpha=0.3,
    color=color_hr
)

# 血糖値
ax1_twin.plot(
    sleep_cgm['timestamp'],
    sleep_cgm['glucose'],
    color=color_glucose,
    linewidth=2,
    alpha=0.8,
    label='血糖値'
)

# 軸設定
ax1.set_ylabel('心拍数 (bpm)', color=color_hr, fontsize=11, fontweight='bold')
ax1.tick_params(axis='y', labelcolor=color_hr)
ax1.set_ylim(hr_min - 5, hr_max + 5)

ax1_twin.set_ylabel('血糖値 (mg/dL)', color=color_glucose, fontsize=11, fontweight='bold')
ax1_twin.tick_params(axis='y', labelcolor=color_glucose)
ax1_twin.set_ylim(glucose_min - 10, glucose_max + 10)

ax1.set_title(
    f'睡眠中の心拍数と血糖値の推移\n{sleep_start.strftime("%m/%d %H:%M")}～{sleep_end.strftime("%H:%M")}',
    fontsize=14,
    pad=20,
    loc='left',
    fontweight='bold'
)

ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax1.xaxis.set_major_locator(mdates.HourLocator(interval=1))
ax1.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)
ax1.set_axisbelow(True)

# 凡例
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax1_twin.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', framealpha=0.8)

# 2. 散布図と回帰直線
ax2.scatter(
    merged_data['glucose'],
    merged_data['heart_rate'],
    alpha=0.6,
    s=50,
    color='#4ECDC4',
    edgecolors='white',
    linewidth=0.5
)

# 回帰直線
x_range = np.array([merged_data['glucose'].min(), merged_data['glucose'].max()])
y_range = slope * x_range + intercept
ax2.plot(x_range, y_range, 'r--', linewidth=2, alpha=0.8, label=f'回帰直線 (r={correlation:.3f})')

ax2.set_xlabel('血糖値 (mg/dL)', fontsize=11, fontweight='bold')
ax2.set_ylabel('心拍数 (bpm)', fontsize=11, fontweight='bold')
ax2.set_title('血糖値と心拍数の相関', fontsize=13, pad=15, loc='left', fontweight='bold')
ax2.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)
ax2.legend(loc='upper left', framealpha=0.8)

# 3. 血糖値変化率と心拍数
sleep_cgm['glucose_change'] = sleep_cgm['glucose'].diff()
merged_change = pd.merge_asof(
    sleep_cgm[['timestamp', 'glucose_change']].dropna().sort_values('timestamp'),
    sleep_hr.sort_values('datetime'),
    left_on='timestamp',
    right_on='datetime',
    direction='nearest',
    tolerance=pd.Timedelta('5min')
).dropna()

ax3.scatter(
    merged_change['glucose_change'],
    merged_change['heart_rate'],
    alpha=0.6,
    s=50,
    color='#FFB347',
    edgecolors='white',
    linewidth=0.5
)

# 変化率ゼロライン
ax3.axvline(x=0, color='gray', linestyle='--', linewidth=1, alpha=0.5)

ax3.set_xlabel('血糖値変化率 (mg/dL per 5min)', fontsize=11, fontweight='bold')
ax3.set_ylabel('心拍数 (bpm)', fontsize=11, fontweight='bold')
ax3.set_title('血糖値の変化率と心拍数の関係', fontsize=13, pad=15, loc='left', fontweight='bold')
ax3.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)

# 変化率の相関
if len(merged_change) > 0:
    change_corr = merged_change['glucose_change'].corr(merged_change['heart_rate'])
    ax3.text(
        0.02, 0.98,
        f'相関係数: {change_corr:.3f}',
        transform=ax3.transAxes,
        verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='black', alpha=0.7),
        fontsize=10
    )

# 背景色
for ax in [ax1, ax2, ax3]:
    ax.set_facecolor('#1a1a1a')
fig.patch.set_facecolor('#1a1a1a')

plt.tight_layout()
plt.savefig(
    '/home/tsu-nera/repo/dailybuild/issues/008_cgm_hr/cgm_hr_analysis.png',
    dpi=150,
    facecolor='#1a1a1a',
    edgecolor='none',
    bbox_inches='tight'
)
print("\nグラフを保存しました: cgm_hr_analysis.png")

# Markdownレポート作成
report = f"""# 睡眠中の心拍数と血糖値の関係分析

**対象日**: {target_date}
**睡眠時間**: {sleep_start.strftime('%Y-%m-%d %H:%M')} ～ {sleep_end.strftime('%Y-%m-%d %H:%M')}
**睡眠時間**: {sleep_record['minutesAsleep']:.0f}分 ({sleep_record['minutesAsleep']/60:.1f}時間)

## サマリー

### 心拍数
- **平均**: {hr_mean:.1f} ± {hr_std:.1f} bpm
- **範囲**: {hr_min} - {hr_max} bpm

### 血糖値
- **平均**: {glucose_mean:.1f} ± {glucose_std:.1f} mg/dL
- **範囲**: {glucose_min:.0f} - {glucose_max:.0f} mg/dL

### 相関分析
- **相関係数**: {correlation:.3f}
- **統計的有意性**: {'有意 (p < 0.05)' if p_value < 0.05 else '有意でない (p ≥ 0.05)'} (p = {p_value:.4f})
- **回帰式**: 心拍数 = {slope:.3f} × 血糖値 + {intercept:.3f}

## 分析結果

![睡眠中の心拍数と血糖値分析](cgm_hr_analysis.png)

### グラフの見方

1. **上段**: 時系列グラフ
   - 紫: 心拍数（左軸）
   - 赤: 血糖値（右軸）
   - 睡眠中の心拍数と血糖値の同時推移を表示

2. **中段**: 散布図と相関
   - 各点: 同時刻の心拍数と血糖値のペア
   - 赤破線: 回帰直線
   - 相関係数 r = {correlation:.3f}

3. **下段**: 血糖値変化率との関係
   - 血糖値が5分間でどれだけ変化したか（横軸）と心拍数（縦軸）の関係
   - 血糖値の急激な変動が心拍数に影響を与えているかを確認

## 解釈

"""

# 相関の強さに基づく解釈を追加
if abs(correlation) > 0.5:
    strength = "強い"
elif abs(correlation) > 0.3:
    strength = "中程度の"
else:
    strength = "弱い"

direction = "正の" if correlation > 0 else "負の"

report += f"""### 相関の強さ
{strength}{direction}相関が観察されました（r = {correlation:.3f}）。

"""

if correlation > 0.3:
    report += """- 血糖値が高いほど心拍数が高くなる傾向があります
- 血糖値の上昇が心血管系への負荷を示している可能性があります
"""
elif correlation < -0.3:
    report += """- 血糖値が高いほど心拍数が低くなる傾向があります
- この逆相関は興味深い観察結果です
"""
else:
    report += """- 血糖値と心拍数の間に明確な線形関係は見られませんでした
- 両者は主に独立した要因により変動している可能性があります
"""

report += f"""
### 統計的有意性
"""

if p_value < 0.05:
    report += f"""観察された相関は統計的に有意です（p = {p_value:.4f} < 0.05）。
これは偶然では説明できない関係性を示唆しています。
"""
else:
    report += f"""観察された相関は統計的に有意ではありません（p = {p_value:.4f} ≥ 0.05）。
サンプルサイズが小さいか、真の相関が存在しない可能性があります。
"""

report += f"""
## データ詳細

- **心拍データポイント数**: {len(sleep_hr)}件（1分間隔）
- **血糖データポイント数**: {len(sleep_cgm)}件（5分間隔）
- **マージ後データ数**: {len(merged_data)}件

## 参考情報

### 正常範囲
- **血糖値**:
  - 空腹時: 70-100 mg/dL
  - 睡眠中: 概ね100-140 mg/dL
- **睡眠中の心拍数**:
  - 通常、覚醒時の安静時心拍数より低い
  - 個人差が大きい

### 今後の分析の可能性
- より長期間のデータでパターンを確認
- 睡眠ステージ（深睡眠、REM等）との関連分析
- 食事内容・タイミングとの関連分析
- 血糖値スパイク時の心拍反応の詳細分析

---
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Script: analyze_sleep_cgm_hr.py*
"""

# レポート保存
with open('/home/tsu-nera/repo/dailybuild/issues/008_cgm_hr/ANALYSIS.md', 'w', encoding='utf-8') as f:
    f.write(report)

print("レポートを保存しました: ANALYSIS.md")

# CSVエクスポート（マージデータ）
merged_data.to_csv(
    '/home/tsu-nera/repo/dailybuild/issues/008_cgm_hr/merged_cgm_hr_data.csv',
    index=False
)
print("マージデータを保存しました: merged_cgm_hr_data.csv")

print("\n分析完了！")
