#!/usr/bin/env python3
"""24時間CGM血糖値と心拍数の相関分析スクリプト（複数日）"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np
from scipy import stats

OUTPUT_DIR = '/home/tsu-nera/repo/dailybuild/issues/009_cgm_hr_24h'

# データ読み込み
print("データを読み込み中...")

hr_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/data/fitbit/heart_rate_intraday.csv',
    parse_dates=['datetime']
)

cgm_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/data/dexcom.csv',
    skiprows=range(1, 11)
)

# CGMデータ前処理（EGVのみ）
cgm_df = cgm_df[cgm_df['イベント タイプ'] == 'EGV'].copy()
cgm_df['timestamp'] = pd.to_datetime(cgm_df['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
cgm_df['glucose'] = pd.to_numeric(cgm_df['グルコース値 (mg/dL)'], errors='coerce')
cgm_df = cgm_df[['timestamp', 'glucose']].dropna().sort_values('timestamp')

# 重複期間でフィルタ
overlap_start = max(cgm_df['timestamp'].min(), hr_df['datetime'].min())
overlap_end = min(cgm_df['timestamp'].max(), hr_df['datetime'].max())

print(f"分析期間: {overlap_start.strftime('%Y-%m-%d %H:%M')} ～ {overlap_end.strftime('%Y-%m-%d %H:%M')}")

cgm_df = cgm_df[(cgm_df['timestamp'] >= overlap_start) & (cgm_df['timestamp'] <= overlap_end)]
hr_df = hr_df[(hr_df['datetime'] >= overlap_start) & (hr_df['datetime'] <= overlap_end)]

print(f"CGMデータ: {len(cgm_df)}件")
print(f"心拍データ: {len(hr_df)}件")

# 時間近傍マージ（CGM基準、5分tolerance）
merged = pd.merge_asof(
    cgm_df.sort_values('timestamp'),
    hr_df.sort_values('datetime'),
    left_on='timestamp',
    right_on='datetime',
    direction='nearest',
    tolerance=pd.Timedelta('5min')
).dropna()

print(f"マージ後: {len(merged)}件")

# 派生列
merged['date'] = merged['timestamp'].dt.date
merged['hour'] = merged['timestamp'].dt.hour
merged['time_segment'] = pd.cut(
    merged['hour'],
    bins=[-1, 5, 11, 17, 23],
    labels=['Midnight(0-5)', 'Morning(6-11)', 'Afternoon(12-17)', 'Evening(18-23)']
)

# 全期間統計
hr_mean = merged['heart_rate'].mean()
hr_std = merged['heart_rate'].std()
hr_min = merged['heart_rate'].min()
hr_max = merged['heart_rate'].max()

g_mean = merged['glucose'].mean()
g_std = merged['glucose'].std()
g_min = merged['glucose'].min()
g_max = merged['glucose'].max()
tir = ((merged['glucose'] >= 70) & (merged['glucose'] <= 180)).mean() * 100

# 全期間相関
r_all, p_all = stats.pearsonr(merged['glucose'], merged['heart_rate'])
slope, intercept, _, _, _ = stats.linregress(merged['glucose'], merged['heart_rate'])

print(f"\n=== 全期間サマリー ===")
print(f"心拍数: {hr_mean:.1f} ± {hr_std:.1f} bpm ({hr_min:.0f}-{hr_max:.0f})")
print(f"血糖値: {g_mean:.1f} ± {g_std:.1f} mg/dL ({g_min:.0f}-{g_max:.0f})")
print(f"TIR(70-180): {tir:.1f}%")
print(f"相関係数: r={r_all:.3f}, p={p_all:.4f}")

# 日別相関
daily_stats = []
for date, group in merged.groupby('date'):
    if len(group) >= 10:
        r, p = stats.pearsonr(group['glucose'], group['heart_rate'])
        daily_stats.append({
            'date': date,
            'n': len(group),
            'r': r,
            'p': p,
            'glucose_mean': group['glucose'].mean(),
            'hr_mean': group['heart_rate'].mean(),
        })
daily_df = pd.DataFrame(daily_stats)

# 時間帯別相関
segment_stats = []
for seg, group in merged.groupby('time_segment', observed=True):
    if len(group) >= 10:
        r, p = stats.pearsonr(group['glucose'], group['heart_rate'])
        segment_stats.append({
            'segment': seg,
            'n': len(group),
            'r': r,
            'p': p,
            'glucose_mean': group['glucose'].mean(),
            'hr_mean': group['heart_rate'].mean(),
        })
segment_df = pd.DataFrame(segment_stats)

# 時間別平均
hourly = merged.groupby('hour').agg(
    glucose_mean=('glucose', 'mean'),
    hr_mean=('heart_rate', 'mean')
).reset_index()

# ========== 可視化 ==========
plt.style.use('dark_background')
fig = plt.figure(figsize=(16, 20))
gs = fig.add_gridspec(3, 2, hspace=0.4, wspace=0.3)

color_hr = '#9370DB'
color_glucose = '#FF6B6B'
color_teal = '#4ECDC4'
bg_color = '#1a1a1a'

# パネル1: フル時系列（全幅）
ax1 = fig.add_subplot(gs[0, :])
ax1_twin = ax1.twinx()

ax1.plot(hr_df['datetime'], hr_df['heart_rate'], color=color_hr, linewidth=1, alpha=0.7, label='Heart Rate')
ax1.fill_between(hr_df['datetime'], hr_df['heart_rate'], alpha=0.2, color=color_hr)
ax1_twin.plot(cgm_df['timestamp'], cgm_df['glucose'], color=color_glucose, linewidth=2, alpha=0.9, label='Glucose')

ax1.set_ylabel('Heart Rate (bpm)', color=color_hr, fontsize=11, fontweight='bold')
ax1.tick_params(axis='y', labelcolor=color_hr)
ax1_twin.set_ylabel('Glucose (mg/dL)', color=color_glucose, fontsize=11, fontweight='bold')
ax1_twin.tick_params(axis='y', labelcolor=color_glucose)

ax1.set_title(
    f'24h Heart Rate & Glucose\n{overlap_start.strftime("%Y/%m/%d %H:%M")} - {overlap_end.strftime("%Y/%m/%d %H:%M")}',
    fontsize=14, pad=15, loc='left', fontweight='bold'
)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d\n%H:%M'))
ax1.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
ax1.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)

# 日付境界線
for date in daily_df['date']:
    ax1.axvline(pd.Timestamp(date), color='gray', linestyle='--', linewidth=0.8, alpha=0.4)

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax1_twin.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', framealpha=0.8)

# パネル2: 散布図
ax2 = fig.add_subplot(gs[1, 0])
ax2.scatter(merged['glucose'], merged['heart_rate'],
            alpha=0.4, s=25, color=color_teal, edgecolors='white', linewidth=0.3)
x_range = np.array([merged['glucose'].min(), merged['glucose'].max()])
ax2.plot(x_range, slope * x_range + intercept, 'r--', linewidth=2, alpha=0.8)
ax2.text(
    0.05, 0.95,
    f'r = {r_all:.3f}\np = {p_all:.4f}\nn = {len(merged)}',
    transform=ax2.transAxes, verticalalignment='top',
    bbox=dict(boxstyle='round', facecolor='black', alpha=0.7), fontsize=11
)
ax2.set_xlabel('Glucose (mg/dL)', fontsize=11, fontweight='bold')
ax2.set_ylabel('Heart Rate (bpm)', fontsize=11, fontweight='bold')
ax2.set_title('Glucose vs Heart Rate (All Days)', fontsize=13, pad=10, loc='left', fontweight='bold')
ax2.grid(True, alpha=0.2)

# パネル3: サーカディアンパターン
ax3 = fig.add_subplot(gs[1, 1])
ax3_twin = ax3.twinx()
ax3.plot(hourly['hour'], hourly['hr_mean'], color=color_hr, linewidth=2, marker='o', markersize=5, label='Heart Rate')
ax3_twin.plot(hourly['hour'], hourly['glucose_mean'], color=color_glucose, linewidth=2, marker='s', markersize=5, label='Glucose')
ax3.set_xlabel('Hour of Day', fontsize=11, fontweight='bold')
ax3.set_ylabel('Avg Heart Rate (bpm)', color=color_hr, fontsize=10, fontweight='bold')
ax3.tick_params(axis='y', labelcolor=color_hr)
ax3_twin.set_ylabel('Avg Glucose (mg/dL)', color=color_glucose, fontsize=10, fontweight='bold')
ax3_twin.tick_params(axis='y', labelcolor=color_glucose)
ax3.set_xticks([0, 6, 12, 18, 23])
for xv in [6, 12, 18]:
    ax3.axvline(xv, color='gray', linestyle='--', linewidth=0.8, alpha=0.4)
ax3.set_title('Circadian Pattern (Hourly Average)', fontsize=13, pad=10, loc='left', fontweight='bold')
ax3.grid(True, alpha=0.2)
lines1, labels1 = ax3.get_legend_handles_labels()
lines2, labels2 = ax3_twin.get_legend_handles_labels()
ax3.legend(lines1 + lines2, labels1 + labels2, loc='upper right', framealpha=0.8)

# パネル4: 日別相関
ax4 = fig.add_subplot(gs[2, 0])
colors_daily = [color_glucose if r >= 0 else color_teal for r in daily_df['r']]
bars = ax4.bar(
    [str(d)[5:] for d in daily_df['date']],  # MM-DD形式
    daily_df['r'],
    color=colors_daily, edgecolor='white', linewidth=0.5
)
ax4.axhline(0, color='white', linewidth=0.8, alpha=0.5)
for bar, row in zip(bars, daily_df.itertuples()):
    sig = '*' if row.p < 0.05 else ''
    label = f'r={row.r:.2f}{sig}\n(n={row.n})'
    y_pos = row.r + 0.01 if row.r >= 0 else row.r - 0.01
    va = 'bottom' if row.r >= 0 else 'top'
    ax4.text(bar.get_x() + bar.get_width() / 2, y_pos, label,
             ha='center', va=va, fontsize=8, color='white')
ax4.set_xlabel('Date', fontsize=11, fontweight='bold')
ax4.set_ylabel('Pearson r', fontsize=11, fontweight='bold')
ax4.set_title('Daily Glucose-HR Correlation\n(*p<0.05)', fontsize=13, pad=10, loc='left', fontweight='bold')
ax4.set_ylim(-1, 1)
ax4.grid(True, alpha=0.2, axis='y')

# パネル5: 時間帯別相関
ax5 = fig.add_subplot(gs[2, 1])
colors_seg = [color_glucose if r >= 0 else color_teal for r in segment_df['r']]
bars5 = ax5.bar(
    segment_df['segment'].astype(str),
    segment_df['r'],
    color=colors_seg, edgecolor='white', linewidth=0.5
)
ax5.axhline(0, color='white', linewidth=0.8, alpha=0.5)
for bar, row in zip(bars5, segment_df.itertuples()):
    sig = '*' if row.p < 0.05 else ''
    label = f'r={row.r:.2f}{sig}\n(n={row.n})'
    y_pos = row.r + 0.01 if row.r >= 0 else row.r - 0.01
    va = 'bottom' if row.r >= 0 else 'top'
    ax5.text(bar.get_x() + bar.get_width() / 2, y_pos, label,
             ha='center', va=va, fontsize=8, color='white')
ax5.set_xlabel('Time Segment', fontsize=11, fontweight='bold')
ax5.set_ylabel('Pearson r', fontsize=11, fontweight='bold')
ax5.set_title('Segment Glucose-HR Correlation\n(*p<0.05)', fontsize=13, pad=10, loc='left', fontweight='bold')
ax5.set_ylim(-1, 1)
ax5.grid(True, alpha=0.2, axis='y')
plt.setp(ax5.get_xticklabels(), rotation=15, ha='right')

for ax in [ax1, ax1_twin, ax2, ax3, ax3_twin, ax4, ax5]:
    ax.set_facecolor(bg_color)
fig.patch.set_facecolor(bg_color)

plt.savefig(f'{OUTPUT_DIR}/cgm_hr_24h_analysis.png', dpi=150,
            facecolor=bg_color, edgecolor='none', bbox_inches='tight')
print("\nグラフを保存しました: cgm_hr_24h_analysis.png")

# ========== Markdownレポート ==========
def sig_label(p):
    return '有意 (p < 0.05)' if p < 0.05 else '有意でない (p ≥ 0.05)'

def corr_strength(r):
    a = abs(r)
    if a > 0.5:
        return '強い'
    elif a > 0.3:
        return '中程度の'
    else:
        return '弱い'

daily_table = '\n'.join(
    f'| {str(row.date)[5:]} | {row.n} | {row.r:.3f} | {row.p:.4f} | {"*" if row.p < 0.05 else "-"} | {row.glucose_mean:.1f} | {row.hr_mean:.1f} |'
    for row in daily_df.itertuples()
)

segment_table = '\n'.join(
    f'| {row.segment} | {row.n} | {row.r:.3f} | {row.p:.4f} | {"*" if row.p < 0.05 else "-"} | {row.glucose_mean:.1f} | {row.hr_mean:.1f} |'
    for row in segment_df.itertuples()
)

report = f"""# 24時間CGM血糖値と心拍数の相関分析

**分析期間**: {overlap_start.strftime('%Y-%m-%d %H:%M')} ～ {overlap_end.strftime('%Y-%m-%d %H:%M')}（約{(overlap_end - overlap_start).days + 1}日間）
**データポイント**: CGM {len(cgm_df)}件, 心拍 {len(hr_df)}件, マージ後 {len(merged)}件

## 全期間サマリー

### 心拍数
- **平均**: {hr_mean:.1f} ± {hr_std:.1f} bpm
- **範囲**: {hr_min:.0f} - {hr_max:.0f} bpm

### 血糖値
- **平均**: {g_mean:.1f} ± {g_std:.1f} mg/dL
- **範囲**: {g_min:.0f} - {g_max:.0f} mg/dL
- **TIR (70-180 mg/dL)**: {tir:.1f}%

### 相関分析（全期間）
- **相関係数**: {r_all:.3f}（{corr_strength(r_all)}{'正の' if r_all > 0 else '負の'}相関）
- **統計的有意性**: {sig_label(p_all)} (p = {p_all:.4f})
- **回帰式**: 心拍数 = {slope:.3f} × 血糖値 + {intercept:.3f}

## 日別分析

| 日付 | n | 相関係数 | p値 | 有意 | 平均血糖値 | 平均心拍数 |
|------|---|----------|-----|------|------------|------------|
{daily_table}

## 時間帯別分析

| 時間帯 | n | 相関係数 | p値 | 有意 | 平均血糖値 | 平均心拍数 |
|--------|---|----------|-----|------|------------|------------|
{segment_table}

## 分析結果

![24時間CGM血糖値と心拍数分析](cgm_hr_24h_analysis.png)

### グラフの見方

1. **上段（フル時系列）**: 約6日間の心拍数（紫・左軸）と血糖値（赤・右軸）の推移。点線は日付境界。
2. **中左（散布図）**: 全データ点の血糖値 vs 心拍数。赤破線は回帰直線。
3. **中右（サーカディアンパターン）**: 時間帯別の平均値。食事・活動・睡眠のリズムを反映。
4. **下左（日別相関）**: 日ごとの相関係数。赤=正の相関、ティール=負の相関、*=p<0.05。
5. **下右（時間帯別相関）**: 深夜/朝/午後/夜の4区分での相関係数。

## 解釈

### 全体的な傾向
{corr_strength(r_all)}{'正の' if r_all > 0 else '負の'}相関（r = {r_all:.3f}）が{'統計的に有意に' if p_all < 0.05 else ''}観察されました。
{'24時間の活動・食事・自律神経の変化が両指標に影響していると考えられます。' if abs(r_all) < 0.3 else ''}

### 睡眠時との比較（Issue 008）
- 睡眠中（2/16 1夜分）: r = -0.310（中程度の負の相関、p < 0.05）
- 24時間全期間（約6日間）: r = {r_all:.3f}（{sig_label(p_all)}）
- 睡眠中と覚醒中では心拍数-血糖値の関係が異なる可能性があります。

### 時間帯別の特徴
活動量・食事タイミングによって、各時間帯で血糖値と心拍数の関係が異なります。
サーカディアンリズムの影響（早朝覚醒後のコルチゾール分泌による血糖上昇など）も考慮が必要です。

---
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Script: analyze_cgm_hr_24h.py*
"""

with open(f'{OUTPUT_DIR}/ANALYSIS.md', 'w', encoding='utf-8') as f:
    f.write(report)
print("レポートを保存しました: ANALYSIS.md")

merged.to_csv(f'{OUTPUT_DIR}/merged_cgm_hr_24h_data.csv', index=False)
print("マージデータを保存しました: merged_cgm_hr_24h_data.csv")

print("\n分析完了！")
