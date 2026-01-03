#!/usr/bin/env python3
"""
感染タイミング推定分析

行動履歴とバイタルデータを組み合わせて、感染のタイミングを特定する。
"""

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta

# データディレクトリ
DATA_DIR = "/home/tsu-nera/repo/dailybuild/data/fitbit"
OUTPUT_DIR = "/home/tsu-nera/repo/dailybuild/issues/003_cold_detection/img"

# 行動履歴
ACTIVITY_LOG = {
    '2025-12-26': '瞑想リトリート1日目（移動: バス・電車）',
    '2025-12-27': '瞑想リトリート2日目',
    '2025-12-28': '瞑想リトリート3日目（帰路: バス・電車）',
    '2025-12-29': '実家帰省（移動: 電車）',
    '2025-12-30': '1日瞑想会',
    '2025-12-31': '1日瞑想会',
    '2026-01-01': '症状発現（発熱・喉の痛み）'
}

# 一般的な風邪ウイルスの潜伏期間
INCUBATION_PERIODS = {
    'ライノウイルス': (1, 3),
    'コロナウイルス（普通感冒）': (2, 4),
    'インフルエンザ': (1, 4),
    'RSウイルス': (4, 6),
    'アデノウイルス': (2, 14)
}

def load_all_data():
    """全データ読み込み"""
    data = {}

    # 心拍数
    df = pd.read_csv(f"{DATA_DIR}/heart_rate.csv", parse_dates=['date'])
    data['rhr'] = df.set_index('date')

    # HRV
    df = pd.read_csv(f"{DATA_DIR}/hrv.csv", parse_dates=['date'])
    data['hrv'] = df.set_index('date')

    # 皮膚温度
    df = pd.read_csv(f"{DATA_DIR}/temperature_skin.csv", parse_dates=['date'])
    data['temp'] = df.set_index('date')

    # 睡眠
    df = pd.read_csv(f"{DATA_DIR}/sleep.csv", parse_dates=['dateOfSleep'])
    df = df[df['isMainSleep'] == True]
    data['sleep'] = df.set_index('dateOfSleep')

    # 呼吸数
    df = pd.read_csv(f"{DATA_DIR}/breathing_rate.csv", parse_dates=['date'])
    data['breathing'] = df.set_index('date')

    return data

def analyze_immune_markers(data, start_date, end_date):
    """免疫系マーカーの時系列分析"""

    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    # データフィルタ
    rhr = data['rhr'].loc[start:end, 'resting_heart_rate']
    hrv = data['hrv'].loc[start:end, 'daily_rmssd']
    temp = data['temp'].loc[start:end, 'nightly_relative']
    sleep_eff = data['sleep'].loc[start:end, 'efficiency']
    sleep_awake = data['sleep'].loc[start:end, 'minutesAwake']
    sleep_rem = data['sleep'].loc[start:end, 'remMinutes']
    sleep_deep = data['sleep'].loc[start:end, 'deepMinutes']
    breathing = data['breathing'].loc[start:end, 'breathing_rate']

    # 統合データフレーム
    df = pd.DataFrame({
        'RHR': rhr,
        'HRV': hrv,
        '皮膚温': temp,
        '睡眠効率': sleep_eff,
        '覚醒時間': sleep_awake,
        'REM睡眠': sleep_rem,
        'Deep睡眠': sleep_deep,
        '呼吸数': breathing
    })

    return df

def calculate_immune_stress_score(df):
    """免疫ストレススコアを計算"""

    # ベースライン期間（12/18-12/25）
    baseline_start = pd.to_datetime('2025-12-18')
    baseline_end = pd.to_datetime('2025-12-25')

    scores = pd.DataFrame(index=df.index)

    # 各指標の異常度を計算
    # HRV低下スコア（低いほど悪い）
    hrv_baseline = df.loc[baseline_start:baseline_end, 'HRV'].mean()
    hrv_std = df.loc[baseline_start:baseline_end, 'HRV'].std()
    scores['HRV異常'] = (hrv_baseline - df['HRV']) / hrv_std
    scores['HRV異常'] = scores['HRV異常'].clip(lower=0)  # 負の値は0に

    # 皮膚温上昇スコア（高いほど悪い）
    temp_baseline = df.loc[baseline_start:baseline_end, '皮膚温'].mean()
    temp_std = df.loc[baseline_start:baseline_end, '皮膚温'].std()
    scores['皮膚温異常'] = (df['皮膚温'] - temp_baseline) / temp_std
    scores['皮膚温異常'] = scores['皮膚温異常'].clip(lower=0)

    # 睡眠効率低下スコア
    sleep_baseline = df.loc[baseline_start:baseline_end, '睡眠効率'].mean()
    sleep_std = df.loc[baseline_start:baseline_end, '睡眠効率'].std()
    scores['睡眠異常'] = (sleep_baseline - df['睡眠効率']) / sleep_std
    scores['睡眠異常'] = scores['睡眠異常'].clip(lower=0)

    # 覚醒時間増加スコア
    awake_baseline = df.loc[baseline_start:baseline_end, '覚醒時間'].mean()
    awake_std = df.loc[baseline_start:baseline_end, '覚醒時間'].std()
    scores['覚醒異常'] = (df['覚醒時間'] - awake_baseline) / awake_std
    scores['覚醒異常'] = scores['覚醒異常'].clip(lower=0)

    # RHR上昇スコア
    rhr_baseline = df.loc[baseline_start:baseline_end, 'RHR'].mean()
    rhr_std = df.loc[baseline_start:baseline_end, 'RHR'].std()
    scores['RHR異常'] = (df['RHR'] - rhr_baseline) / rhr_std
    scores['RHR異常'] = scores['RHR異常'].clip(lower=0)

    # 総合スコア（重み付け平均）
    scores['免疫ストレス総合'] = (
        scores['HRV異常'] * 2.0 +      # HRVは最も重要
        scores['皮膚温異常'] * 1.5 +
        scores['睡眠異常'] * 1.0 +
        scores['覚醒異常'] * 1.5 +
        scores['RHR異常'] * 1.0
    ) / 7.0

    return scores

def estimate_infection_timing(scores, symptom_date):
    """感染タイミングを推定"""

    symptom_dt = pd.to_datetime(symptom_date)

    # 免疫ストレススコアが閾値を超えた最初の日を検出
    threshold = 1.0  # 標準偏差の1倍以上

    anomaly_dates = scores[scores['免疫ストレス総合'] > threshold].index

    if len(anomaly_dates) == 0:
        return None, None

    first_anomaly = anomaly_dates[0]

    # 潜伏期間の推定
    days_before_symptoms = (symptom_dt - first_anomaly).days

    # 各ウイルスの可能性を評価
    possible_viruses = []
    for virus, (min_incub, max_incub) in INCUBATION_PERIODS.items():
        if min_incub <= days_before_symptoms <= max_incub:
            possible_viruses.append(virus)

    return first_anomaly, possible_viruses

def create_timeline_visualization(df, scores):
    """タイムライン可視化"""

    fig, axes = plt.subplots(6, 1, figsize=(16, 14))

    # 日付範囲
    dates = df.index

    # 1. 免疫ストレス総合スコア
    ax = axes[0]
    ax.plot(dates, scores['免疫ストレス総合'], 'o-', color='red', linewidth=2, markersize=8)
    ax.axhline(1.0, color='orange', linestyle='--', label='Alert threshold (1.0σ)')
    ax.axhline(2.0, color='red', linestyle='--', label='Critical threshold (2.0σ)')
    ax.axvline(pd.to_datetime('2026-01-01'), color='darkred', linestyle=':', linewidth=2, label='Symptom onset')

    # 行動履歴を追加
    for date_str, activity in ACTIVITY_LOG.items():
        date = pd.to_datetime(date_str)
        if date in dates:
            y_pos = scores.loc[date, '免疫ストレス総合']
            ax.annotate(activity, xy=(date, y_pos), xytext=(0, 20),
                       textcoords='offset points', fontsize=8,
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.5),
                       arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))

    ax.set_title('Immune Stress Score & Activity Timeline', fontsize=14, fontweight='bold')
    ax.set_ylabel('Standard Deviation (σ)')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)

    # 2. HRV
    ax = axes[1]
    ax.plot(dates, df['HRV'], 'o-', color='blue', linewidth=2, markersize=6)
    ax.set_title('HRV (RMSSD)', fontsize=12, fontweight='bold')
    ax.set_ylabel('ms')
    ax.grid(True, alpha=0.3)

    # 3. 皮膚温度
    ax = axes[2]
    ax.plot(dates, df['皮膚温'], 'o-', color='orange', linewidth=2, markersize=6)
    ax.axhline(0, color='gray', linestyle='--', alpha=0.5)
    ax.set_title('Skin Temperature Variation', fontsize=12, fontweight='bold')
    ax.set_ylabel('°C')
    ax.grid(True, alpha=0.3)

    # 4. 睡眠効率と覚醒時間
    ax = axes[3]
    ax2 = ax.twinx()
    l1 = ax.plot(dates, df['睡眠効率'], 'o-', color='purple', linewidth=2, markersize=6, label='Sleep Efficiency')
    l2 = ax2.plot(dates, df['覚醒時間'], 's-', color='brown', linewidth=2, markersize=6, label='Awake Time')
    ax.set_ylabel('Efficiency (%)', color='purple')
    ax2.set_ylabel('Minutes', color='brown')
    ax.set_title('Sleep Quality', fontsize=12, fontweight='bold')

    # 凡例を統合
    lines = l1 + l2
    labels = [l.get_label() for l in lines]
    ax.legend(lines, labels, loc='upper left')
    ax.grid(True, alpha=0.3)

    # 5. REM/Deep睡眠
    ax = axes[4]
    ax.plot(dates, df['REM睡眠'], 'o-', color='cyan', linewidth=2, markersize=6, label='REM Sleep')
    ax.plot(dates, df['Deep睡眠'], 's-', color='darkblue', linewidth=2, markersize=6, label='Deep Sleep')
    ax.set_title('Sleep Stages', fontsize=12, fontweight='bold')
    ax.set_ylabel('Minutes')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)

    # 6. 安静時心拍数
    ax = axes[5]
    ax.plot(dates, df['RHR'], 'o-', color='red', linewidth=2, markersize=6)
    ax.set_title('Resting Heart Rate', fontsize=12, fontweight='bold')
    ax.set_ylabel('bpm')
    ax.set_xlabel('Date')
    ax.grid(True, alpha=0.3)

    # 全グラフに症状発現日のラインを追加
    for ax in axes[1:]:
        ax.axvline(pd.to_datetime('2026-01-01'), color='darkred', linestyle=':', linewidth=2, alpha=0.5)

    # 日付フォーマット
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()
    plt.savefig(f"{OUTPUT_DIR}/infection_timeline.png", dpi=300, bbox_inches='tight')
    print(f"保存: {OUTPUT_DIR}/infection_timeline.png")

def generate_infection_report(df, scores):
    """感染タイミング推定レポート生成"""

    report = """# 感染タイミング推定分析

## 行動履歴

| 日付 | 活動内容 | 感染リスク |
|------|---------|-----------|
| 12/26 | 瞑想リトリート1日目（移動: バス・電車） | ⚠️ 高（公共交通機関） |
| 12/27 | 瞑想リトリート2日目 | 🟢 低（施設内） |
| 12/28 | 瞑想リトリート3日目（帰路: バス・電車） | ⚠️ 高（公共交通機関） |
| 12/29 | 実家帰省（移動: 電車） | ⚠️ 高（公共交通機関） |
| 12/30 | 1日瞑想会 | 🟡 中（集団活動） |
| 12/31 | 1日瞑想会 | 🟡 中（集団活動） |
| 01/01 | 症状発現（発熱・喉の痛み） | 🔴 発症 |

## バイタルデータ詳細分析

"""

    # 各日のデータを詳細に分析
    for date in df.index:
        date_str = date.strftime('%Y-%m-%d')
        activity = ACTIVITY_LOG.get(date_str, '')

        report += f"### {date.strftime('%m/%d')} ({date.strftime('%a')})"
        if activity:
            report += f" - {activity}"
        report += "\n\n"

        # バイタルデータ
        report += "**バイタルサイン:**\n"
        report += f"- 皮膚温: {df.loc[date, '皮膚温']:.1f}°C"
        if date > df.index[0]:
            prev_temp = df.loc[date - timedelta(days=1), '皮膚温'] if (date - timedelta(days=1)) in df.index else None
            if prev_temp is not None:
                change = df.loc[date, '皮膚温'] - prev_temp
                report += f" ({change:+.1f}°C変化)"
        report += "\n"

        report += f"- HRV: {df.loc[date, 'HRV']:.1f}ms\n"
        report += f"- 安静時心拍数: {df.loc[date, 'RHR']:.0f}bpm\n"

        if not pd.isna(df.loc[date, '呼吸数']):
            report += f"- 呼吸数: {df.loc[date, '呼吸数']:.1f}回/分\n"

        report += f"\n**睡眠:**\n"
        report += f"- 効率: {df.loc[date, '睡眠効率']:.0f}%\n"
        report += f"- 覚醒時間: {df.loc[date, '覚醒時間']:.0f}分\n"
        report += f"- Deep睡眠: {df.loc[date, 'Deep睡眠']:.0f}分\n"
        report += f"- REM睡眠: {df.loc[date, 'REM睡眠']:.0f}分\n"

        # 免疫ストレススコア
        immune_score = scores.loc[date, '免疫ストレス総合']
        report += f"\n**免疫ストレススコア: {immune_score:.2f}σ**"

        if immune_score > 2.0:
            report += " 🔴 **重度異常**"
        elif immune_score > 1.0:
            report += " ⚠️ **警告レベル**"
        else:
            report += " 🟢 正常範囲"

        report += "\n\n"

        # 異常パターンの解釈
        interpretations = []

        if df.loc[date, '覚醒時間'] > 100:
            interpretations.append("⚠️ 覚醒時間が異常に長い（免疫系が活性化している可能性）")

        if df.loc[date, 'REM睡眠'] < 60:
            interpretations.append("⚠️ REM睡眠が著しく少ない（ストレス/免疫応答）")

        if date > df.index[0]:
            prev_date = date - timedelta(days=1)
            if prev_date in df.index:
                temp_change = df.loc[date, '皮膚温'] - df.loc[prev_date, '皮膚温']
                if abs(temp_change) > 2.0:
                    interpretations.append(f"🌡️ 皮膚温が急激に変化（{temp_change:+.1f}°C）")

        if df.loc[date, 'HRV'] < 30:
            interpretations.append("💔 HRVが低下（自律神経系ストレス）")

        if interpretations:
            report += "**解釈:**\n"
            for interp in interpretations:
                report += f"- {interp}\n"
            report += "\n"

        report += "---\n\n"

    # 感染タイミング推定
    report += """## 感染タイミング推定

### 潜伏期間からの逆算

症状発現日: **2026-01-01**

"""

    # 各ウイルスの感染可能期間を計算
    symptom_date = pd.to_datetime('2026-01-01')

    report += "| ウイルス | 潜伏期間 | 感染推定期間 | 該当する行動 |\n"
    report += "|---------|---------|-------------|-------------|\n"

    for virus, (min_inc, max_inc) in INCUBATION_PERIODS.items():
        earliest = symptom_date - timedelta(days=max_inc)
        latest = symptom_date - timedelta(days=min_inc)

        # 該当する行動を特定
        matching_activities = []
        for date_str, activity in ACTIVITY_LOG.items():
            act_date = pd.to_datetime(date_str)
            if earliest <= act_date <= latest and act_date < symptom_date:
                matching_activities.append(f"{act_date.strftime('%m/%d')} {activity}")

        activities_str = "<br>".join(matching_activities) if matching_activities else "-"

        report += f"| {virus} | {min_inc}-{max_inc}日 | {earliest.strftime('%m/%d')}-{latest.strftime('%m/%d')} | {activities_str} |\n"

    report += """
### 免疫マーカーからの分析

免疫ストレススコアが有意に上昇した日付を基に感染タイミングを推定：

"""

    # 免疫ストレススコアが1.0を超えた日を特定
    alert_dates = scores[scores['免疫ストレス総合'] > 1.0].index

    if len(alert_dates) > 0:
        first_alert = alert_dates[0]
        days_before = (symptom_date - first_alert).days

        report += f"**最初の免疫応答検出: {first_alert.strftime('%Y-%m-%d')}**\n\n"
        report += f"症状発現の**{days_before}日前**に免疫系の活性化が始まっている。\n\n"

        # この日数から逆算して感染日を推定
        estimated_infection_start = first_alert - timedelta(days=1)
        estimated_infection_end = first_alert

        report += f"**推定感染期間: {estimated_infection_start.strftime('%m/%d')} - {estimated_infection_end.strftime('%m/%d')}**\n\n"

        # この期間の行動を特定
        report += "**この期間の行動:**\n"
        for date_str, activity in ACTIVITY_LOG.items():
            act_date = pd.to_datetime(date_str)
            if estimated_infection_start <= act_date <= estimated_infection_end:
                report += f"- {act_date.strftime('%m/%d')}: {activity}\n"

    report += """
## 詳細な考察

### 12/26-28 瞑想リトリート期間の異常

"""

    # 12/26の分析
    date_1226 = pd.to_datetime('2025-12-26')
    if date_1226 in df.index:
        report += f"""#### 12/26（初日）
- 皮膚温: **-2.4°C**（極端に低い）
- REM睡眠: **{df.loc[date_1226, 'REM睡眠']:.0f}分**（通常の半分）
- 睡眠効率: **{df.loc[date_1226, '睡眠効率']:.0f}%**（低下）

**解釈:**
- 環境変化（新しい場所での睡眠）によるストレス
- 移動疲労の影響
- **または**: すでに感染後の初期免疫応答が始まっていた可能性

**重要ポイント**: この日にバス・電車で移動しているため、**感染リスクが高い**。

"""

    # 12/27の分析
    date_1227 = pd.to_datetime('2025-12-27')
    if date_1227 in df.index and date_1226 in df.index:
        temp_change = df.loc[date_1227, '皮膚温'] - df.loc[date_1226, '皮膚温']
        report += f"""#### 12/27（2日目）
- 皮膚温: **+1.5°C**（前日比: **{temp_change:+.1f}°C**の急激な上昇）
- Deep睡眠: **{df.loc[date_1227, 'Deep睡眠']:.0f}分**（増加）
- 睡眠効率: **{df.loc[date_1227, '睡眠効率']:.0f}%**（回復）

**解釈:**
1. **環境適応**: 2日目で環境に慣れた
2. **免疫応答開始**: 感染後24-48時間での初期免疫反応
   - 皮膚温の急上昇は血管拡張（炎症反応）を示唆
   - Deep睡眠の増加は免疫機能の活性化に対応

**どちらの可能性が高いか?**
- 4°Cの急激な変化は、単なる環境適応にしては大きすぎる
- **免疫応答の可能性が高い**

"""

    # 12/28の分析
    date_1228 = pd.to_datetime('2025-12-28')
    if date_1228 in df.index:
        report += f"""#### 12/28（3日目・帰路）
- 皮膚温: **+2.0°C**（さらに上昇継続）
- 睡眠効率: **{df.loc[date_1228, '睡眠効率']:.0f}%**（良好）

**解釈:**
- 皮膚温の継続的上昇は免疫応答の持続を示唆
- この日も帰路でバス・電車を利用（追加感染リスク）

"""

    # 12/29の分析
    date_1229 = pd.to_datetime('2025-12-29')
    if date_1229 in df.index:
        report += f"""#### 12/29（実家帰省）
- 覚醒時間: **{df.loc[date_1229, '覚醒時間']:.0f}分**（異常に長い、通常の3倍！）
- 睡眠効率: **{df.loc[date_1229, '睡眠効率']:.0f}%**（急激に悪化）
- Deep睡眠: **{df.loc[date_1229, 'Deep睡眠']:.0f}分**（減少）

**解釈:**
- **これは最も重要な異常値**
- 202分（3時間以上）の覚醒は、免疫系が本格的に活性化している証拠
- 感染後2-3日目の典型的な免疫応答パターン
- この日も電車で移動（感染リスクあり）

**結論**: 12/29時点で、すでに感染が進行していた可能性が**非常に高い**

"""

    # 12/30-31の分析
    date_1230 = pd.to_datetime('2025-12-30')
    date_1231 = pd.to_datetime('2025-12-31')

    report += f"""### 12/30-31 1日瞑想会期間

#### 12/30
- HRV: {df.loc[date_1230, 'HRV']:.1f}ms（まだ正常範囲）
- 睡眠効率: {df.loc[date_1230, '睡眠効率']:.0f}%（回復）

#### 12/31
- HRV: **{df.loc[date_1231, 'HRV']:.1f}ms**（低下開始）
- 免疫ストレススコア: {scores.loc[date_1231, '免疫ストレス総合']:.2f}σ

**解釈:**
- 12/30-31は**潜伏期間**というより、すでに**感染が進行している期間**
- 12/31からHRV低下が始まり、免疫系が本格的に戦闘モードに入った
- 瞑想会での感染の可能性は**低い**（すでに感染していた）

"""

    report += """## 結論

### 最も可能性の高いシナリオ

**感染日: 12/26（瞑想リトリート往路の公共交通機関）**

**根拠:**
1. **12/27の皮膚温急上昇**（4°C変化）は、感染後24時間での初期免疫応答と一致
2. **12/29の異常な覚醒時間**（202分）は、感染後3日目の免疫系本格化と一致
3. **潜伏期間**: 12/26感染 → 01/01発症 = **6日間**
   - RSウイルス（4-6日）やアデノウイルスと一致
   - または、ライノウイルス/コロナウイルスで免疫応答が早期に始まった

### 代替シナリオ

**感染日: 12/28（瞑想リトリート帰路）**

**根拠:**
1. 12/29の異常な睡眠は、感染後24時間の初期応答
2. 潜伏期間: 12/28感染 → 01/01発症 = **4日間**
   - コロナウイルス（普通感冒）やインフルエンザと一致

### 12/30-31の瞑想会での感染の可能性

**可能性: 低い**

**理由:**
- すでに12/29時点で明確な免疫応答（覚醒時間異常）が出現
- 12/30-31で感染した場合、潜伏期間が1-2日と非常に短い
- データからは、12/30-31はすでに感染が進行している時期と判断

### 推奨される予防策

今回の分析から、**公共交通機関での移動が最大のリスク**であることが示唆されます：

1. **移動後24-48時間の自己モニタリング強化**
   - HRV、皮膚温、睡眠の質をチェック

2. **免疫早期警告システム**
   - 皮膚温が2日連続で+1°C以上
   - 覚醒時間が通常の2倍以上
   - HRVが急激に低下

3. **予防的措置**
   - 公共交通機関利用後は十分な睡眠
   - 栄養補給の強化
   - 瞑想会など集団活動前の体調チェック

## タイムライングラフ

![感染タイムライン](img/infection_timeline.png)

---

*分析実施日: 2026-01-01*
"""

    return report

def main():
    """メイン処理"""
    print("=" * 60)
    print("感染タイミング推定分析")
    print("=" * 60)

    # データ読み込み
    print("\nデータ読み込み中...")
    data = load_all_data()

    # 分析期間
    start_date = '2025-12-26'
    end_date = '2026-01-01'

    # データ分析
    print("バイタルデータ分析中...")
    df = analyze_immune_markers(data, start_date, end_date)

    # 免疫ストレススコア計算
    print("免疫ストレススコア計算中...")
    scores = calculate_immune_stress_score(df)

    # 感染タイミング推定
    print("感染タイミング推定中...")
    first_anomaly, possible_viruses = estimate_infection_timing(scores, '2026-01-01')

    if first_anomaly:
        print(f"\n最初の免疫応答検出: {first_anomaly.strftime('%Y-%m-%d')}")
        if possible_viruses:
            print(f"可能性のあるウイルス: {', '.join(possible_viruses)}")

    # 可視化
    print("\nタイムライングラフ生成中...")
    create_timeline_visualization(df, scores)

    # レポート生成
    print("\nレポート生成中...")
    report = generate_infection_report(df, scores)

    report_path = "/home/tsu-nera/repo/dailybuild/issues/003_cold_detection/INFECTION_TIMELINE.md"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n✅ 分析完了!")
    print(f"📄 レポート: {report_path}")
    print(f"📊 グラフ: {OUTPUT_DIR}/infection_timeline.png")
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
