#!/usr/bin/env python3
"""睡眠中の心拍数・血糖値・HRVの包括的関係分析スクリプト"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np
from scipy import stats
import seaborn as sns

# データ読み込み
print("データを読み込み中...")

# 睡眠データ
sleep_df = pd.read_csv('/home/tsu-nera/repo/dailybuild/data/fitbit/sleep.csv')

# 心拍数データ
hr_intraday_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/data/fitbit/heart_rate_intraday.csv',
    parse_dates=['datetime']
)

# HRVデータ
hrv_intraday_df = pd.read_csv(
    '/home/tsu-nera/repo/dailybuild/data/fitbit/hrv_intraday.csv',
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

sleep_hrv = hrv_intraday_df[
    (hrv_intraday_df['datetime'] >= sleep_start) &
    (hrv_intraday_df['datetime'] <= sleep_end)
].copy()

sleep_cgm = cgm_df[
    (cgm_df['timestamp'] >= sleep_start) &
    (cgm_df['timestamp'] <= sleep_end)
].copy()

print(f"心拍データ: {len(sleep_hr)}件")
print(f"HRVデータ: {len(sleep_hrv)}件")
print(f"血糖データ: {len(sleep_cgm)}件")

# データマージ（HRVを基準に）
# HRVが5分間隔なので、これを基準にマージ
merged_data = sleep_hrv.copy()

# CGMとマージ（5分間隔同士なので近接マッチング）
merged_data = pd.merge_asof(
    merged_data.sort_values('datetime'),
    sleep_cgm.sort_values('timestamp'),
    left_on='datetime',
    right_on='timestamp',
    direction='nearest',
    tolerance=pd.Timedelta('3min')
)

# 心拍数とマージ（1分間隔を5分間隔に集約）
merged_data = pd.merge_asof(
    merged_data.sort_values('datetime'),
    sleep_hr.sort_values('datetime'),
    on='datetime',
    direction='nearest',
    tolerance=pd.Timedelta('3min')
)

# 欠損値を除外
merged_data = merged_data.dropna(subset=['glucose', 'heart_rate', 'rmssd'])

print(f"マージ後: {len(merged_data)}件")

# 統計分析
hr_mean = merged_data['heart_rate'].mean()
glucose_mean = merged_data['glucose'].mean()
rmssd_mean = merged_data['rmssd'].mean()
hf_mean = merged_data['hf'].mean()
lf_mean = merged_data['lf'].mean()
lf_hf_ratio_mean = (merged_data['lf'] / merged_data['hf']).mean()

# 相関分析
corr_glucose_hr = merged_data['glucose'].corr(merged_data['heart_rate'])
corr_glucose_rmssd = merged_data['glucose'].corr(merged_data['rmssd'])
corr_glucose_hf = merged_data['glucose'].corr(merged_data['hf'])
corr_hr_rmssd = merged_data['heart_rate'].corr(merged_data['rmssd'])

# 統計的有意性検定
_, p_glucose_hr = stats.pearsonr(merged_data['glucose'], merged_data['heart_rate'])
_, p_glucose_rmssd = stats.pearsonr(merged_data['glucose'], merged_data['rmssd'])
_, p_glucose_hf = stats.pearsonr(merged_data['glucose'], merged_data['hf'])

print(f"\n=== 統計サマリー ===")
print(f"心拍数: 平均 {hr_mean:.1f} bpm")
print(f"血糖値: 平均 {glucose_mean:.1f} mg/dL")
print(f"HRV (RMSSD): 平均 {rmssd_mean:.1f} ms")
print(f"HF (副交感神経): 平均 {hf_mean:.1f}")
print(f"LF/HF比: 平均 {lf_hf_ratio_mean:.2f}")
print(f"\n相関係数:")
print(f"  血糖値 vs 心拍数: {corr_glucose_hr:.3f} (p={p_glucose_hr:.4f})")
print(f"  血糖値 vs HRV: {corr_glucose_rmssd:.3f} (p={p_glucose_rmssd:.4f})")
print(f"  血糖値 vs HF: {corr_glucose_hf:.3f} (p={p_glucose_hf:.4f})")
print(f"  心拍数 vs HRV: {corr_hr_rmssd:.3f}")

# グラフ作成
plt.style.use('dark_background')
fig = plt.figure(figsize=(16, 12))
gs = fig.add_gridspec(4, 2, hspace=0.3, wspace=0.3)

# 1. 時系列グラフ（3軸: 血糖値、心拍数、HRV）
ax1 = fig.add_subplot(gs[0, :])
ax1_hr = ax1.twinx()
ax1_hrv = ax1.twinx()
ax1_hrv.spines['right'].set_position(('outward', 60))

color_glucose = '#FF6B6B'
color_hr = '#9370DB'
color_hrv = '#4ECDC4'

# 血糖値
ax1.plot(sleep_cgm['timestamp'], sleep_cgm['glucose'],
         color=color_glucose, linewidth=2, label='血糖値', alpha=0.8)
ax1.set_ylabel('血糖値 (mg/dL)', color=color_glucose, fontweight='bold')
ax1.tick_params(axis='y', labelcolor=color_glucose)

# 心拍数
ax1_hr.plot(sleep_hr['datetime'], sleep_hr['heart_rate'],
            color=color_hr, linewidth=1.5, label='心拍数', alpha=0.7)
ax1_hr.set_ylabel('心拍数 (bpm)', color=color_hr, fontweight='bold')
ax1_hr.tick_params(axis='y', labelcolor=color_hr)

# HRV (RMSSD)
ax1_hrv.plot(sleep_hrv['datetime'], sleep_hrv['rmssd'],
             color=color_hrv, linewidth=1.5, label='HRV (RMSSD)', alpha=0.7)
ax1_hrv.set_ylabel('HRV RMSSD (ms)', color=color_hrv, fontweight='bold')
ax1_hrv.tick_params(axis='y', labelcolor=color_hrv)

ax1.set_title(f'睡眠中の血糖値・心拍数・HRVの推移\n{sleep_start.strftime("%m/%d %H:%M")}～{sleep_end.strftime("%H:%M")}',
              fontsize=14, pad=20, loc='left', fontweight='bold')
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax1.grid(True, alpha=0.2)

# 2. 血糖値 vs HRV (RMSSD)
ax2 = fig.add_subplot(gs[1, 0])
scatter2 = ax2.scatter(merged_data['glucose'], merged_data['rmssd'],
                       c=merged_data['heart_rate'], cmap='plasma',
                       alpha=0.6, s=50, edgecolors='white', linewidth=0.5)
ax2.set_xlabel('血糖値 (mg/dL)', fontweight='bold')
ax2.set_ylabel('HRV RMSSD (ms)', fontweight='bold')
ax2.set_title(f'血糖値 vs HRV\n相関係数: {corr_glucose_rmssd:.3f}',
              fontsize=12, pad=15, loc='left', fontweight='bold')
cbar2 = plt.colorbar(scatter2, ax=ax2, label='心拍数 (bpm)')
ax2.grid(True, alpha=0.2)

# 回帰直線
z = np.polyfit(merged_data['glucose'], merged_data['rmssd'], 1)
p = np.poly1d(z)
ax2.plot(merged_data['glucose'].sort_values(),
         p(merged_data['glucose'].sort_values()),
         "r--", linewidth=2, alpha=0.8)

# 3. 血糖値 vs HF（副交感神経活動）
ax3 = fig.add_subplot(gs[1, 1])
ax3.scatter(merged_data['glucose'], merged_data['hf'],
            alpha=0.6, s=50, color='#FFB347', edgecolors='white', linewidth=0.5)
ax3.set_xlabel('血糖値 (mg/dL)', fontweight='bold')
ax3.set_ylabel('HF成分 (副交感神経)', fontweight='bold')
ax3.set_title(f'血糖値 vs 副交感神経活動 (HF)\n相関係数: {corr_glucose_hf:.3f}',
              fontsize=12, pad=15, loc='left', fontweight='bold')
ax3.grid(True, alpha=0.2)

# 4. 心拍数 vs HRV
ax4 = fig.add_subplot(gs[2, 0])
scatter4 = ax4.scatter(merged_data['heart_rate'], merged_data['rmssd'],
                       c=merged_data['glucose'], cmap='RdYlGn_r',
                       alpha=0.6, s=50, edgecolors='white', linewidth=0.5)
ax4.set_xlabel('心拍数 (bpm)', fontweight='bold')
ax4.set_ylabel('HRV RMSSD (ms)', fontweight='bold')
ax4.set_title(f'心拍数 vs HRV\n相関係数: {corr_hr_rmssd:.3f}',
              fontsize=12, pad=15, loc='left', fontweight='bold')
cbar4 = plt.colorbar(scatter4, ax=ax4, label='血糖値 (mg/dL)')
ax4.grid(True, alpha=0.2)

# 5. LF/HF比（自律神経バランス）の時系列
ax5 = fig.add_subplot(gs[2, 1])
lf_hf_ratio = sleep_hrv['lf'] / sleep_hrv['hf']
ax5.plot(sleep_hrv['datetime'], lf_hf_ratio,
         color='#FFA07A', linewidth=2, alpha=0.8)
ax5.axhline(y=1.0, color='gray', linestyle='--', linewidth=1, alpha=0.5,
            label='バランス点 (LF=HF)')
ax5.set_ylabel('LF/HF比', fontweight='bold')
ax5.set_title('自律神経バランス (LF/HF比)\n高い=交感神経優位、低い=副交感神経優位',
              fontsize=12, pad=15, loc='left', fontweight='bold')
ax5.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
ax5.grid(True, alpha=0.2)
ax5.legend(loc='upper right', framealpha=0.8)

# 6. 相関マトリックス
ax6 = fig.add_subplot(gs[3, :])
corr_matrix = merged_data[['glucose', 'heart_rate', 'rmssd', 'hf', 'lf']].corr()
sns.heatmap(corr_matrix, annot=True, fmt='.3f', cmap='coolwarm',
            center=0, vmin=-1, vmax=1, ax=ax6,
            xticklabels=['血糖値', '心拍数', 'HRV\n(RMSSD)', 'HF\n(副交感)', 'LF'],
            yticklabels=['血糖値', '心拍数', 'HRV\n(RMSSD)', 'HF\n(副交感)', 'LF'],
            cbar_kws={'label': '相関係数'})
ax6.set_title('相関マトリックス', fontsize=12, pad=15, loc='left', fontweight='bold')

# 背景色設定
fig.patch.set_facecolor('#1a1a1a')
for ax in [ax1, ax2, ax3, ax4, ax5, ax6]:
    ax.set_facecolor('#1a1a1a')

plt.savefig(
    '/home/tsu-nera/repo/dailybuild/issues/008_cgm_hr/cgm_hr_hrv_analysis.png',
    dpi=150,
    facecolor='#1a1a1a',
    edgecolor='none',
    bbox_inches='tight'
)
print("\nグラフを保存しました: cgm_hr_hrv_analysis.png")

# Markdownレポート作成
report = f"""# 睡眠中の血糖値・心拍数・HRVの包括的関係分析

**対象日**: {target_date}
**睡眠時間**: {sleep_start.strftime('%Y-%m-%d %H:%M')} ～ {sleep_end.strftime('%Y-%m-%d %H:%M')}
**睡眠時間**: {sleep_record['minutesAsleep']:.0f}分 ({sleep_record['minutesAsleep']/60:.1f}時間)

## サマリー

### 平均値
- **心拍数**: {hr_mean:.1f} bpm
- **血糖値**: {glucose_mean:.1f} mg/dL
- **HRV (RMSSD)**: {rmssd_mean:.1f} ms（副交感神経活動の指標）
- **HF成分**: {hf_mean:.1f}（副交感神経優位度）
- **LF/HF比**: {lf_hf_ratio_mean:.2f}（自律神経バランス、低いほど副交感神経優位）

### 相関分析

| 関係 | 相関係数 | p値 | 有意性 | 解釈 |
|------|----------|-----|--------|------|
| **血糖値 vs 心拍数** | {corr_glucose_hr:.3f} | {p_glucose_hr:.4f} | {'✅ 有意' if p_glucose_hr < 0.05 else '❌ 非有意'} | {'負の相関：血糖値↑→心拍数↓' if corr_glucose_hr < -0.2 else '正の相関：血糖値↑→心拍数↑' if corr_glucose_hr > 0.2 else '相関弱い'} |
| **血糖値 vs HRV** | {corr_glucose_rmssd:.3f} | {p_glucose_rmssd:.4f} | {'✅ 有意' if p_glucose_rmssd < 0.05 else '❌ 非有意'} | {'負の相関：血糖値↑→HRV↓（副交感神経抑制）' if corr_glucose_rmssd < -0.2 else '正の相関：血糖値↑→HRV↑' if corr_glucose_rmssd > 0.2 else '相関弱い'} |
| **血糖値 vs HF** | {corr_glucose_hf:.3f} | {p_glucose_hf:.4f} | {'✅ 有意' if p_glucose_hf < 0.05 else '❌ 非有意'} | {'負の相関：血糖値↑→副交感神経↓' if corr_glucose_hf < -0.2 else '正の相関' if corr_glucose_hf > 0.2 else '相関弱い'} |
| **心拍数 vs HRV** | {corr_hr_rmssd:.3f} | - | - | {'負の相関：心拍数↑→HRV↓（生理学的に正常）' if corr_hr_rmssd < 0 else '正の相関（要注意）'} |

## 分析結果

![睡眠中の血糖値・心拍数・HRV分析](cgm_hr_hrv_analysis.png)

### グラフの見方

1. **上段**: 時系列グラフ（3軸同時表示）
   - 赤: 血糖値（左軸）
   - 紫: 心拍数（中軸）
   - 水色: HRV RMSSD（右軸）

2. **中段左**: 血糖値 vs HRV
   - 色: 心拍数を示す
   - 先行研究では血糖値↑→HRV↓の負の相関が報告されている

3. **中段右**: 血糖値 vs HF成分（副交感神経活動）
   - HF成分が高いほど副交感神経が優位（リラックス状態）

4. **下段左**: 心拍数 vs HRV
   - 色: 血糖値を示す
   - 通常、心拍数が高いとHRVは低下する

5. **下段中**: LF/HF比の時系列
   - LF/HF比が1.0より低い: 副交感神経優位（睡眠中の正常状態）
   - LF/HF比が1.0より高い: 交感神経優位（ストレス・覚醒状態）

6. **下段**: 相関マトリックス
   - 全指標間の相関係数を一覧表示

## 先行研究との比較

### 期待される関係性（先行研究より）

1. **血糖値 ↑ → HRV ↓**（負の相関）
   - 高血糖は自律神経機能を抑制し、特に副交感神経（迷走神経）を障害する
   - 2023年の研究では相関係数 r = -0.453 が報告されている

2. **血糖値 ↑ → HF成分 ↓**（副交感神経抑制）
   - 高血糖により副交感神経活動が低下
   - 糖化最終産物（AGEs）蓄積や微小血管障害が原因

3. **心拍数とHRVの逆相関**
   - 生理学的に正常な関係
   - 心拍数が高い時はHRVが低く、自律神経の柔軟性が失われている

### 今回の発見

"""

# 今回の発見の解釈を追加
if corr_glucose_rmssd < -0.3:
    report += f"""✅ **血糖値とHRVに明確な負の相関**（r = {corr_glucose_rmssd:.3f}）が確認され、先行研究と一致しています。
   - 高血糖時に副交感神経活動が抑制されている可能性
   - 自律神経の調節機能が血糖値の影響を受けている
"""
elif corr_glucose_rmssd > 0.3:
    report += f"""⚠️ **血糖値とHRVに正の相関**（r = {corr_glucose_rmssd:.3f}）が見られ、先行研究と異なるパターンです。
   - 代償的な副交感神経反応の可能性
   - 個人差や測定条件の影響を考慮が必要
"""
else:
    report += f"""❓ **血糖値とHRVの相関が弱い**（r = {corr_glucose_rmssd:.3f}）結果となりました。
   - サンプルサイズが小さい（1晩のみ）
   - 他の要因（睡眠ステージ、食事内容等）の影響が大きい可能性
"""

report += f"""
## HRV指標の解説

### RMSSD (Root Mean Square of Successive Differences)
- **副交感神経活動の指標**として最も信頼性が高い
- 連続する心拍間隔の差の二乗平均平方根
- 高い値 = 副交感神経が活発（リラックス、回復状態）
- 低い値 = 副交感神経が抑制（ストレス、疲労状態）

### HF成分 (High Frequency)
- **周波数0.15-0.4 Hzの成分**で、主に副交感神経活動を反映
- 呼吸と同期した心拍変動
- 睡眠中は通常高い値を示す

### LF/HF比 (Low Frequency / High Frequency Ratio)
- **自律神経のバランス**を示す指標
- LF/HF < 1.0: 副交感神経優位（睡眠中の正常状態）
- LF/HF > 1.0: 交感神経優位（覚醒、ストレス状態）
- ただし解釈には議論があり、LF成分は交感神経と副交感神経の両方を含む

## 臨床的意義

### 血糖値管理の重要性
高血糖は自律神経機能に悪影響を与え、特に：
- 副交感神経（迷走神経）の障害が先に現れる
- 睡眠中の回復機能が低下する
- 長期的には心血管リスクが上昇する

### 睡眠の質への影響
- 自律神経の乱れは睡眠の質を低下させる
- 血糖値スパイクは夜間の交感神経活動を亢進させる
- 良好な血糖コントロールが質の高い睡眠につながる

## 推奨される追加分析

1. **長期追跡**: 複数日/週のデータで再現性を確認
2. **睡眠ステージ別分析**: 深睡眠・REM・浅睡眠ごとの関係性
3. **食事内容との関連**: 夕食の糖質量・GL値とHRVの関係
4. **時系列ラグ分析**: 血糖値変化の何分後にHRVが反応するか
5. **血糖値変動幅とHRV**: 平均値だけでなく変動の大きさとの関係

## データ詳細

- **心拍データポイント数**: {len(sleep_hr)}件（1分間隔）
- **HRVデータポイント数**: {len(sleep_hrv)}件（5分間隔）
- **血糖データポイント数**: {len(sleep_cgm)}件（5分間隔）
- **マージ後データ数**: {len(merged_data)}件

## 参考文献

### 先行研究
- Correlation analysis of heart rate variations and glucose fluctuations during sleep (2023)
  - 睡眠中の血糖値とHRVに中程度の負の相関（r = -0.453）を報告
- Heart rate variability in different sleep stages and glycemic control in T2DM (2023)
  - 睡眠ステージ別のHRV分析と血糖コントロールの関連
- Dynamic Sleep-Derived HR/HRV Features Associated with Glucose Metabolism (2026)
  - ウェアラブルデバイスによる睡眠中のHRV特徴と糖代謝状態の関連

---
*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*Script: analyze_sleep_cgm_hr_hrv.py*
"""

# レポート保存
with open('/home/tsu-nera/repo/dailybuild/issues/008_cgm_hr/ANALYSIS_HRV.md', 'w', encoding='utf-8') as f:
    f.write(report)

print("レポートを保存しました: ANALYSIS_HRV.md")

# CSVエクスポート（統合データ）
merged_data.to_csv(
    '/home/tsu-nera/repo/dailybuild/issues/008_cgm_hr/merged_cgm_hr_hrv_data.csv',
    index=False
)
print("統合データを保存しました: merged_cgm_hr_hrv_data.csv")

print("\n包括的分析完了！")
