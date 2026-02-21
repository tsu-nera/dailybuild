#!/usr/bin/env python3
"""CGM基本統計分析スクリプト - Dexcom G7データ単体分析"""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import matplotlib.colors as mcolors
import numpy as np
from datetime import datetime

OUTPUT_DIR = Path(__file__).parent
PROJECT_ROOT = Path(__file__).parent.parent.parent

# ========== データ読み込み ==========
print("データを読み込み中...")

raw_df = pd.read_csv(
    PROJECT_ROOT / 'data/dexcom.csv',
    skiprows=range(1, 11)
)

# EGVデータ
cgm_df = raw_df[raw_df['イベント タイプ'] == 'EGV'].copy()
cgm_df['timestamp'] = pd.to_datetime(cgm_df['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
cgm_df['glucose'] = pd.to_numeric(cgm_df['グルコース値 (mg/dL)'], errors='coerce')
cgm_df = cgm_df[['timestamp', 'glucose']].dropna().sort_values('timestamp').reset_index(drop=True)

# イベントデータ抽出
def extract_events(df, event_type):
    ev = df[df['イベント タイプ'] == event_type].copy()
    ev = ev[ev['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'].notna() &
            (ev['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'] != '')]
    if not ev.empty:
        ev['timestamp'] = pd.to_datetime(ev['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
    return ev

meal_df = extract_events(raw_df, '食事')
if not meal_df.empty:
    meal_df['carbs'] = pd.to_numeric(meal_df['炭水化物値 (グラム)'], errors='coerce')

activity_df = extract_events(raw_df, '活動')

print(f"EGVデータ: {len(cgm_df)}件")
print(f"食事イベント: {len(meal_df)}件, 活動イベント: {len(activity_df)}件")
print(f"期間: {cgm_df['timestamp'].min().strftime('%Y-%m-%d %H:%M')} ～ {cgm_df['timestamp'].max().strftime('%Y-%m-%d %H:%M')}")

# ========== 派生列 ==========
cgm_df['date'] = cgm_df['timestamp'].dt.date
cgm_df['hour'] = cgm_df['timestamp'].dt.hour
cgm_df['minute'] = cgm_df['timestamp'].dt.minute
cgm_df['time_minutes'] = cgm_df['hour'] * 60 + cgm_df['minute']

BIN_SIZE = 5  # 5分間隔
cgm_df['time_bin'] = (cgm_df['time_minutes'] // BIN_SIZE) * BIN_SIZE

# ========== 全体統計 ==========
g = cgm_df['glucose']
mean_g = g.mean()
median_g = g.median()
sd_g = g.std()
min_g = g.min()
max_g = g.max()
cv_g = (sd_g / mean_g) * 100
q1 = g.quantile(0.25)
q3 = g.quantile(0.75)
iqr_g = q3 - q1
gmi = 3.31 + 0.02392 * mean_g
hba1c_est = (46.7 + mean_g) / 28.7
n_total = len(g)

# TIR全体
tir_very_low = (g < 54).mean() * 100
tir_low = ((g >= 54) & (g < 70)).mean() * 100
tir_target = ((g >= 70) & (g <= 140)).mean() * 100
tir_high = ((g > 140) & (g <= 180)).mean() * 100
tir_very_high = (g > 180).mean() * 100

print(f"\n=== 全体統計 ===")
print(f"平均: {mean_g:.1f} mg/dL, SD: {sd_g:.1f}, CV: {cv_g:.1f}%")
print(f"GMI: {gmi:.2f}%, 推定HbA1c: {hba1c_est:.2f}%")
print(f"TIR(70-140): {tir_target:.1f}%")

# ========== 日別統計 ==========
daily_stats = []
for date, group in cgm_df.groupby('date'):
    g_d = group['glucose']
    mean_d = g_d.mean()
    sd_d = g_d.std()
    daily_stats.append({
        'date': date,
        'mean': mean_d,
        'median': g_d.median(),
        'min': g_d.min(),
        'max': g_d.max(),
        'sd': sd_d,
        'cv': (sd_d / mean_d * 100) if mean_d > 0 else 0,
        'tir_pct': ((g_d >= 70) & (g_d <= 140)).mean() * 100,
        'very_low_pct': (g_d < 54).mean() * 100,
        'low_pct': ((g_d >= 54) & (g_d < 70)).mean() * 100,
        'high_pct': ((g_d > 140) & (g_d <= 180)).mean() * 100,
        'very_high_pct': (g_d > 180).mean() * 100,
        'n': len(g_d),
    })

daily_df = pd.DataFrame(daily_stats)

dates_sorted = sorted(daily_df['date'].tolist())
n_days = len(dates_sorted)

# ========== カラー定義 ==========
COLOR_VERY_LOW = '#8B0000'
COLOR_LOW = '#FF6B6B'
COLOR_TARGET = '#4ECDC4'
COLOR_HIGH = '#FFA500'
COLOR_VERY_HIGH = '#FF4500'

bg_color = '#1a1a1a'
color_glucose = '#FF6B6B'
color_target = '#4ECDC4'
color_meal = '#FFD700'
color_activity = '#9370DB'

plt.style.use('dark_background')

# ========== PLOT 1: 時系列（日毎に行を分割） ==========
print("\n1. 時系列グラフを作成中...")

cgm_df['hour_float'] = cgm_df['hour'] + cgm_df['minute'] / 60

fig, axes = plt.subplots(n_days, 1, figsize=(14, 3 * n_days), sharex=True)
if n_days == 1:
    axes = [axes]

fig.suptitle('CGM Glucose Time Series (Daily)', fontsize=14, fontweight='bold', y=1.01)

for ax, date in zip(axes, dates_sorted):
    day_data = cgm_df[cgm_df['date'] == date]
    row = daily_df[daily_df['date'] == date].iloc[0]

    # 目標範囲バンド
    ax.axhspan(70, 140, color=color_target, alpha=0.1, zorder=0)
    ax.axhline(70, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)
    ax.axhline(140, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)

    # 血糖値トレース
    ax.plot(day_data['hour_float'], day_data['glucose'],
            color=color_glucose, linewidth=1.8, alpha=0.95)

    # 食事マーカー（同日のみ）
    if not meal_df.empty:
        for _, mrow in meal_df[meal_df['timestamp'].dt.date == date].iterrows():
            hf = mrow['timestamp'].hour + mrow['timestamp'].minute / 60
            ax.axvline(hf, color=color_meal, linewidth=1.5, alpha=0.9)
            label = f"M {int(mrow['carbs'])}g" if pd.notna(mrow.get('carbs')) else 'M'
            ax.text(hf + 0.1, 193, label, color=color_meal, fontsize=8, va='top')

    # 活動マーカー（同日のみ）
    if not activity_df.empty:
        for _, arow in activity_df[activity_df['timestamp'].dt.date == date].iterrows():
            hf = arow['timestamp'].hour + arow['timestamp'].minute / 60
            ax.axvline(hf, color=color_activity, linewidth=1.2, alpha=0.9, linestyle=':')

    # タイトル（日付 + 統計）
    ax.set_title(
        f"{str(date)}  |  Mean: {row['mean']:.1f}  SD: {row['sd']:.1f}  CV: {row['cv']:.1f}%  TIR: {row['tir_pct']:.1f}%  n={row['n']}",
        fontsize=10, pad=4, loc='left', fontweight='bold'
    )
    ax.set_ylabel('mg/dL', fontsize=9)
    ax.set_ylim(60, 200)
    ax.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)
    ax.set_facecolor(bg_color)

# X軸（共有）
axes[-1].set_xlabel('Hour of Day', fontsize=11, fontweight='bold')
axes[-1].set_xlim(0, 24)
axes[-1].set_xticks([0, 3, 6, 9, 12, 15, 18, 21, 24])
axes[-1].set_xticklabels(['0:00', '3:00', '6:00', '9:00', '12:00', '15:00', '18:00', '21:00', '24:00'])

# 凡例（最初の行のみ）
axes[0].legend(handles=[
    plt.Line2D([0], [0], color=color_glucose, linewidth=2, label='Glucose (EGV)'),
    mpatches.Patch(color=color_target, alpha=0.3, label='Target (70-140)'),
    plt.Line2D([0], [0], color=color_meal, linewidth=2, label='Meal'),
    plt.Line2D([0], [0], color=color_activity, linewidth=2, linestyle=':', label='Activity'),
], loc='upper right', framealpha=0.8, fontsize=9)

fig.patch.set_facecolor(bg_color)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'cgm_timeseries.png', dpi=150, facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_timeseries.png 保存")

# ========== PLOT 2: AGP日内プロファイル ==========
print("2. AGP日内プロファイルを作成中...")

agp_stats = cgm_df.groupby('time_bin')['glucose'].agg(
    p10=lambda x: x.quantile(0.10),
    p25=lambda x: x.quantile(0.25),
    median='median',
    p75=lambda x: x.quantile(0.75),
    p90=lambda x: x.quantile(0.90),
).reset_index()
agp_stats['hour_float'] = agp_stats['time_bin'] / 60

fig, ax = plt.subplots(figsize=(14, 6))

ax.axhspan(70, 140, color=color_target, alpha=0.08, zorder=0)
ax.axhline(70, color=color_target, linewidth=0.8, linestyle='--', alpha=0.5)
ax.axhline(140, color=color_target, linewidth=0.8, linestyle='--', alpha=0.5)

ax.fill_between(agp_stats['hour_float'], agp_stats['p10'], agp_stats['p90'],
                color=color_glucose, alpha=0.15, label='10-90th percentile')
ax.fill_between(agp_stats['hour_float'], agp_stats['p25'], agp_stats['p75'],
                color=color_glucose, alpha=0.30, label='25-75th percentile')
ax.plot(agp_stats['hour_float'], agp_stats['median'],
        color=color_glucose, linewidth=2.5, label='Median', zorder=5)

for xv in [6, 12, 18]:
    ax.axvline(xv, color='gray', linestyle='--', linewidth=0.8, alpha=0.3)

ax.set_xlabel('Hour of Day', fontsize=12, fontweight='bold')
ax.set_ylabel('Glucose (mg/dL)', fontsize=12, fontweight='bold')
ax.set_title('Ambulatory Glucose Profile (AGP) - Daily 24h Overlay', fontsize=13, pad=12, loc='left', fontweight='bold')
ax.set_xlim(0, 24)
ax.set_xticks([0, 3, 6, 9, 12, 15, 18, 21, 24])
ax.set_xticklabels(['0:00', '3:00', '6:00', '9:00', '12:00', '15:00', '18:00', '21:00', '24:00'])
ax.set_ylim(60, 210)
ax.legend(loc='upper right', framealpha=0.8)
ax.grid(True, alpha=0.2)
ax.set_facecolor(bg_color)
fig.patch.set_facecolor(bg_color)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'cgm_daily_profile.png', dpi=150, facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_daily_profile.png 保存")

# ========== PLOT 3: ヒートマップ ==========
print("3. ヒートマップを作成中...")

N_BINS = 288  # 5分×288 = 24時間
date_idx = {d: i for i, d in enumerate(dates_sorted)}

grid = np.full((n_days, N_BINS), np.nan)
for _, row in cgm_df.iterrows():
    d = row['date']
    bin_idx = int(row['time_bin'] // BIN_SIZE)
    if d in date_idx and 0 <= bin_idx < N_BINS:
        grid[date_idx[d], bin_idx] = row['glucose']

fig, ax = plt.subplots(figsize=(14, 5))

x_edges = np.linspace(0, 24, N_BINS + 1)
y_edges = np.arange(0, n_days + 1)

cmap = plt.cm.RdYlGn_r
norm = mcolors.Normalize(vmin=60, vmax=200)
pcm = ax.pcolormesh(x_edges, y_edges, grid, cmap=cmap, norm=norm, shading='flat')

cbar = plt.colorbar(pcm, ax=ax, orientation='vertical', pad=0.02)
cbar.set_label('Glucose (mg/dL)', fontsize=11)
# 目標範囲ラインをカラーバーに表示
for val in [70, 140]:
    cbar.ax.axhline(y=val, color='white', linewidth=1.5, alpha=0.8)

ax.set_xlabel('Hour of Day', fontsize=12, fontweight='bold')
ax.set_ylabel('Date', fontsize=12, fontweight='bold')
ax.set_title('Glucose Heatmap (Time × Date)', fontsize=13, pad=12, loc='left', fontweight='bold')
ax.set_xlim(0, 24)
ax.set_xticks([0, 3, 6, 9, 12, 15, 18, 21, 24])
ax.set_xticklabels(['0:00', '3:00', '6:00', '9:00', '12:00', '15:00', '18:00', '21:00', '24:00'])
ax.set_yticks(np.arange(n_days) + 0.5)
ax.set_yticklabels([str(d)[5:] for d in dates_sorted])

ax.set_facecolor(bg_color)
fig.patch.set_facecolor(bg_color)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'cgm_heatmap.png', dpi=150, facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_heatmap.png 保存")

# ========== PLOT 4: TIR積み上げ棒グラフ ==========
print("4. TIR日別積み上げ棒グラフを作成中...")

fig, ax = plt.subplots(figsize=(12, 6))

tir_cols = ['very_low_pct', 'low_pct', 'tir_pct', 'high_pct', 'very_high_pct']
tir_colors = [COLOR_VERY_LOW, COLOR_LOW, COLOR_TARGET, COLOR_HIGH, COLOR_VERY_HIGH]
tir_labels = ['Very Low (<54)', 'Low (54-69)', 'Target (70-140)', 'High (141-180)', 'Very High (>180)']

x = np.arange(len(daily_df))
bottom = np.zeros(len(daily_df))

for col, color, label in zip(tir_cols, tir_colors, tir_labels):
    vals = daily_df[col].values
    ax.bar(x, vals, bottom=bottom, color=color, label=label, edgecolor='black', linewidth=0.3)
    for i, (v, b) in enumerate(zip(vals, bottom)):
        if v >= 5:
            ax.text(i, b + v / 2, f'{v:.0f}%', ha='center', va='center',
                    fontsize=9, color='white', fontweight='bold')
    bottom += vals

ax.axhline(70, color='white', linewidth=1.5, linestyle='--', alpha=0.6, label='TIR 70% goal')
ax.set_xlabel('Date', fontsize=12, fontweight='bold')
ax.set_ylabel('Time in Range (%)', fontsize=12, fontweight='bold')
ax.set_title('Time in Range by Day', fontsize=13, pad=12, loc='left', fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels([str(d)[5:] for d in daily_df['date']])
ax.set_ylim(0, 100)
ax.legend(loc='upper right', framealpha=0.8)
ax.grid(True, alpha=0.2, axis='y')
ax.set_facecolor(bg_color)
fig.patch.set_facecolor(bg_color)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'cgm_tir.png', dpi=150, facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_tir.png 保存")

# ========== PLOT 5: 分布ヒストグラム ==========
print("5. 分布ヒストグラムを作成中...")

fig, ax = plt.subplots(figsize=(10, 6))

bins = np.arange(int(min_g) - 5, int(max_g) + 10, 5)

ranges = [
    (cgm_df[cgm_df['glucose'] < 54]['glucose'], COLOR_VERY_LOW, 'Very Low (<54)'),
    (cgm_df[(cgm_df['glucose'] >= 54) & (cgm_df['glucose'] < 70)]['glucose'], COLOR_LOW, 'Low (54-69)'),
    (cgm_df[(cgm_df['glucose'] >= 70) & (cgm_df['glucose'] <= 140)]['glucose'], COLOR_TARGET, 'Target (70-140)'),
    (cgm_df[(cgm_df['glucose'] > 140) & (cgm_df['glucose'] <= 180)]['glucose'], COLOR_HIGH, 'High (141-180)'),
    (cgm_df[cgm_df['glucose'] > 180]['glucose'], COLOR_VERY_HIGH, 'Very High (>180)'),
]

for data, color, label in ranges:
    if len(data) > 0:
        ax.hist(data, bins=bins, color=color, alpha=0.8, edgecolor='black', linewidth=0.3, label=label)

ax.axvline(mean_g, color='white', linewidth=2, linestyle='-', label=f'Mean: {mean_g:.1f}')
ax.axvline(median_g, color='yellow', linewidth=2, linestyle='--', label=f'Median: {median_g:.1f}')

stats_text = (
    f'Mean:   {mean_g:.1f} mg/dL\n'
    f'Median: {median_g:.1f} mg/dL\n'
    f'SD:     {sd_g:.1f} mg/dL\n'
    f'CV:     {cv_g:.1f}%\n'
    f'IQR:    {iqr_g:.1f} mg/dL\n'
    f'GMI:    {gmi:.2f}%\n'
    f'HbA1c:  {hba1c_est:.2f}%\n'
    f'n:      {n_total}'
)
ax.text(0.97, 0.95, stats_text, transform=ax.transAxes,
        verticalalignment='top', horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='black', alpha=0.7, edgecolor='gray'),
        fontsize=10, fontfamily='monospace')

ax.set_xlabel('Glucose (mg/dL)', fontsize=12, fontweight='bold')
ax.set_ylabel('Count', fontsize=12, fontweight='bold')
ax.set_title('Glucose Distribution', fontsize=13, pad=12, loc='left', fontweight='bold')
ax.legend(loc='upper left', framealpha=0.8)
ax.grid(True, alpha=0.2)
ax.set_facecolor(bg_color)
fig.patch.set_facecolor(bg_color)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'cgm_distribution.png', dpi=150, facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_distribution.png 保存")

# ========== Markdownレポート ==========
print("\nMarkdownレポートを作成中...")

period_days = (cgm_df['timestamp'].max() - cgm_df['timestamp'].min()).total_seconds() / 86400

daily_table_rows = []
for _, row in daily_df.iterrows():
    daily_table_rows.append(
        f'| {str(row["date"])[5:]} | {row["mean"]:.1f} | {row["median"]:.1f} | '
        f'{int(row["min"])} | {int(row["max"])} | {row["sd"]:.1f} | {row["cv"]:.1f} | '
        f'{row["tir_pct"]:.1f} | {row["n"]} |'
    )
daily_table_str = '\n'.join(daily_table_rows)

cv_label = '✅ 安定 (<36%)' if cv_g < 36 else '⚠️ 変動あり (≥36%)'
tir_label = '✅ 良好 (≥70%)' if tir_target >= 70 else '⚠️ 改善余地あり (<70%)'

report = f"""# CGM基本統計分析

**分析期間**: {cgm_df['timestamp'].min().strftime('%Y-%m-%d %H:%M')} ～ {cgm_df['timestamp'].max().strftime('%Y-%m-%d %H:%M')}（約{period_days:.1f}日間）
**デバイス**: Dexcom G7
**データポイント**: EGV {n_total}件（5分間隔）

---

## 全体サマリー

### 基本統計

| 指標 | 値 |
|------|-----|
| 平均血糖値 | {mean_g:.1f} mg/dL |
| 中央値 | {median_g:.1f} mg/dL |
| 標準偏差 (SD) | {sd_g:.1f} mg/dL |
| 変動係数 (CV) | {cv_g:.1f}% {cv_label} |
| 最小値 | {min_g:.0f} mg/dL |
| 最大値 | {max_g:.0f} mg/dL |
| IQR | {iqr_g:.1f} mg/dL |
| GMI | {gmi:.2f}% |
| 推定HbA1c | {hba1c_est:.2f}% |

### TIR (Time in Range)

| 範囲 | 閾値 | 割合 |
|------|------|------|
| 非常に低い | <54 mg/dL | {tir_very_low:.1f}% |
| 低い | 54-69 mg/dL | {tir_low:.1f}% |
| **目標** | **70-140 mg/dL** | **{tir_target:.1f}%** {tir_label} |
| 高い | 141-180 mg/dL | {tir_high:.1f}% |
| 非常に高い | >180 mg/dL | {tir_very_high:.1f}% |

---

## 日別統計

| 日付 | 平均 | 中央値 | 最小 | 最大 | SD | CV(%) | TIR(%) | n |
|------|------|--------|------|------|----|-------|--------|---|
{daily_table_str}

---

## 可視化

### 1. 血糖値時系列

![CGM血糖値時系列](cgm_timeseries.png)

全期間の血糖値推移。ティール帯=目標範囲(70-140)、金色縦線=食事イベント、紫縦線=活動イベント。

### 2. AGP日内プロファイル

![AGP日内プロファイル](cgm_daily_profile.png)

24時間軸に全日オーバーレイ。赤線=中央値、濃い帯=25-75パーセンタイル、薄い帯=10-90パーセンタイル。

### 3. 血糖値ヒートマップ

![血糖値ヒートマップ](cgm_heatmap.png)

X軸=時刻、Y軸=日付、色=血糖値（赤=高、黄=中、緑=低）。カラーバーの白線=目標範囲境界(70/140)。

### 4. TIR日別グラフ

![TIR日別積み上げ棒グラフ](cgm_tir.png)

日ごとの各範囲の割合積み上げ棒グラフ。白破線=TIR 70%推奨ライン。

### 5. 血糖値分布

![血糖値分布ヒストグラム](cgm_distribution.png)

範囲別に色分けしたヒストグラム。右上テキストボックスに統計サマリー。

---

## 解釈

### 血糖コントロール評価

- **CV {cv_g:.1f}%**: {'血糖変動が安定している（36%未満が推奨）' if cv_g < 36 else '血糖変動がやや大きい（36%以上は変動リスク）'}
- **GMI {gmi:.2f}%**: CGMデータから推定したHbA1c相当値（長期平均血糖の指標）
- **TIR(70-140) {tir_target:.1f}%**: {'目標範囲内の時間が十分（70%以上が推奨）' if tir_target >= 70 else '目標範囲をさらに拡大することが望ましい（推奨: 70%以上）'}

### 注意事項

- 分析期間は約{period_days:.1f}日間（短期間）のため、長期的なトレンドとは異なる可能性がある
- センサー装着開始直後（2/15夕方）のデータを含むため、精度に影響がある場合がある
- 食事・活動ログは手動入力のため、実際のタイミングと若干のズレがある可能性がある

---

*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Script: analyze_cgm_basic.py*
"""

with open(OUTPUT_DIR / 'ANALYSIS.md', 'w', encoding='utf-8') as f:
    f.write(report)
print("レポートを保存しました: ANALYSIS.md")

print("\n分析完了!")
print(f"出力先: {OUTPUT_DIR}")
print("生成ファイル:")
for fname in ['cgm_timeseries.png', 'cgm_daily_profile.png', 'cgm_heatmap.png', 'cgm_tir.png', 'cgm_distribution.png', 'ANALYSIS.md']:
    print(f"  - {fname}")
