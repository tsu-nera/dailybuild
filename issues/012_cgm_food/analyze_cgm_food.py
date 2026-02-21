#!/usr/bin/env python3
"""CGM × Nutrition Analysis - Dexcom G7 + Cronometer data"""

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
import numpy as np
from datetime import datetime, timedelta
from scipy import stats

OUTPUT_DIR = Path(__file__).parent
PROJECT_ROOT = Path(__file__).parent.parent.parent

# ========== Style ==========
bg_color = '#1a1a1a'
color_glucose = '#FF6B6B'
color_target = '#4ECDC4'
color_meal = '#FFD700'
color_carbs = '#FF8C69'
color_protein = '#7EB5F0'
color_fat = '#F5D76E'
color_fiber = '#7DCD85'
color_sugars = '#FF6B9D'

plt.style.use('dark_background')

# ========== Data Loading ==========
print("Loading data...")

raw_df = pd.read_csv(
    PROJECT_ROOT / 'data/dexcom.csv',
    skiprows=range(1, 11)
)

cgm_df = raw_df[raw_df['イベント タイプ'] == 'EGV'].copy()
cgm_df['timestamp'] = pd.to_datetime(cgm_df['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
cgm_df['glucose'] = pd.to_numeric(cgm_df['グルコース値 (mg/dL)'], errors='coerce')
cgm_df = cgm_df[['timestamp', 'glucose']].dropna().sort_values('timestamp').reset_index(drop=True)
cgm_df['date'] = cgm_df['timestamp'].dt.date

meal_df_raw = raw_df[raw_df['イベント タイプ'] == '食事'].copy()
meal_df_raw = meal_df_raw[
    meal_df_raw['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'].notna() &
    (meal_df_raw['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'] != '')
].copy()
if not meal_df_raw.empty:
    meal_df_raw['timestamp'] = pd.to_datetime(meal_df_raw['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
    meal_df_raw['carbs'] = pd.to_numeric(meal_df_raw['炭水化物値 (グラム)'], errors='coerce')
meal_df = meal_df_raw.copy()

nut_df = pd.read_csv(PROJECT_ROOT / 'data/cronometer.csv')
nut_df['date'] = pd.to_datetime(nut_df['Date']).dt.date
nut_df = nut_df.rename(columns={
    'Energy (kcal)': 'energy',
    'Carbs (g)': 'carbs',
    'Fiber (g)': 'fiber',
    'Sugars (g)': 'sugars',
    'Net Carbs (g)': 'net_carbs',
    'Fat (g)': 'fat',
    'Protein (g)': 'protein',
    'Added Sugars (g)': 'added_sugars',
    'Completed': 'completed',
})

print(f"EGV: {len(cgm_df)} readings, {cgm_df['date'].nunique()} days")
print(f"Meal events: {len(meal_df)}")
print(f"Nutrition days: {len(nut_df)}")

# ========== Daily Glucose Stats ==========
def compute_daily_glucose_stats(df):
    rows = []
    for date, group in df.groupby('date'):
        g = group['glucose']
        mean_g = g.mean()
        sd_g = g.std()
        rows.append({
            'date': date,
            'mean': mean_g,
            'median': g.median(),
            'min': g.min(),
            'max': g.max(),
            'sd': sd_g,
            'cv': (sd_g / mean_g * 100) if mean_g > 0 else 0,
            'tir_pct': ((g >= 70) & (g <= 140)).mean() * 100,
            'high_pct': (g > 140).mean() * 100,
            'n': len(g),
        })
    return pd.DataFrame(rows)

daily_glucose = compute_daily_glucose_stats(cgm_df)

# ========== Merge ==========
overlap_start = pd.to_datetime('2026-02-15').date()
full_days = [pd.to_datetime(f'2026-02-{d:02d}').date() for d in range(16, 21)]

merged = pd.merge(
    daily_glucose[daily_glucose['date'] >= overlap_start],
    nut_df[['date', 'energy', 'carbs', 'fiber', 'sugars', 'net_carbs',
            'fat', 'protein', 'added_sugars', 'completed']],
    on='date', how='inner'
).sort_values('date').reset_index(drop=True)

merged_full = merged[merged['date'].isin(full_days)].copy().reset_index(drop=True)

print(f"Merged overlap days: {len(merged)}")
print(f"Full days for analysis: {len(merged_full)}")

# ========== Post-Meal Windows ==========
post_meal_info = []
post_meal_windows = []
if not meal_df.empty:
    colors_pm = ['#FF6B6B', '#FFD700', '#7EB5F0']
    for i, (_, mrow) in enumerate(meal_df.iterrows()):
        meal_time = mrow['timestamp']
        start_time = meal_time - timedelta(minutes=30)
        end_time = meal_time + timedelta(minutes=120)
        window = cgm_df[(cgm_df['timestamp'] >= start_time) & (cgm_df['timestamp'] <= end_time)].copy()
        if not window.empty:
            window['minutes_from_meal'] = (window['timestamp'] - meal_time).dt.total_seconds() / 60
            window['meal_carbs'] = mrow['carbs']
            window['meal_label'] = (
                f"{str(meal_time.date())[5:]} {meal_time.strftime('%H:%M')} "
                f"({int(mrow['carbs'])}g carbs)"
            )
            window['color'] = colors_pm[i % len(colors_pm)]
            post_meal_windows.append(window)
            post_meal_info.append({
                'time': meal_time,
                'carbs': mrow['carbs'],
                'peak': window['glucose'].max(),
                'minutes_to_peak': window.loc[window['glucose'].idxmax(), 'minutes_from_meal'],
            })

# ========== PLOT 1: Daily Overview ==========
print("\n1. Daily Overview...")

fig = plt.figure(figsize=(14, 12))
gs = gridspec.GridSpec(3, 1, hspace=0.45)
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1])
ax3 = fig.add_subplot(gs[2])

x = np.arange(len(merged))
dates_str = [str(d)[5:] for d in merged['date']]
width = 0.6

# Panel 1: Macros stacked bar (kcal)
carbs_kcal = merged['carbs'] * 4
protein_kcal = merged['protein'] * 4
fat_kcal = merged['fat'] * 9
ax1.bar(x, carbs_kcal, width, label='Carbs', color=color_carbs, alpha=0.85)
ax1.bar(x, protein_kcal, width, bottom=carbs_kcal, label='Protein', color=color_protein, alpha=0.85)
ax1.bar(x, fat_kcal, width, bottom=carbs_kcal + protein_kcal, label='Fat', color=color_fat, alpha=0.85)
ax1.set_title('Daily Macronutrient Intake (kcal)', fontsize=11, fontweight='bold', loc='left')
ax1.set_ylabel('Energy (kcal)', fontsize=9)
ax1.set_xticks(x)
ax1.set_xticklabels(dates_str, fontsize=9)
ax1.legend(loc='upper right', fontsize=8, framealpha=0.7)
ax1.grid(True, alpha=0.2, axis='y')
ax1.set_facecolor(bg_color)
for i, row in merged.iterrows():
    if not row.get('completed', True):
        ax1.text(i, 50, '*', color='orange', fontsize=14, ha='center')

# Panel 2: Glucose mean ± full range
err_low = merged['mean'] - merged['min']
err_high = merged['max'] - merged['mean']
ax2.bar(x, merged['mean'], width, color=color_glucose, alpha=0.7, label='Mean Glucose')
ax2.errorbar(x, merged['mean'], yerr=[err_low, err_high],
             fmt='none', color='white', capsize=5, linewidth=1.5, alpha=0.6)
ax2.axhline(70, color=color_target, linewidth=1, linestyle='--', alpha=0.5)
ax2.axhline(140, color=color_target, linewidth=1, linestyle='--', alpha=0.5)
ax2.axhspan(70, 140, color=color_target, alpha=0.05)
ax2.set_title('Daily Glucose Statistics (Mean ± Full Range)', fontsize=11, fontweight='bold', loc='left')
ax2.set_ylabel('Glucose (mg/dL)', fontsize=9)
ax2.set_xticks(x)
ax2.set_xticklabels(dates_str, fontsize=9)
ax2.grid(True, alpha=0.2, axis='y')
ax2.set_facecolor(bg_color)

# Panel 3: Fiber and Sugars
w = 0.35
ax3.bar(x - w / 2, merged['fiber'], w, label='Fiber', color=color_fiber, alpha=0.85)
ax3.bar(x + w / 2, merged['sugars'], w, label='Total Sugars', color=color_sugars, alpha=0.85)
ax3.set_title('Daily Fiber & Sugar Intake (g)', fontsize=11, fontweight='bold', loc='left')
ax3.set_ylabel('Amount (g)', fontsize=9)
ax3.set_xticks(x)
ax3.set_xticklabels(dates_str, fontsize=9)
ax3.set_xlabel('Date (MM-DD)', fontsize=10, fontweight='bold')
ax3.legend(loc='upper right', fontsize=8, framealpha=0.7)
ax3.grid(True, alpha=0.2, axis='y')
ax3.set_facecolor(bg_color)

fig.patch.set_facecolor(bg_color)
fig.suptitle('CGM × Nutrition Daily Overview', fontsize=14, fontweight='bold', y=0.99)
fig.text(0.01, 0.005, '* = incomplete Cronometer log', fontsize=8, color='orange', alpha=0.8)
plt.savefig(OUTPUT_DIR / 'cgm_food_daily_overview.png', dpi=150,
            facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_food_daily_overview.png")

# ========== PLOT 2: Scatter Plots ==========
print("2. Scatter plots...")

fig, axes = plt.subplots(2, 3, figsize=(16, 10))
axes = axes.flatten()

scatter_pairs = [
    ('carbs', 'mean', 'Carbs (g)', 'Mean Glucose (mg/dL)', color_carbs),
    ('protein', 'mean', 'Protein (g)', 'Mean Glucose (mg/dL)', color_protein),
    ('fat', 'mean', 'Fat (g)', 'Mean Glucose (mg/dL)', color_fat),
    ('fiber', 'mean', 'Fiber (g)', 'Mean Glucose (mg/dL)', color_fiber),
    ('sugars', 'mean', 'Sugars (g)', 'Mean Glucose (mg/dL)', color_sugars),
    ('energy', 'sd', 'Energy (kcal)', 'Glucose SD (mg/dL)', '#C39BD3'),
]

for ax, (x_col, y_col, x_label, y_label, color) in zip(axes, scatter_pairs):
    data = merged_full[[x_col, y_col, 'date']].dropna()
    if len(data) >= 3:
        x_vals = data[x_col].values
        y_vals = data[y_col].values
        ax.scatter(x_vals, y_vals, color=color, s=80, alpha=0.85, zorder=5)

        slope, intercept, r_val, p_val, _ = stats.linregress(x_vals, y_vals)
        x_line = np.linspace(x_vals.min(), x_vals.max(), 50)
        ax.plot(x_line, slope * x_line + intercept, color='white',
                linewidth=1.5, alpha=0.7, linestyle='--')

        for _, row in data.iterrows():
            ax.annotate(str(row['date'])[5:], (row[x_col], row[y_col]),
                        textcoords='offset points', xytext=(5, 3),
                        fontsize=7, color='gray', alpha=0.8)

        r_color = '#4ECDC4' if abs(r_val) >= 0.5 else 'white'
        p_str = f'p={p_val:.3f}' if p_val >= 0.001 else 'p<0.001'
        ax.text(0.05, 0.93, f'r={r_val:.2f}, {p_str}\n(n={len(data)})',
                transform=ax.transAxes, fontsize=9, color=r_color,
                bbox=dict(boxstyle='round', facecolor='black', alpha=0.5))
    else:
        ax.text(0.5, 0.5, 'Insufficient data', transform=ax.transAxes,
                ha='center', va='center', color='gray')

    ax.set_xlabel(x_label, fontsize=9, fontweight='bold')
    ax.set_ylabel(y_label, fontsize=9, fontweight='bold')
    x_title = x_label.split(' ')[0]
    y_title = y_label.split(' ')[0]
    ax.set_title(f'{x_title} vs {y_title} Glucose', fontsize=10, fontweight='bold')
    ax.grid(True, alpha=0.2)
    ax.set_facecolor(bg_color)

fig.patch.set_facecolor(bg_color)
fig.suptitle('Nutrient vs Glucose Correlations (Full Days: 02/16–02/20, n=5)',
             fontsize=13, fontweight='bold', y=0.99)
fig.text(0.5, 0.01, 'Exploratory only — small sample (n=5), interpret with caution',
         ha='center', fontsize=9, color='gray', style='italic')
plt.tight_layout(rect=[0, 0.03, 1, 0.97])
plt.savefig(OUTPUT_DIR / 'cgm_food_scatter.png', dpi=150,
            facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_food_scatter.png")

# ========== PLOT 3: Meal Timeline ==========
print("3. Meal timeline...")

overlap_dates = sorted(merged['date'].tolist())
n_days = len(overlap_dates)

fig, axes = plt.subplots(n_days, 1, figsize=(14, 3.5 * n_days), sharex=True)
if n_days == 1:
    axes = [axes]

fig.suptitle('CGM Glucose with Meal Events (Daily Timeline)', fontsize=13, fontweight='bold', y=1.01)

for ax, date in zip(axes, overlap_dates):
    day_data = cgm_df[cgm_df['date'] == date].copy()
    day_data['hour_float'] = day_data['timestamp'].dt.hour + day_data['timestamp'].dt.minute / 60

    gluc_row = daily_glucose[daily_glucose['date'] == date]
    nut_row = merged[merged['date'] == date]

    ax.axhspan(70, 140, color=color_target, alpha=0.08, zorder=0)
    ax.axhline(70, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)
    ax.axhline(140, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)

    if not day_data.empty:
        ax.plot(day_data['hour_float'], day_data['glucose'],
                color=color_glucose, linewidth=1.8, alpha=0.95)

    day_meals = meal_df[meal_df['timestamp'].dt.date == date] if not meal_df.empty else pd.DataFrame()
    for _, mrow in day_meals.iterrows():
        hf = mrow['timestamp'].hour + mrow['timestamp'].minute / 60
        ax.axvline(hf, color=color_meal, linewidth=2, alpha=0.9, zorder=5)
        ax.axvspan(hf, min(hf + 2, 24), color=color_meal, alpha=0.07, zorder=1)
        carb_str = f"{int(mrow['carbs'])}g" if pd.notna(mrow.get('carbs')) else ''
        ax.text(hf + 0.1, 195, f'Meal\n{carb_str}', color=color_meal,
                fontsize=7.5, va='top', fontweight='bold')

    gluc_str = ''
    nut_str = ''
    if not gluc_row.empty:
        r = gluc_row.iloc[0]
        gluc_str = f"Glucose: {r['mean']:.1f}±{r['sd']:.1f} mg/dL  TIR:{r['tir_pct']:.1f}%"
    if not nut_row.empty:
        n = nut_row.iloc[0]
        completed_flag = '✓' if n.get('completed', False) else '*'
        nut_str = f"C:{n['carbs']:.0f}g P:{n['protein']:.0f}g F:{n['fat']:.0f}g {completed_flag}"

    ax.set_title(f"{str(date)}  |  {gluc_str}  |  {nut_str}",
                 fontsize=9, pad=3, loc='left', fontweight='bold')
    ax.set_ylabel('mg/dL', fontsize=8)
    ax.set_ylim(60, 215)
    ax.grid(True, alpha=0.2)
    ax.set_facecolor(bg_color)

axes[-1].set_xlabel('Hour of Day', fontsize=11, fontweight='bold')
axes[-1].set_xlim(0, 24)
axes[-1].set_xticks([0, 3, 6, 9, 12, 15, 18, 21, 24])
axes[-1].set_xticklabels(['0:00', '3:00', '6:00', '9:00', '12:00',
                           '15:00', '18:00', '21:00', '24:00'])
axes[0].legend(handles=[
    plt.Line2D([0], [0], color=color_glucose, linewidth=2, label='Glucose (EGV)'),
    mpatches.Patch(color=color_target, alpha=0.3, label='Target (70–140 mg/dL)'),
    plt.Line2D([0], [0], color=color_meal, linewidth=2, label='Meal event'),
    mpatches.Patch(color=color_meal, alpha=0.15, label='Post-meal 2h window'),
], loc='upper right', framealpha=0.8, fontsize=8)

fig.text(0.01, -0.005, '* = incomplete Cronometer log  |  C=Carbs P=Protein F=Fat',
         fontsize=8, color='gray')
fig.patch.set_facecolor(bg_color)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'cgm_food_meal_timeline.png', dpi=150,
            facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_food_meal_timeline.png")

# ========== PLOT 4: Post-Meal Response ==========
print("4. Post-meal response...")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

if post_meal_windows:
    for window in post_meal_windows:
        color = window['color'].iloc[0]
        label = window['meal_label'].iloc[0]
        ax1.plot(window['minutes_from_meal'], window['glucose'],
                 color=color, linewidth=2.5, alpha=0.85, label=label)
        # Mark peak
        peak_idx = window['glucose'].idxmax()
        peak_time = window.loc[peak_idx, 'minutes_from_meal']
        peak_gluc = window.loc[peak_idx, 'glucose']
        ax1.annotate(f'Peak\n{peak_gluc:.0f}', (peak_time, peak_gluc),
                     textcoords='offset points', xytext=(5, 5),
                     color=color, fontsize=8, fontweight='bold')

ax1.axvline(0, color='white', linewidth=1.5, linestyle='--', alpha=0.5, label='Meal time')
ax1.axhspan(70, 140, color=color_target, alpha=0.07)
ax1.axhline(70, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)
ax1.axhline(140, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)
ax1.set_xlabel('Minutes from Meal', fontsize=11, fontweight='bold')
ax1.set_ylabel('Glucose (mg/dL)', fontsize=11, fontweight='bold')
ax1.set_title(f'Post-Meal Glucose Response (Case Study, n={len(post_meal_windows)})',
              fontsize=11, fontweight='bold', loc='left')
ax1.legend(loc='upper right', fontsize=8, framealpha=0.8)
ax1.grid(True, alpha=0.2)
ax1.set_facecolor(bg_color)
ax1.set_xlim(-35, 125)

if post_meal_info:
    carbs_list = [info['carbs'] for info in post_meal_info]
    peak_list = [info['peak'] for info in post_meal_info]
    scatter_colors = [colors_pm[i % len(colors_pm)] for i in range(len(post_meal_info))]
    ax2.scatter(carbs_list, peak_list, c=scatter_colors, s=150, zorder=5, alpha=0.9)
    for i, info in enumerate(post_meal_info):
        ax2.annotate(info['time'].strftime('%m/%d'), (info['carbs'], info['peak']),
                     textcoords='offset points', xytext=(8, 0),
                     color=scatter_colors[i], fontsize=9)
    if len(carbs_list) >= 2:
        slope, intercept, r_val, p_val, _ = stats.linregress(carbs_list, peak_list)
        x_line = np.linspace(min(carbs_list) - 5, max(carbs_list) + 5, 50)
        ax2.plot(x_line, slope * x_line + intercept, color='white',
                 linewidth=1.5, linestyle='--', alpha=0.6)
        p_str = f'p={p_val:.3f}' if p_val >= 0.001 else 'p<0.001'
        ax2.text(0.05, 0.93, f'r={r_val:.2f}, {p_str} (n={len(carbs_list)}, exploratory only)',
                 transform=ax2.transAxes, fontsize=9, color='gray',
                 bbox=dict(boxstyle='round', facecolor='black', alpha=0.5))

ax2.axhline(140, color=color_target, linewidth=0.8, linestyle='--', alpha=0.5, label='Target upper (140)')
ax2.set_xlabel('Meal Carbohydrates (g)', fontsize=11, fontweight='bold')
ax2.set_ylabel('Peak Post-Meal Glucose (mg/dL)', fontsize=11, fontweight='bold')
ax2.set_title('Carbohydrate Load vs Peak Glucose Response', fontsize=11, fontweight='bold', loc='left')
ax2.legend(fontsize=8, framealpha=0.8)
ax2.grid(True, alpha=0.2)
ax2.set_facecolor(bg_color)

fig.patch.set_facecolor(bg_color)
fig.suptitle('Post-Meal Glucose Response Analysis', fontsize=13, fontweight='bold')
fig.text(0.5, 0.01, f'n={len(post_meal_windows)} meal events — statistical conclusions not valid',
         ha='center', fontsize=9, color='orange', style='italic')
plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.savefig(OUTPUT_DIR / 'cgm_food_postmeal.png', dpi=150,
            facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_food_postmeal.png")

# ========== PLOT 5: Correlation Heatmap ==========
print("5. Correlation heatmap...")

nutrient_cols = ['energy', 'carbs', 'fiber', 'sugars', 'net_carbs', 'fat', 'protein']
glucose_cols = ['mean', 'sd', 'cv', 'tir_pct', 'high_pct']
nut_labels = ['Energy', 'Carbs', 'Fiber', 'Sugars', 'Net Carbs', 'Fat', 'Protein']
gluc_labels = ['Mean\nGlucose', 'Glucose\nSD', 'Glucose\nCV', 'TIR\n(%)', 'High\n(%)']

corr_matrix = np.full((len(nutrient_cols), len(glucose_cols)), np.nan)
for i, nc in enumerate(nutrient_cols):
    for j, gc in enumerate(glucose_cols):
        data = merged_full[[nc, gc]].dropna()
        if len(data) >= 3:
            r, _ = stats.pearsonr(data[nc], data[gc])
            corr_matrix[i, j] = r

fig, ax = plt.subplots(figsize=(10, 8))
from matplotlib.colors import TwoSlopeNorm
norm = TwoSlopeNorm(vmin=-1, vcenter=0, vmax=1)
im = ax.imshow(corr_matrix, cmap='RdBu_r', norm=norm, aspect='auto')
cbar = plt.colorbar(im, ax=ax, pad=0.02)
cbar.set_label('Pearson r', fontsize=11)

ax.set_xticks(range(len(gluc_labels)))
ax.set_xticklabels(gluc_labels, fontsize=10)
ax.set_yticks(range(len(nut_labels)))
ax.set_yticklabels(nut_labels, fontsize=10)

for i in range(len(nutrient_cols)):
    for j in range(len(glucose_cols)):
        val = corr_matrix[i, j]
        if not np.isnan(val):
            text_color = 'white' if abs(val) > 0.5 else 'black'
            ax.text(j, i, f'{val:.2f}', ha='center', va='center',
                    fontsize=10, fontweight='bold', color=text_color)

ax.set_title('Nutrient × Glucose Metric Correlations\n(Full Days: 02/16–02/20, n=5)',
             fontsize=12, fontweight='bold', pad=15)
ax.set_xlabel('Glucose Metrics', fontsize=11, fontweight='bold')
ax.set_ylabel('Nutrients', fontsize=11, fontweight='bold')
ax.set_facecolor(bg_color)
fig.patch.set_facecolor(bg_color)
fig.text(0.5, 0.01, 'Exploratory Pearson r — small sample (n=5), not statistically conclusive',
         ha='center', fontsize=8, color='gray', style='italic')
plt.tight_layout(rect=[0, 0.04, 1, 1])
plt.savefig(OUTPUT_DIR / 'cgm_food_correlation.png', dpi=150,
            facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_food_correlation.png")

# ========== PLOT 6: Macro Ratio ==========
print("6. Macro ratio...")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))

# Macro calorie ratio stacked horizontal bars
carbs_ratio = merged['carbs'] * 4 / merged['energy'] * 100
protein_ratio = merged['protein'] * 4 / merged['energy'] * 100
fat_ratio = merged['fat'] * 9 / merged['energy'] * 100
y = np.arange(len(merged))
dates_str_h = [str(d)[5:] for d in merged['date']]

ax1.barh(y, carbs_ratio, color=color_carbs, alpha=0.85, label='Carbs')
ax1.barh(y, protein_ratio, left=carbs_ratio, color=color_protein, alpha=0.85, label='Protein')
ax1.barh(y, fat_ratio, left=carbs_ratio + protein_ratio, color=color_fat, alpha=0.85, label='Fat')
ax1.set_yticks(y)
ax1.set_yticklabels(dates_str_h, fontsize=10)
ax1.set_xlabel('% of Total Energy', fontsize=11, fontweight='bold')
ax1.set_title('Daily Macronutrient Calorie Ratio', fontsize=11, fontweight='bold', loc='left')
ax1.legend(loc='lower right', fontsize=9, framealpha=0.8)
ax1.set_xlim(0, 102)
ax1.grid(True, alpha=0.2, axis='x')
ax1.set_facecolor(bg_color)

# Add % labels inside bars
for i in range(len(merged)):
    vals = [carbs_ratio.iloc[i], protein_ratio.iloc[i], fat_ratio.iloc[i]]
    lefts = [0, carbs_ratio.iloc[i], carbs_ratio.iloc[i] + protein_ratio.iloc[i]]
    for v, l in zip(vals, lefts):
        if v >= 8:
            ax1.text(l + v / 2, i, f'{v:.0f}%', ha='center', va='center',
                     fontsize=8, color='white', fontweight='bold')

# Fiber/Carb ratio vs Mean Glucose bubble chart
if len(merged_full) >= 3:
    fiber_carb_ratio = merged_full['fiber'] / merged_full['carbs']
    mean_glucose = merged_full['mean']
    energy = merged_full['energy']
    bubble_size = (energy / energy.max()) * 500

    scatter = ax2.scatter(fiber_carb_ratio, mean_glucose, s=bubble_size,
                          c=merged_full['carbs'], cmap='YlOrRd',
                          alpha=0.8, edgecolors='white', linewidth=1, zorder=5)
    cbar = plt.colorbar(scatter, ax=ax2)
    cbar.set_label('Carbs (g)', fontsize=9)

    for i, row in merged_full.iterrows():
        ax2.annotate(str(row['date'])[5:],
                     (fiber_carb_ratio.loc[i], row['mean']),
                     textcoords='offset points', xytext=(8, 0),
                     fontsize=8, color='white', alpha=0.8)

    slope, intercept, r_val, p_val, _ = stats.linregress(
        fiber_carb_ratio.values, mean_glucose.values
    )
    x_line = np.linspace(fiber_carb_ratio.min(), fiber_carb_ratio.max(), 50)
    ax2.plot(x_line, slope * x_line + intercept, color='white',
             linewidth=1.5, linestyle='--', alpha=0.6)
    p_str = f'p={p_val:.3f}' if p_val >= 0.001 else 'p<0.001'
    ax2.text(0.05, 0.93, f'r={r_val:.2f}, {p_str} (n={len(merged_full)})',
             transform=ax2.transAxes, fontsize=9, color='white',
             bbox=dict(boxstyle='round', facecolor='black', alpha=0.5))

ax2.axhspan(70, 140, color=color_target, alpha=0.05)
ax2.axhline(70, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)
ax2.axhline(140, color=color_target, linewidth=0.8, linestyle='--', alpha=0.4)
ax2.set_xlabel('Fiber / Carb Ratio', fontsize=11, fontweight='bold')
ax2.set_ylabel('Mean Glucose (mg/dL)', fontsize=11, fontweight='bold')
ax2.set_title('Fiber-to-Carb Ratio vs Mean Glucose\n(bubble size = total energy)',
              fontsize=11, fontweight='bold', loc='left')
ax2.grid(True, alpha=0.2)
ax2.set_facecolor(bg_color)

fig.patch.set_facecolor(bg_color)
fig.suptitle('Macronutrient Ratio Analysis', fontsize=13, fontweight='bold')
plt.tight_layout()
plt.savefig(OUTPUT_DIR / 'cgm_food_macro_ratio.png', dpi=150,
            facecolor=bg_color, edgecolor='none', bbox_inches='tight')
plt.close()
print("  -> cgm_food_macro_ratio.png")

# ========== ANALYSIS.md ==========
print("\nGenerating ANALYSIS.md...")

nutrient_table_rows = []
for _, row in merged.iterrows():
    flag = '✓' if row.get('completed', False) else '*'
    nutrient_table_rows.append(
        f"| {str(row['date'])[5:]} {flag} | {row['energy']:.0f} | {row['carbs']:.1f} | "
        f"{row['protein']:.1f} | {row['fat']:.1f} | {row['fiber']:.1f} | {row['sugars']:.1f} |"
    )

glucose_table_rows = []
for _, row in merged.iterrows():
    glucose_table_rows.append(
        f"| {str(row['date'])[5:]} | {row['mean']:.1f} | {row['sd']:.1f} | "
        f"{row['cv']:.1f} | {row['tir_pct']:.1f} | {int(row['min'])} | {int(row['max'])} | {row['n']} |"
    )

# Top correlations
top_corrs = []
for i, nc in enumerate(nutrient_cols):
    for j, gc in enumerate(glucose_cols):
        val = corr_matrix[i, j]
        if not np.isnan(val) and abs(val) >= 0.3:
            top_corrs.append((abs(val), nut_labels[i], gluc_labels[j].replace('\n', ' '), val))
top_corrs.sort(reverse=True)

corr_lines = []
for _, nut, gluc, r in top_corrs[:6]:
    direction = '正の' if r > 0 else '負の'
    corr_lines.append(f"- **{nut} ↔ {gluc}**: r={r:.2f}（{direction}相関）")
corr_text = '\n'.join(corr_lines) if corr_lines else "- 顕著な相関なし（全て |r| < 0.3）"

postmeal_table_rows = []
for i, info in enumerate(post_meal_info):
    postmeal_table_rows.append(
        f"| {i+1} | {info['time'].strftime('%m/%d %H:%M')} | {int(info['carbs'])} | "
        f"{info['peak']:.0f} | {info['minutes_to_peak']:.0f} |"
    )
postmeal_table = '\n'.join(postmeal_table_rows)

report = f"""# CGM × 栄養素分析

**分析日**: {datetime.now().strftime('%Y-%m-%d')}
**期間**: 2026-02-15 〜 2026-02-21（CGM + Cronometer 重複期間）
**CGMデバイス**: Dexcom G7
**栄養ログ**: Cronometer

---

## データ概要

| 項目 | 内容 |
|------|------|
| CGMデータ | EGV {len(cgm_df)}件（5分間隔） |
| 食事イベント（Dexcom記録） | {len(meal_df)}件 |
| 栄養ログ日数（重複期間） | {len(merged)}日 |
| 完全日（散布図・相関分析用） | 5日間（02/16〜02/20、CGM + 栄養ログ完備） |

**注意事項:**
- 部分的CGM日（02/15 センサー装着開始、02/21 部分記録）: 日次概要チャートに含めるが、散布図・相関分析からは除外
- Cronometer 未完了ログ（*）: チャートには含めるが、テーブルにフラグ表示
- 相関分析は n=5 のため探索的。統計的結論は得られない

---

## 日次栄養素サマリー

| 日付 | エネルギー (kcal) | 炭水化物 (g) | タンパク質 (g) | 脂質 (g) | 食物繊維 (g) | 糖質 (g) |
|------|------------------|-------------|----------------|---------|------------|---------|
{chr(10).join(nutrient_table_rows)}

*✓ = 記録完了、* = 未完了ログ*

---

## 日次血糖値サマリー

| 日付 | 平均 | SD | CV (%) | TIR (%) | 最小 | 最大 | n |
|------|------|-----|--------|---------|------|------|---|
{chr(10).join(glucose_table_rows)}

*TIR = 目標範囲内時間（70〜140 mg/dL）*

---

## チャート

### 1. 日次概要
![日次概要](cgm_food_daily_overview.png)

3パネル構成: 上=マクロ栄養素摂取量（kcal積み上げ棒）、中=日次血糖値統計（mean ± 全範囲）、下=食物繊維・糖質摂取量。

### 2. 栄養素 × 血糖値 散布図
![散布図](cgm_food_scatter.png)

6散布図（回帰線・Pearson r付き）。完全日のみ（02/16〜02/20、n=5）。ティール色のr値は |r| ≥ 0.5 を示す。

### 3. 食事タイムライン
![食事タイムライン](cgm_food_meal_timeline.png)

日別血糖値カーブにDexcom記録の食事イベントマーカー（金色縦線）と食後2時間ウィンドウを重ねて表示。

### 4. 食後血糖応答
![食後血糖応答](cgm_food_postmeal.png)

左: 食事前30分〜食事後120分の血糖値応答曲線（n={len(post_meal_windows)}件のケーススタディ）。右: 炭水化物量 vs ピーク血糖値。

### 5. 相関ヒートマップ
![相関ヒートマップ](cgm_food_correlation.png)

栄養素7項目 × 血糖指標5項目のPearson r ヒートマップ（RdBu_r: 赤=正、青=負）。完全日のみ（n=5）。

### 6. マクロ栄養素比率分析
![マクロ比率](cgm_food_macro_ratio.png)

左: 日次マクロ栄養素カロリー比率（積み上げ横棒）。右: 食物繊維/炭水化物比 vs 平均血糖値（バブルサイズ=総エネルギー、色=炭水化物量）。

---

## 主要知見

### 相関分析（探索的、n=5）
{corr_text}

### 食後血糖応答（{len(post_meal_info)}件）

| # | 食事時刻 | 炭水化物 (g) | ピーク血糖 (mg/dL) | ピークまでの分数 |
|---|---------|-------------|------------------|----------------|
{postmeal_table}

---

## 制限事項

1. **サンプル数が少ない**: 相関分析はn=5日間のみ — 統計的結論は得られない
2. **食事イベントが{len(meal_df)}件のみ**: Dexcomに記録された食事が少なく、食後分析はケーススタディとして提示
3. **Cronometer未完了ログ**（Completed=false）: 実際の摂取量を過小評価している可能性がある
4. **部分的CGM日の除外**: 02/15（センサー装着開始）・02/21（部分記録）は散布図・相関から除外
5. **Cronometer日次集計に食事時刻がない**: {len(meal_df)}件のDexcom食事ログを除き、特定の食事とCGMスパイクの紐付けが困難
6. **交絡因子の未制御**: 運動・ストレス・睡眠の質・センサー較正誤差等が血糖値に影響する

---

*生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*スクリプト: analyze_cgm_food.py*
"""

with open(OUTPUT_DIR / 'ANALYSIS.md', 'w', encoding='utf-8') as f:
    f.write(report)
print("  -> ANALYSIS.md")

print("\nDone!")
print(f"Output: {OUTPUT_DIR}")
for fname in ['cgm_food_daily_overview.png', 'cgm_food_scatter.png', 'cgm_food_meal_timeline.png',
              'cgm_food_postmeal.png', 'cgm_food_correlation.png', 'cgm_food_macro_ratio.png', 'ANALYSIS.md']:
    fpath = OUTPUT_DIR / fname
    status = '✓' if fpath.exists() else '✗'
    print(f"  {status} {fname}")
