#!/usr/bin/env python3
"""睡眠中の高度な心拍数指標分析スクリプト

研究に基づく新しい心拍数指標:
1. 夜間心拍数ディップ率（Nocturnal HR Dip）
2. 入眠から最低心拍数までの時間
3. 最低心拍数の発生時刻
4. 睡眠効率との相関
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import numpy as np

# 日本語フォント設定
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial']
plt.rcParams['axes.unicode_minus'] = False

# データ読み込み
sleep_df = pd.read_csv('/home/tsu-nera/repo/dailybuild/data/fitbit/sleep.csv')
hr_intraday_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/data/fitbit/heart_rate_intraday.csv',
    parse_dates=['datetime']
)
hr_daily_df = pd.read_csv('/home/tsu-nera/repo/dailybuild/data/fitbit/heart_rate.csv')

# 最近のデータを分析（過去30日間）
end_date = datetime.now().date()
start_date = end_date - timedelta(days=30)

sleep_df['dateOfSleep'] = pd.to_datetime(sleep_df['dateOfSleep'])
recent_sleep = sleep_df[
    (sleep_df['dateOfSleep'].dt.date >= start_date) &
    (sleep_df['dateOfSleep'].dt.date <= end_date)
].copy()

print(f"分析期間: {start_date} ～ {end_date}")
print(f"対象睡眠記録: {len(recent_sleep)}件\n")

# 各睡眠記録について指標を計算
results = []

for idx, sleep_record in recent_sleep.iterrows():
    date = sleep_record['dateOfSleep'].strftime('%Y-%m-%d')

    # 安静時心拍数を取得
    resting_hr_data = hr_daily_df[hr_daily_df['date'] == date]
    if len(resting_hr_data) == 0:
        continue

    resting_hr = int(resting_hr_data['resting_heart_rate'].iloc[0])

    # 睡眠時間帯を取得
    sleep_start = pd.to_datetime(sleep_record['startTime'])
    sleep_end = pd.to_datetime(sleep_record['endTime'])

    # 日中の平均心拍数を計算（6:00-22:00）
    day_start = sleep_start.replace(hour=6, minute=0, second=0)
    day_end = sleep_start.replace(hour=22, minute=0, second=0)

    day_hr = hr_intraday_df[
        (hr_intraday_df['datetime'] >= day_start) &
        (hr_intraday_df['datetime'] < day_end)
    ]

    if len(day_hr) == 0:
        continue

    avg_day_hr = day_hr['heart_rate'].mean()

    # 睡眠時間帯の心拍数データを抽出
    sleep_hr = hr_intraday_df[
        (hr_intraday_df['datetime'] >= sleep_start) &
        (hr_intraday_df['datetime'] <= sleep_end)
    ].copy()

    if len(sleep_hr) == 0:
        continue

    # 指標1: 夜間心拍数ディップ率
    min_sleep_hr = sleep_hr['heart_rate'].min()
    avg_sleep_hr = sleep_hr['heart_rate'].mean()

    # 日中平均心拍数との比較
    dip_rate_avg = ((avg_day_hr - avg_sleep_hr) / avg_day_hr) * 100
    dip_rate_min = ((avg_day_hr - min_sleep_hr) / avg_day_hr) * 100
    night_day_ratio = avg_sleep_hr / avg_day_hr

    # 指標2: 入眠から最低心拍数までの時間
    min_hr_idx = sleep_hr['heart_rate'].idxmin()
    min_hr_time = sleep_hr.loc[min_hr_idx, 'datetime']
    time_to_min_hr = (min_hr_time - sleep_start).total_seconds() / 60  # 分単位

    # 指標3: 最低心拍数の発生時刻
    min_hr_clock_time = min_hr_time.strftime('%H:%M')

    # 指標4: 睡眠効率
    minutes_asleep = sleep_record['minutesAsleep']
    time_in_bed = sleep_record['timeInBed']
    sleep_efficiency = (minutes_asleep / time_in_bed) * 100 if time_in_bed > 0 else 0

    results.append({
        'date': date,
        'avg_day_hr': avg_day_hr,
        'avg_sleep_hr': avg_sleep_hr,
        'min_sleep_hr': min_sleep_hr,
        'resting_hr': resting_hr,
        'dip_rate_avg': dip_rate_avg,
        'dip_rate_min': dip_rate_min,
        'night_day_ratio': night_day_ratio,
        'time_to_min_hr': time_to_min_hr,
        'min_hr_clock_time': min_hr_clock_time,
        'sleep_efficiency': sleep_efficiency,
        'minutes_asleep': minutes_asleep,
        'time_in_bed': time_in_bed
    })

# DataFrameに変換
df_results = pd.DataFrame(results)
df_results['date'] = pd.to_datetime(df_results['date'])

print("=" * 60)
print("📊 分析結果サマリー")
print("=" * 60)

print("\n【指標1】夜間心拍数ディップ率")
print(f"平均ディップ率（睡眠平均）: {df_results['dip_rate_avg'].mean():.1f}%")
print(f"平均ディップ率（最低心拍数）: {df_results['dip_rate_min'].mean():.1f}%")
print(f"夜/昼比率: {df_results['night_day_ratio'].mean():.2f}")
non_dippers = (df_results['dip_rate_avg'] < 10).sum()
print(f"非ディッパー（<10%）: {non_dippers}/{len(df_results)}日")

print("\n【指標2】入眠から最低心拍数までの時間")
print(f"平均: {df_results['time_to_min_hr'].mean():.0f}分")
print(f"中央値: {df_results['time_to_min_hr'].median():.0f}分")
print(f"範囲: {df_results['time_to_min_hr'].min():.0f}～{df_results['time_to_min_hr'].max():.0f}分")

print("\n【指標3】最低心拍数の発生時刻")
print(f"最頻時刻帯: {df_results['min_hr_clock_time'].mode().iloc[0] if len(df_results) > 0 else 'N/A'}")

print("\n【指標4】睡眠効率")
print(f"平均睡眠効率: {df_results['sleep_efficiency'].mean():.1f}%")

# 相関分析
corr_eff_dip = df_results[['sleep_efficiency', 'dip_rate_avg']].corr().iloc[0, 1]
print(f"睡眠効率とディップ率の相関: {corr_eff_dip:.2f}")

# グラフ作成
plt.style.use('dark_background')
fig = plt.figure(figsize=(16, 12))

# グラフ1: 夜間心拍数ディップ率のトレンド
ax1 = plt.subplot(3, 2, 1)
ax1.plot(df_results['date'], df_results['dip_rate_avg'],
         marker='o', linewidth=2, markersize=6, color='#4CAF50')
ax1.axhline(y=10, color='red', linestyle='--', linewidth=1, alpha=0.5, label='Non-dipper threshold (10%)')
ax1.axhline(y=20, color='yellow', linestyle='--', linewidth=1, alpha=0.5, label='Healthy baseline (20%)')
ax1.set_title('Nocturnal HR Dip Rate (Sleep Avg)', fontsize=12, pad=10)
ax1.set_ylabel('Dip Rate (%)', fontsize=10)
ax1.legend(fontsize=8)
ax1.grid(True, alpha=0.2)
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))

# グラフ2: 夜/昼心拍数比率
ax2 = plt.subplot(3, 2, 2)
ax2.plot(df_results['date'], df_results['night_day_ratio'],
         marker='o', linewidth=2, markersize=6, color='#2196F3')
ax2.axhline(y=0.90, color='red', linestyle='--', linewidth=1, alpha=0.5, label='Non-dipper threshold (>0.90)')
ax2.set_title('Night/Day HR Ratio', fontsize=12, pad=10)
ax2.set_ylabel('Ratio', fontsize=10)
ax2.legend(fontsize=8)
ax2.grid(True, alpha=0.2)
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))

# グラフ3: 入眠から最低心拍数までの時間
ax3 = plt.subplot(3, 2, 3)
ax3.bar(df_results['date'], df_results['time_to_min_hr'],
        color='#9C27B0', alpha=0.7, width=0.8)
ax3.axhline(y=df_results['time_to_min_hr'].mean(),
           color='yellow', linestyle='--', linewidth=1, alpha=0.7, label=f"Average ({df_results['time_to_min_hr'].mean():.0f}min)")
ax3.set_title('Time to Lowest HR from Sleep Onset', fontsize=12, pad=10)
ax3.set_ylabel('Time (min)', fontsize=10)
ax3.legend(fontsize=8)
ax3.grid(True, alpha=0.2, axis='y')
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))

# グラフ4: 心拍数の推移（日中vs睡眠中）
ax4 = plt.subplot(3, 2, 4)
ax4.plot(df_results['date'], df_results['avg_day_hr'],
         marker='o', linewidth=2, markersize=6, color='#FF9800', label='Daytime Avg')
ax4.plot(df_results['date'], df_results['avg_sleep_hr'],
         marker='o', linewidth=2, markersize=6, color='#03A9F4', label='Sleep Avg')
ax4.plot(df_results['date'], df_results['min_sleep_hr'],
         marker='o', linewidth=2, markersize=6, color='#E91E63', label='Sleep Min')
ax4.set_title('Heart Rate Trends', fontsize=12, pad=10)
ax4.set_ylabel('Heart Rate (bpm)', fontsize=10)
ax4.legend(fontsize=8)
ax4.grid(True, alpha=0.2)
ax4.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))

# グラフ5: 睡眠効率とディップ率の関係
ax5 = plt.subplot(3, 2, 5)
scatter = ax5.scatter(df_results['sleep_efficiency'], df_results['dip_rate_avg'],
                     c=range(len(df_results)), cmap='viridis',
                     s=100, alpha=0.6, edgecolors='white', linewidth=0.5)
z = np.polyfit(df_results['sleep_efficiency'], df_results['dip_rate_avg'], 1)
p = np.poly1d(z)
ax5.plot(df_results['sleep_efficiency'], p(df_results['sleep_efficiency']),
         "r--", alpha=0.8, linewidth=2)
ax5.set_title(f'Sleep Efficiency vs Dip Rate (r={corr_eff_dip:.2f})', fontsize=12, pad=10)
ax5.set_xlabel('Sleep Efficiency (%)', fontsize=10)
ax5.set_ylabel('Dip Rate (%)', fontsize=10)
ax5.grid(True, alpha=0.2)
cbar = plt.colorbar(scatter, ax=ax5)
cbar.set_label('Older -> Newer', fontsize=8)

# グラフ6: 最低心拍数発生時刻の分布
ax6 = plt.subplot(3, 2, 6)
# 時刻を時間（小数）に変換
hours = [int(t.split(':')[0]) + int(t.split(':')[1])/60 for t in df_results['min_hr_clock_time']]
ax6.hist(hours, bins=24, color='#00BCD4', alpha=0.7, edgecolor='white', linewidth=0.5)
ax6.axvline(x=2, color='yellow', linestyle='--', linewidth=1, alpha=0.7, label='Ideal time (02:00)')
ax6.set_title('Distribution of Lowest HR Time', fontsize=12, pad=10)
ax6.set_xlabel('Time', fontsize=10)
ax6.set_ylabel('Frequency', fontsize=10)
ax6.legend(fontsize=8)
ax6.grid(True, alpha=0.2, axis='y')
ax6.set_xlim(20, 8)
ax6.set_xticks(range(20, 32, 2))
ax6.set_xticklabels([f'{h%24:02d}:00' for h in range(20, 32, 2)], rotation=45)

fig.patch.set_facecolor('#1a1a1a')
for ax in [ax1, ax2, ax3, ax4, ax5, ax6]:
    ax.set_facecolor('#1a1a1a')

plt.tight_layout()
plt.savefig(
    '/home/tsu-nera/repo/dailybuild/issues/006_sleep_hr/advanced_hr_metrics.png',
    dpi=150,
    facecolor='#1a1a1a',
    edgecolor='none'
)
print("\nグラフを保存しました: advanced_hr_metrics.png")

# 健康評価
def evaluate_health_status(df):
    issues = []
    recommendations = []

    # ディップ率評価
    avg_dip = df['dip_rate_avg'].mean()
    if avg_dip < 10:
        issues.append("⚠️ 夜間心拍数ディップ率が10%未満（非ディッパー）")
        recommendations.append("心血管リスクが高い可能性があります。ストレス管理と睡眠の質改善を検討してください。")
    elif avg_dip < 20:
        issues.append("⚡ 夜間心拍数ディップ率が10-20%（やや低め）")
        recommendations.append("睡眠環境の最適化と副交感神経活性化を促す習慣を取り入れましょう。")
    else:
        issues.append("✅ 夜間心拍数ディップ率が20%以上（良好）")

    # 最低心拍数到達時間評価
    avg_time = df['time_to_min_hr'].mean()
    if avg_time > 180:
        issues.append("⚠️ 最低心拍数到達に時間がかかる（平均180分超）")
        recommendations.append("入眠後の副交感神経活性化が遅い可能性があります。就寝前のリラクゼーションを強化してください。")
    elif avg_time < 60:
        issues.append("⚡ 最低心拍数到達が早い（平均60分未満）")
        recommendations.append("睡眠前の過度な疲労や体調変化に注意してください。")
    else:
        issues.append("✅ 最低心拍数到達時間は正常範囲（60-180分）")

    # 睡眠効率評価
    avg_eff = df['sleep_efficiency'].mean()
    if avg_eff < 85:
        issues.append("⚠️ 睡眠効率が85%未満")
        recommendations.append("睡眠の質改善が必要です。就寝時刻の一貫性と睡眠環境を見直してください。")
    else:
        issues.append("✅ 睡眠効率は良好（85%以上）")

    return issues, recommendations

issues, recommendations = evaluate_health_status(df_results)

# Markdownレポート作成
report = f"""# 睡眠中心拍数の高度な指標分析

**分析期間**: {start_date} ～ {end_date}
**対象記録数**: {len(df_results)}日間

## 📊 分析結果サマリー

### 1. 夜間心拍数ディップ率（Nocturnal HR Dip）

健康な人は睡眠中に心拍数が日中の10-20%低下します。この低下が不十分な「非ディッパー」は心血管イベントのリスクが2.4倍に増加します。

- **平均ディップ率**: {df_results['dip_rate_avg'].mean():.1f}%
- **夜/昼心拍数比率**: {df_results['night_day_ratio'].mean():.2f}
- **非ディッパー日数**: {(df_results['dip_rate_avg'] < 10).sum()}/{len(df_results)}日
- **基準**: 健康な範囲は10-20%以上、非ディッパーは<10%（比率>0.90）

### 2. 入眠から最低心拍数までの時間

入眠後、副交感神経が活性化し心拍数が低下します。この時間が長すぎる場合、ストレスや交感神経優位の可能性があります。

- **平均到達時間**: {df_results['time_to_min_hr'].mean():.0f}分
- **中央値**: {df_results['time_to_min_hr'].median():.0f}分
- **範囲**: {df_results['time_to_min_hr'].min():.0f}～{df_results['time_to_min_hr'].max():.0f}分
- **基準**: シフトワーク研究では112-174分、健康な範囲は60-180分程度

### 3. 最低心拍数の発生時刻

概日リズムによって、徐波睡眠中の最大副交感神経活動は通常午前2時頃に観察されます。

- **最頻時刻帯**: {df_results['min_hr_clock_time'].mode().iloc[0] if len(df_results) > 0 else 'N/A'}
- **基準**: 午前2時前後が理想的

### 4. 睡眠効率との相関

睡眠効率が低い人は夜間心拍数ディップも減少します。

- **平均睡眠効率**: {df_results['sleep_efficiency'].mean():.1f}%
- **相関係数**: {corr_eff_dip:.2f}
- **基準**: 85%以上が良好

## 📈 可視化

![高度な心拍数指標](advanced_hr_metrics.png)

## 🏥 健康評価

### 検出された状態

{'  \n'.join(f'- {issue}' for issue in issues)}

### 推奨事項

{'  \n'.join(f'{i+1}. {rec}' for i, rec in enumerate(recommendations))}

## 🔬 研究的背景

これらの指標は以下の研究に基づいています：

1. **夜間心拍数ディップ**: 非ディッパーは心血管イベントリスクが2.4倍に増加（Hypertension Research）
2. **副交感神経活性化**: 入眠後1時間以内に副交感神経活動がピークに達する（PMC研究）
3. **概日リズム**: 午前2時頃に最大副交感神経活動が観察される（Circulation）
4. **睡眠効率**: 低効率群は心拍数ディップが21%→12%に減少（American Journal of Physiology）

## 📝 詳細データ

| 日付 | ディップ率(%) | 最低HR到達(分) | 睡眠効率(%) | 夜/昼比率 |
|------|--------------|---------------|-------------|-----------|
"""

for _, row in df_results.tail(10).iterrows():
    report += f"| {row['date'].strftime('%Y-%m-%d')} | {row['dip_rate_avg']:.1f} | {row['time_to_min_hr']:.0f} | {row['sleep_efficiency']:.1f} | {row['night_day_ratio']:.2f} |\n"

report += f"""
---
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""

with open('/home/tsu-nera/repo/dailybuild/issues/006_sleep_hr/ADVANCED_METRICS_REPORT.md', 'w', encoding='utf-8') as f:
    f.write(report)

print("詳細レポートを保存しました: ADVANCED_METRICS_REPORT.md")

# CSV出力
df_results.to_csv(
    '/home/tsu-nera/repo/dailybuild/issues/006_sleep_hr/advanced_hr_metrics.csv',
    index=False
)
print("データをCSVに保存しました: advanced_hr_metrics.csv")

print("\n✅ 分析完了！")
