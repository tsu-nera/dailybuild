#!/usr/bin/env python3
"""覚醒時CGM血糖値と心拍数の相関分析スクリプト

Analysis A: 睡眠除外のみ（全覚醒時間）
Analysis B: 睡眠除外 + 歩行ノイズ除去（安静覚醒時のみ）
"""

import sys
import os
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from datetime import datetime
import numpy as np
from scipy import stats

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.lib.analytics.circadian import exclude_sleep_periods

OUTPUT_DIR = Path(__file__).parent

# ========== データ読み込み ==========
print("データを読み込み中...")

hr_df = pd.read_csv(
    project_root / 'data/fitbit/heart_rate_intraday.csv',
    index_col='datetime', parse_dates=True
)

steps_df = pd.read_csv(
    project_root / 'data/fitbit/steps_intraday.csv',
    index_col='datetime', parse_dates=True
)

cgm_df = pd.read_csv(
    project_root / 'data/dexcom.csv',
    skiprows=range(1, 11)
)

sleep_df = pd.read_csv(
    project_root / 'data/fitbit/sleep.csv',
    parse_dates=['startTime', 'endTime']
)

# CGMデータ前処理（EGVのみ）
cgm_df = cgm_df[cgm_df['イベント タイプ'] == 'EGV'].copy()
cgm_df['timestamp'] = pd.to_datetime(cgm_df['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
cgm_df['glucose'] = pd.to_numeric(cgm_df['グルコース値 (mg/dL)'], errors='coerce')
cgm_df = cgm_df[['timestamp', 'glucose']].dropna().sort_values('timestamp')

print(f"生データ: CGM {len(cgm_df)}件, HR {len(hr_df)}件, Steps {len(steps_df)}件, 睡眠 {len(sleep_df)}件")

# 重複期間でフィルタ
overlap_start = max(cgm_df['timestamp'].min(), hr_df.index.min())
overlap_end = min(cgm_df['timestamp'].max(), hr_df.index.max())

print(f"分析期間: {overlap_start.strftime('%Y-%m-%d %H:%M')} ～ {overlap_end.strftime('%Y-%m-%d %H:%M')}")

cgm_df = cgm_df[(cgm_df['timestamp'] >= overlap_start) & (cgm_df['timestamp'] <= overlap_end)]
hr_df = hr_df[(hr_df.index >= overlap_start) & (hr_df.index <= overlap_end)]
steps_df = steps_df[(steps_df.index >= overlap_start) & (steps_df.index <= overlap_end)]
sleep_df = sleep_df[
    (sleep_df['startTime'] >= overlap_start - pd.Timedelta('1day')) &
    (sleep_df['endTime'] <= overlap_end + pd.Timedelta('1day'))
]

# ========== 覚醒時CGMフィルタリング（共通） ==========
# CGMから睡眠時間帯を除外
cgm_awake = cgm_df.set_index('timestamp')
for _, sleep in sleep_df.iterrows():
    start = pd.to_datetime(sleep['startTime'])
    end = pd.to_datetime(sleep['endTime'])
    mask = (cgm_awake.index >= start) & (cgm_awake.index <= end)
    cgm_awake = cgm_awake[~mask]
cgm_awake = cgm_awake.reset_index()
print(f"CGM 睡眠除外後: {len(cgm_awake)}件 ({len(cgm_awake)/len(cgm_df)*100:.1f}%)")

# ========== Analysis A: 睡眠除外のみ ==========
print("\n=== Analysis A: 睡眠除外 ===")
hr_a = exclude_sleep_periods(hr_df, sleep_df)
print(f"HR 睡眠除外後: {len(hr_a)}件 ({len(hr_a)/len(hr_df)*100:.1f}%)")

hr_a_reset = hr_a.reset_index()

merged_a = pd.merge_asof(
    cgm_awake.sort_values('timestamp'),
    hr_a_reset.sort_values('datetime'),
    left_on='timestamp',
    right_on='datetime',
    direction='nearest',
    tolerance=pd.Timedelta('5min')
).dropna()

print(f"Analysis A マージ後: {len(merged_a)}件")

# ========== Analysis B: 睡眠除外 + 歩行ノイズ除去 ==========
print("\n=== Analysis B: 睡眠除外 + 歩数フィルタ ===")

# HRとStepsをinner merge（睡眠除外済みHRに対して）
hr_steps = hr_a.merge(steps_df, left_index=True, right_index=True, how='inner')
print(f"HR + Steps マージ: {len(hr_steps)}件")

# 歩数フィルタ: 現在分と前1分ともに steps == 0
hr_steps = hr_steps.sort_index()
hr_steps['steps_prev'] = hr_steps['steps'].shift(1)
hr_b = hr_steps[
    (hr_steps['steps'] == 0) &
    ((hr_steps['steps_prev'] == 0) | hr_steps['steps_prev'].isna())
][['heart_rate']].copy()

print(f"歩数フィルタ後: {len(hr_b)}件 ({len(hr_b)/len(hr_a)*100:.1f}%)")

hr_b_reset = hr_b.reset_index()

merged_b = pd.merge_asof(
    cgm_awake.sort_values('timestamp'),
    hr_b_reset.sort_values('datetime'),
    left_on='timestamp',
    right_on='datetime',
    direction='nearest',
    tolerance=pd.Timedelta('5min')
).dropna()

print(f"Analysis B マージ後: {len(merged_b)}件")
print(f"\nデータ数確認: A={len(merged_a)}, B={len(merged_b)} (B < A: {len(merged_b) < len(merged_a)})")

# ========== 統計計算 ==========
def compute_stats(merged):
    r, p = stats.pearsonr(merged['glucose'], merged['heart_rate'])
    slope, intercept, _, _, _ = stats.linregress(merged['glucose'], merged['heart_rate'])
    return dict(
        hr_mean=merged['heart_rate'].mean(),
        hr_std=merged['heart_rate'].std(),
        hr_min=merged['heart_rate'].min(),
        hr_max=merged['heart_rate'].max(),
        g_mean=merged['glucose'].mean(),
        g_std=merged['glucose'].std(),
        g_min=merged['glucose'].min(),
        g_max=merged['glucose'].max(),
        tir=((merged['glucose'] >= 70) & (merged['glucose'] <= 180)).mean() * 100,
        r=r, p=p, slope=slope, intercept=intercept,
        n=len(merged)
    )

def compute_daily(merged):
    merged = merged.copy()
    merged['date'] = merged['timestamp'].dt.date
    daily = []
    for date, group in merged.groupby('date'):
        if len(group) >= 10:
            r, p = stats.pearsonr(group['glucose'], group['heart_rate'])
            daily.append(dict(date=date, n=len(group), r=r, p=p,
                              glucose_mean=group['glucose'].mean(),
                              hr_mean=group['heart_rate'].mean()))
    return pd.DataFrame(daily)

def compute_segments(merged):
    merged = merged.copy()
    merged['hour'] = merged['timestamp'].dt.hour
    merged['segment'] = pd.cut(
        merged['hour'],
        bins=[5, 11, 17, 23],
        labels=['Morning\n(6-11)', 'Afternoon\n(12-17)', 'Evening\n(18-23)']
    )
    segs = []
    for seg, group in merged.groupby('segment', observed=True):
        if len(group) >= 10:
            r, p = stats.pearsonr(group['glucose'], group['heart_rate'])
            segs.append(dict(segment=str(seg), n=len(group), r=r, p=p,
                             glucose_mean=group['glucose'].mean(),
                             hr_mean=group['heart_rate'].mean()))
    return pd.DataFrame(segs)

st_a = compute_stats(merged_a)
st_b = compute_stats(merged_b)
daily_a = compute_daily(merged_a)
daily_b = compute_daily(merged_b)
seg_a = compute_segments(merged_a)
seg_b = compute_segments(merged_b)

print(f"\n=== Analysis A サマリー ===")
print(f"心拍数: {st_a['hr_mean']:.1f} ± {st_a['hr_std']:.1f} bpm")
print(f"血糖値: {st_a['g_mean']:.1f} ± {st_a['g_std']:.1f} mg/dL, TIR={st_a['tir']:.1f}%")
print(f"相関: r={st_a['r']:.3f}, p={st_a['p']:.4f}, n={st_a['n']}")

print(f"\n=== Analysis B サマリー ===")
print(f"心拍数: {st_b['hr_mean']:.1f} ± {st_b['hr_std']:.1f} bpm")
print(f"血糖値: {st_b['g_mean']:.1f} ± {st_b['g_std']:.1f} mg/dL, TIR={st_b['tir']:.1f}%")
print(f"相関: r={st_b['r']:.3f}, p={st_b['p']:.4f}, n={st_b['n']}")

# ========== 可視化 ==========
plt.style.use('dark_background')
fig = plt.figure(figsize=(16, 24))
gs = fig.add_gridspec(4, 2, hspace=0.45, wspace=0.3)

color_hr = '#9370DB'
color_glucose = '#FF6B6B'
color_teal = '#4ECDC4'
color_orange = '#FFA500'
bg_color = '#1a1a1a'

# --- Row 0: 時系列（全幅） ---
ax0 = fig.add_subplot(gs[0, :])
ax0_twin = ax0.twinx()

# HR全体（薄く）
ax0.plot(hr_df.index, hr_df['heart_rate'],
         color=color_hr, linewidth=0.8, alpha=0.5, label='Heart Rate (all)')
# 覚醒HR（Analysis A）
ax0.plot(hr_a.index, hr_a['heart_rate'],
         color=color_hr, linewidth=1.2, alpha=0.9, label='Heart Rate (awake)')
# 覚醒CGM
ax0_twin.plot(cgm_awake['timestamp'], cgm_awake['glucose'],
              color=color_glucose, linewidth=2, alpha=0.9, label='Glucose (awake)')
# 全CGM（薄く）
ax0_twin.plot(cgm_df['timestamp'], cgm_df['glucose'],
              color=color_glucose, linewidth=0.8, alpha=0.3)

# 睡眠帯をグレー帯で表示
for _, sleep in sleep_df.iterrows():
    start = pd.to_datetime(sleep['startTime'])
    end = pd.to_datetime(sleep['endTime'])
    ax0.axvspan(start, end, color='gray', alpha=0.25)

ax0.set_ylabel('Heart Rate (bpm)', color=color_hr, fontsize=11, fontweight='bold')
ax0.tick_params(axis='y', labelcolor=color_hr)
ax0_twin.set_ylabel('Glucose (mg/dL)', color=color_glucose, fontsize=11, fontweight='bold')
ax0_twin.tick_params(axis='y', labelcolor=color_glucose)
ax0.set_title(
    f'Awake HR & Glucose Time Series  [{overlap_start.strftime("%Y/%m/%d")} - {overlap_end.strftime("%Y/%m/%d")}]'
    f'\n(Gray bands = Sleep periods)',
    fontsize=13, pad=12, loc='left', fontweight='bold'
)
ax0.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d\n%H:%M'))
ax0.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
ax0.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)

lines1, labels1 = ax0.get_legend_handles_labels()
lines2, labels2 = ax0_twin.get_legend_handles_labels()
sleep_patch = mpatches.Patch(color='gray', alpha=0.4, label='Sleep')
ax0.legend(lines1 + lines2 + [sleep_patch], labels1 + labels2 + ['Sleep'],
           loc='upper right', framealpha=0.8, fontsize=9)

# --- Row 1: 散布図 A / B ---
def plot_scatter(ax, merged, st, title):
    ax.scatter(merged['glucose'], merged['heart_rate'],
               alpha=0.4, s=25, color=color_teal, edgecolors='white', linewidth=0.3)
    x_range = np.array([merged['glucose'].min(), merged['glucose'].max()])
    ax.plot(x_range, st['slope'] * x_range + st['intercept'], 'r--', linewidth=2, alpha=0.8)
    sig = '★' if st['p'] < 0.05 else ''
    ax.text(
        0.05, 0.95,
        f"r = {st['r']:.3f}{sig}\np = {st['p']:.4f}\nn = {st['n']}",
        transform=ax.transAxes, verticalalignment='top',
        bbox=dict(boxstyle='round', facecolor='black', alpha=0.7), fontsize=11
    )
    ax.set_xlabel('Glucose (mg/dL)', fontsize=11, fontweight='bold')
    ax.set_ylabel('Heart Rate (bpm)', fontsize=11, fontweight='bold')
    ax.set_title(title, fontsize=12, pad=8, loc='left', fontweight='bold')
    ax.grid(True, alpha=0.2)

ax1l = fig.add_subplot(gs[1, 0])
ax1r = fig.add_subplot(gs[1, 1])
plot_scatter(ax1l, merged_a, st_a, 'Analysis A: Scatter (Awake, all)')
plot_scatter(ax1r, merged_b, st_b, 'Analysis B: Scatter (Awake, resting)')

# --- Row 2: 日別相関 A / B ---
def plot_daily(ax, daily_df, title):
    if daily_df.empty:
        ax.text(0.5, 0.5, 'No data', transform=ax.transAxes, ha='center')
        ax.set_title(title, fontsize=12, pad=8, loc='left', fontweight='bold')
        return
    colors = [color_glucose if r >= 0 else color_teal for r in daily_df['r']]
    bars = ax.bar(
        [str(d)[5:] for d in daily_df['date']],
        daily_df['r'],
        color=colors, edgecolor='white', linewidth=0.5
    )
    ax.axhline(0, color='white', linewidth=0.8, alpha=0.5)
    for bar, row in zip(bars, daily_df.itertuples()):
        sig = '*' if row.p < 0.05 else ''
        label = f'r={row.r:.2f}{sig}\n(n={row.n})'
        y_pos = row.r + 0.02 if row.r >= 0 else row.r - 0.02
        va = 'bottom' if row.r >= 0 else 'top'
        ax.text(bar.get_x() + bar.get_width() / 2, y_pos, label,
                ha='center', va=va, fontsize=8, color='white')
    ax.set_xlabel('Date', fontsize=11, fontweight='bold')
    ax.set_ylabel('Pearson r', fontsize=11, fontweight='bold')
    ax.set_title(title + '\n(*p<0.05)', fontsize=12, pad=8, loc='left', fontweight='bold')
    ax.set_ylim(-1.1, 1.1)
    ax.grid(True, alpha=0.2, axis='y')
    plt.setp(ax.get_xticklabels(), rotation=30, ha='right')

ax2l = fig.add_subplot(gs[2, 0])
ax2r = fig.add_subplot(gs[2, 1])
plot_daily(ax2l, daily_a, 'Daily Correlation (Analysis A)')
plot_daily(ax2r, daily_b, 'Daily Correlation (Analysis B)')

# --- Row 3: 時間帯別相関 A / B ---
def plot_segments(ax, seg_df, title):
    if seg_df.empty:
        ax.text(0.5, 0.5, 'No data', transform=ax.transAxes, ha='center')
        ax.set_title(title, fontsize=12, pad=8, loc='left', fontweight='bold')
        return
    colors = [color_glucose if r >= 0 else color_teal for r in seg_df['r']]
    bars = ax.bar(
        seg_df['segment'],
        seg_df['r'],
        color=colors, edgecolor='white', linewidth=0.5, width=0.5
    )
    ax.axhline(0, color='white', linewidth=0.8, alpha=0.5)
    for bar, row in zip(bars, seg_df.itertuples()):
        sig = '*' if row.p < 0.05 else ''
        label = f'r={row.r:.2f}{sig}\n(n={row.n})'
        y_pos = row.r + 0.02 if row.r >= 0 else row.r - 0.02
        va = 'bottom' if row.r >= 0 else 'top'
        ax.text(bar.get_x() + bar.get_width() / 2, y_pos, label,
                ha='center', va=va, fontsize=9, color='white')
    ax.set_xlabel('Time Segment', fontsize=11, fontweight='bold')
    ax.set_ylabel('Pearson r', fontsize=11, fontweight='bold')
    ax.set_title(title + '\n(*p<0.05)', fontsize=12, pad=8, loc='left', fontweight='bold')
    ax.set_ylim(-1.1, 1.1)
    ax.grid(True, alpha=0.2, axis='y')

ax3l = fig.add_subplot(gs[3, 0])
ax3r = fig.add_subplot(gs[3, 1])
plot_segments(ax3l, seg_a, 'Time Segment (Analysis A)')
plot_segments(ax3r, seg_b, 'Time Segment (Analysis B)')

# 背景色統一
for ax in fig.get_axes():
    ax.set_facecolor(bg_color)
fig.patch.set_facecolor(bg_color)

png_path = OUTPUT_DIR / 'cgm_hr_awake_analysis.png'
plt.savefig(str(png_path), dpi=150, facecolor=bg_color, edgecolor='none', bbox_inches='tight')
print(f"\nグラフを保存しました: {png_path}")
plt.close()

# ========== CSVエクスポート ==========
merged_a.to_csv(OUTPUT_DIR / 'merged_cgm_hr_awake_a.csv', index=False)
merged_b.to_csv(OUTPUT_DIR / 'merged_cgm_hr_awake_b.csv', index=False)
print("CSVを保存しました: merged_cgm_hr_awake_a.csv, merged_cgm_hr_awake_b.csv")

# ========== Markdownレポート ==========
def sig_label(p):
    return '有意 (p < 0.05)' if p < 0.05 else '有意でない (p ≥ 0.05)'

def corr_strength(r):
    a = abs(r)
    if a > 0.5:
        return '強い'
    elif a > 0.3:
        return '中程度の'
    return '弱い'

def daily_table(daily_df):
    if daily_df.empty:
        return '（データなし）'
    rows = []
    for row in daily_df.itertuples():
        rows.append(
            f'| {str(row.date)[5:]} | {row.n} | {row.r:.3f} | {row.p:.4f} '
            f'| {"*" if row.p < 0.05 else "-"} | {row.glucose_mean:.1f} | {row.hr_mean:.1f} |'
        )
    return '\n'.join(rows)

def seg_table(seg_df):
    if seg_df.empty:
        return '（データなし）'
    rows = []
    for row in seg_df.itertuples():
        rows.append(
            f'| {row.segment.replace(chr(10), " ")} | {row.n} | {row.r:.3f} | {row.p:.4f} '
            f'| {"*" if row.p < 0.05 else "-"} | {row.glucose_mean:.1f} | {row.hr_mean:.1f} |'
        )
    return '\n'.join(rows)

report = f"""# 覚醒時CGM血糖値と心拍数の相関分析

**分析期間**: {overlap_start.strftime('%Y-%m-%d %H:%M')} ～ {overlap_end.strftime('%Y-%m-%d %H:%M')}
**前提**: 睡眠中（Issue 008: r=-0.310）・24時間（Issue 009: r=0.147）の結果を踏まえ、覚醒時に絞って分析

---

## 分析方法

| | Analysis A | Analysis B |
|---|---|---|
| **対象** | 全覚醒時間 | 安静覚醒時のみ |
| **処理** | 睡眠除外 | 睡眠除外 + 歩数フィルタ |
| **歩数条件** | - | 現在・前1分ともにsteps=0 |
| **データ数** | {st_a['n']}件 | {st_b['n']}件 |

---

## Analysis A: 全覚醒時（睡眠除外のみ）

### 基本統計

| 指標 | 値 |
|------|-----|
| 心拍数 | {st_a['hr_mean']:.1f} ± {st_a['hr_std']:.1f} bpm ({st_a['hr_min']:.0f}-{st_a['hr_max']:.0f}) |
| 血糖値 | {st_a['g_mean']:.1f} ± {st_a['g_std']:.1f} mg/dL ({st_a['g_min']:.0f}-{st_a['g_max']:.0f}) |
| TIR (70-180) | {st_a['tir']:.1f}% |

### 相関分析

- **相関係数**: r = {st_a['r']:.3f}（{corr_strength(st_a['r'])}{'正の' if st_a['r'] > 0 else '負の'}相関）
- **統計的有意性**: {sig_label(st_a['p'])} (p = {st_a['p']:.4f})
- **回帰式**: 心拍数 = {st_a['slope']:.4f} × 血糖値 + {st_a['intercept']:.3f}

### 日別相関

| 日付 | n | 相関係数 | p値 | 有意 | 平均血糖値 | 平均心拍数 |
|------|---|----------|-----|------|------------|------------|
{daily_table(daily_a)}

### 時間帯別相関

| 時間帯 | n | 相関係数 | p値 | 有意 | 平均血糖値 | 平均心拍数 |
|--------|---|----------|-----|------|------------|------------|
{seg_table(seg_a)}

---

## Analysis B: 安静覚醒時（歩数フィルタ適用）

### 基本統計

| 指標 | 値 |
|------|-----|
| 心拍数 | {st_b['hr_mean']:.1f} ± {st_b['hr_std']:.1f} bpm ({st_b['hr_min']:.0f}-{st_b['hr_max']:.0f}) |
| 血糖値 | {st_b['g_mean']:.1f} ± {st_b['g_std']:.1f} mg/dL ({st_b['g_min']:.0f}-{st_b['g_max']:.0f}) |
| TIR (70-180) | {st_b['tir']:.1f}% |

### 相関分析

- **相関係数**: r = {st_b['r']:.3f}（{corr_strength(st_b['r'])}{'正の' if st_b['r'] > 0 else '負の'}相関）
- **統計的有意性**: {sig_label(st_b['p'])} (p = {st_b['p']:.4f})
- **回帰式**: 心拍数 = {st_b['slope']:.4f} × 血糖値 + {st_b['intercept']:.3f}

### 日別相関

| 日付 | n | 相関係数 | p値 | 有意 | 平均血糖値 | 平均心拍数 |
|------|---|----------|-----|------|------------|------------|
{daily_table(daily_b)}

### 時間帯別相関

| 時間帯 | n | 相関係数 | p値 | 有意 | 平均血糖値 | 平均心拍数 |
|--------|---|----------|-----|------|------------|------------|
{seg_table(seg_b)}

---

## A vs B 比較サマリー

| 項目 | Analysis A (全覚醒) | Analysis B (安静覚醒) | 差 |
|------|---------------------|----------------------|-----|
| データ数 | {st_a['n']} | {st_b['n']} | {st_a['n'] - st_b['n']} |
| 相関係数 r | {st_a['r']:.3f} | {st_b['r']:.3f} | {st_b['r'] - st_a['r']:+.3f} |
| p値 | {st_a['p']:.4f} | {st_b['p']:.4f} | - |
| 有意性 | {"有意" if st_a['p'] < 0.05 else "非有意"} | {"有意" if st_b['p'] < 0.05 else "非有意"} | - |
| 平均心拍数 | {st_a['hr_mean']:.1f} bpm | {st_b['hr_mean']:.1f} bpm | {st_b['hr_mean'] - st_a['hr_mean']:+.1f} |
| 平均血糖値 | {st_a['g_mean']:.1f} mg/dL | {st_b['g_mean']:.1f} mg/dL | {st_b['g_mean'] - st_a['g_mean']:+.1f} |
| TIR | {st_a['tir']:.1f}% | {st_b['tir']:.1f}% | {st_b['tir'] - st_a['tir']:+.1f}% |

---

## Issue シリーズ相関係数まとめ

| Issue | 対象期間 | 相関係数 | 備考 |
|-------|---------|----------|------|
| 008 | 睡眠中のみ | r = -0.310 | 負の相関（中程度）|
| 009 | 24時間全体 | r = 0.147 | 正の相関（弱い）|
| 010 (A) | 覚醒時全体 | r = {st_a['r']:.3f} | {corr_strength(st_a['r'])}{'正の' if st_a['r'] > 0 else '負の'}相関 |
| 010 (B) | 安静覚醒時 | r = {st_b['r']:.3f} | {corr_strength(st_b['r'])}{'正の' if st_b['r'] > 0 else '負の'}相関 |

---

## 可視化

![覚醒時CGM-HR相関分析](cgm_hr_awake_analysis.png)

### グラフの見方

1. **上段（時系列）**: 覚醒時のHR（紫）と血糖値（赤）。グレー帯=睡眠時間。
2. **中上左（散布図A）**: Analysis Aの全覚醒データの散布図と回帰直線。
3. **中上右（散布図B）**: Analysis Bの安静覚醒データの散布図と回帰直線。
4. **中下左（日別相関A）**: Analysis Aの日別相関係数棒グラフ（赤=正、ティール=負、*=p<0.05）。
5. **中下右（日別相関B）**: Analysis Bの日別相関係数棒グラフ。
6. **下左（時間帯別A）**: Analysis Aの朝・午後・夜別相関。
7. **下右（時間帯別B）**: Analysis Bの朝・午後・夜別相関。

---

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Script: analyze_cgm_hr_awake.py*
"""

report_path = OUTPUT_DIR / 'ANALYSIS.md'
with open(str(report_path), 'w', encoding='utf-8') as f:
    f.write(report)
print(f"レポートを保存しました: {report_path}")

print("\n分析完了！")
