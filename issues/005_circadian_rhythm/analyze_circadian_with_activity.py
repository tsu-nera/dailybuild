#!/usr/bin/env python3
"""
サーカディアンリズム - 活動データ含む版

activity_logsの運動時間も含めて、実際の心拍数変動を分析する。
除外版と比較して、運動の影響がどれほどあるかを確認する。
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
from scipy.signal import find_peaks
from scipy.interpolate import UnivariateSpline
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.lib.analytics.circadian import (
    format_time as format_time_minutes,
    prepare_hourly_data_with_interval,
)


def detect_peaks_dips_detailed(time_decimal, hr_values, prominence=2.0):
    """詳細なピーク・ディップ検出"""
    # 欠損値を除外
    valid_mask = ~np.isnan(hr_values)
    time_valid = time_decimal[valid_mask]
    hr_valid = hr_values[valid_mask]

    if len(time_valid) < 10:
        print("⚠️ データが少なすぎます")
        return {
            'peaks': [],
            'dips': [],
            'spline': (np.array([]), np.array([])),
            'original': (time_valid, hr_valid),
        }

    # スプライン補間で滑らかな曲線を作成
    spline = UnivariateSpline(time_valid, hr_valid, s=len(time_valid)*3, k=3)

    # 細かい時間グリッドで評価
    time_fine = np.linspace(0, 24, 1440)  # 1分ごと
    hr_fine = spline(time_fine)

    # ピーク・ディップ検出
    peaks, peak_props = find_peaks(hr_fine, prominence=prominence, distance=30)
    dips, dip_props = find_peaks(-hr_fine, prominence=prominence, distance=30)

    peak_times = time_fine[peaks]
    peak_hrs = hr_fine[peaks]

    dip_times = time_fine[dips]
    dip_hrs = hr_fine[dips]

    return {
        'peaks': list(zip(peak_times, peak_hrs)),
        'dips': list(zip(dip_times, dip_hrs)),
        'spline': (time_fine, hr_fine),
        'original': (time_valid, hr_valid),
    }


def categorize_peaks_dips_detailed(peaks, dips):
    """ピーク・ディップを時間帯で分類"""
    categories = {
        'night_dip': None,         # 0-6時
        'morning_peak': None,      # 6-12時（起床後〜午前中）
        'afternoon_dip': None,     # 11-15時
        'afternoon_peak': None,    # 15-18時
        'evening_peak': None,      # 17-21時
    }

    # 夜のディップ（0-6時）
    night_dips = [(t, hr) for t, hr in dips if 0 <= t < 6]
    if night_dips:
        categories['night_dip'] = min(night_dips, key=lambda x: x[1])

    # 朝のピーク（6-12時）
    morning_peaks = [(t, hr) for t, hr in peaks if 6 <= t < 12]
    if morning_peaks:
        categories['morning_peak'] = max(morning_peaks, key=lambda x: x[1])

    # 昼のディップ（11-15時）
    afternoon_dips = [(t, hr) for t, hr in dips if 11 <= t < 15]
    if afternoon_dips:
        categories['afternoon_dip'] = min(afternoon_dips, key=lambda x: x[1])

    # 午後のピーク（15-18時）
    afternoon_peaks = [(t, hr) for t, hr in peaks if 15 <= t < 18]
    if afternoon_peaks:
        categories['afternoon_peak'] = max(afternoon_peaks, key=lambda x: x[1])

    # 夕方のピーク（17-21時）
    evening_peaks = [(t, hr) for t, hr in peaks if 17 <= t < 21]
    if evening_peaks:
        categories['evening_peak'] = max(evening_peaks, key=lambda x: x[1])

    return categories


def visualize_peaks_dips(time_fine, hr_fine, time_original, hr_original, categories, output_file):
    """ピーク・ディップを強調した可視化"""
    fig, ax = plt.subplots(figsize=(16, 8))

    # 元データ（10分ごと）
    ax.scatter(time_original, hr_original, color='lightcoral', s=30,
              alpha=0.5, label='10-min average HR (with activity)', zorder=2)

    # スプライン曲線
    ax.plot(time_fine, hr_fine, color='darkred', linewidth=3,
           label='Smoothed curve (spline)', zorder=3)

    # ピーク・ディップをマーク
    if categories['night_dip']:
        t, hr = categories['night_dip']
        ax.plot(t, hr, 'v', color='navy', markersize=20,
               label=f"Night dip ({format_time_minutes(t)}, {hr:.1f} bpm)", zorder=5)
        ax.annotate('Night\ndip', xy=(t, hr), xytext=(0, -30),
                   textcoords='offset points', ha='center',
                   fontsize=11, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='navy', linewidth=2))

    if categories['morning_peak']:
        t, hr = categories['morning_peak']
        ax.plot(t, hr, '^', color='gold', markersize=20,
               label=f"Morning peak ({format_time_minutes(t)}, {hr:.1f} bpm)", zorder=5)
        ax.annotate('Morning\npeak', xy=(t, hr), xytext=(0, 30),
                   textcoords='offset points', ha='center',
                   fontsize=11, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='gold', linewidth=2))

    if categories['afternoon_dip']:
        t, hr = categories['afternoon_dip']
        ax.plot(t, hr, 'v', color='purple', markersize=20,
               label=f"Afternoon dip ({format_time_minutes(t)}, {hr:.1f} bpm)", zorder=5)
        ax.annotate('Afternoon\ndip', xy=(t, hr), xytext=(0, -30),
                   textcoords='offset points', ha='center',
                   fontsize=11, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='purple', linewidth=2))

    if categories['afternoon_peak']:
        t, hr = categories['afternoon_peak']
        ax.plot(t, hr, '^', color='orange', markersize=20,
               label=f"Afternoon peak ({format_time_minutes(t)}, {hr:.1f} bpm)", zorder=5)
        ax.annotate('Afternoon\npeak', xy=(t, hr), xytext=(0, 30),
                   textcoords='offset points', ha='center',
                   fontsize=11, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='orange', linewidth=2))

    if categories['evening_peak']:
        t, hr = categories['evening_peak']
        ax.plot(t, hr, '^', color='red', markersize=20,
               label=f"Evening peak ({format_time_minutes(t)}, {hr:.1f} bpm)", zorder=5)
        ax.annotate('Evening\npeak', xy=(t, hr), xytext=(0, 30),
                   textcoords='offset points', ha='center',
                   fontsize=11, fontweight='bold',
                   bbox=dict(boxstyle='round,pad=0.5', facecolor='white', edgecolor='red', linewidth=2))

    # 時間帯を色分け
    ax.axvspan(0, 6, alpha=0.05, color='blue', zorder=0)
    ax.axvspan(6, 12, alpha=0.05, color='yellow', zorder=0)
    ax.axvspan(12, 18, alpha=0.05, color='orange', zorder=0)
    ax.axvspan(18, 24, alpha=0.05, color='purple', zorder=0)

    ax.set_xlabel('Time (hour)', fontsize=14, fontweight='bold')
    ax.set_ylabel('Heart Rate (bpm)', fontsize=14, fontweight='bold')
    ax.set_title('Circadian Rhythm - WITH Activity Data (10-min resolution)',
                fontsize=16, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10, ncol=2)
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.set_xlim(0, 24)
    ax.set_xticks(np.arange(0, 25, 2))
    ax.set_ylim(40, max(hr_fine) + 10)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"✅ ピーク・ディップ可視化を保存: {output_file}")


def generate_report(categories, all_peaks, all_dips):
    """レポート生成（活動データ含む）"""

    def format_entry(cat):
        if cat:
            t, hr = cat
            return f"**{format_time_minutes(t)}** ({hr:.1f} bpm)"
        return "検出されず"

    report = f"""# サーカディアンリズム - 活動データ含む版

**分析日**: 2026-01-07
**データ期間**: 2025-12-09 ~ 2026-01-07（30日間）
**フィルタリング**: なし（運動時間も含む）
**分析手法**: スプライン補間によるピーク・ディップ検出

---

## 重要

この分析では、**運動・活動時間を除外していません**。

含まれる活動：
- 🚴 Bike（自転車）
- 🏋️ Weights（筋トレ）
- 🚶 Walk（ウォーキング）
- その他すべての記録された運動

これにより、**実際の生活における心拍数変動**を観察できます。

---

## ピーク・ディップ分析

![ピーク・ディップの詳細分析](circadian_with_activity_markers.png)

**グラフの見方**:
- **ライトコーラルの点**: 10分ごとの平均心拍数（活動含む）
- **ダークレッドの線**: スプライン補間による滑らかな曲線
- **三角マーカー**: 検出されたピーク（上向き）とディップ（下向き）
- **色分け**: Navy（夜間）、Gold（朝）、Purple（昼）、Orange（午後）、Red（夕方）

| 時間帯 | タイプ | 時刻・心拍数 | 意味 |
|-------|--------|------------|------|
| 🌙 **夜間** | ディップ | {format_entry(categories['night_dip'])} | 深い睡眠 |
| ☀️ **朝** | ピーク | {format_entry(categories['morning_peak'])} | 起床後の活性化 |
| 😴 **昼** | ディップ | {format_entry(categories['afternoon_dip'])} | post-lunch dip（活動の影響含む） |
| 📈 **午後** | ピーク | {format_entry(categories['afternoon_peak'])} | 午後の活動ピーク |
| 🌆 **夕方** | ピーク | {format_entry(categories['evening_peak'])} | 夕方の活動ピーク |

---

## 全ピーク一覧（活動含む）

"""

    if all_peaks:
        for i, (t, hr) in enumerate(all_peaks, 1):
            report += f"{i}. **{format_time_minutes(t)}** - {hr:.1f} bpm\n"
    else:
        report += "検出されませんでした。\n"

    report += "\n## 全ディップ一覧（活動含む）\n\n"

    if all_dips:
        for i, (t, hr) in enumerate(all_dips, 1):
            report += f"{i}. **{format_time_minutes(t)}** - {hr:.1f} bpm\n"
    else:
        report += "検出されませんでした。\n"

    report += """
---

## 参考文献

- Circadian rhythm of heart rate and activity: A cross-sectional study (2025)
- Post-lunch dip: 多くの研究で確認されている生理的現象

---

**生成日時**: 2026-01-07
**分析ツール**: dailybuild サーカディアンリズム分析モジュール（活動データ含む版）
"""

    return report


def main():
    print("=" * 70)
    print("サーカディアンリズム - 活動データ含む版")
    print("=" * 70)

    # データ読み込み
    hr_df = pd.read_csv('data/fitbit/heart_rate_intraday.csv',
                       index_col='datetime', parse_dates=True)

    print(f"\n📊 元データ:")
    print(f"   心拍数: {len(hr_df):,}件")

    # 10分ごとの平均を計算（活動データ除外なし）
    print("\n⏰ 10分ごとの平均を計算中（30日間の同じ時刻を平均化、活動含む）...")
    hr_10min = prepare_hourly_data_with_interval(hr_df, interval_minutes=10)

    print(f"\n   10分ごとのデータポイント: {len(hr_10min)}個（0-24時の1日分）")

    # 詳細なピーク・ディップ検出
    print("\n🔍 ピーク・ディップを検出中（スプライン補間）...")
    results = detect_peaks_dips_detailed(
        hr_10min['time_decimal'].values,
        hr_10min['heart_rate'].values
    )

    print(f"\n検出されたピーク: {len(results['peaks'])}個")
    for t, hr in results['peaks']:
        print(f"   {format_time_minutes(t)}: {hr:.1f} bpm")

    print(f"\n検出されたディップ: {len(results['dips'])}個")
    for t, hr in results['dips']:
        print(f"   {format_time_minutes(t)}: {hr:.1f} bpm")

    # カテゴリ分類
    print("\n📋 時間帯別の分類:")
    categories = categorize_peaks_dips_detailed(results['peaks'], results['dips'])

    if categories['night_dip']:
        t, hr = categories['night_dip']
        print(f"   🌙 夜のディップ: {format_time_minutes(t)} ({hr:.1f} bpm)")

    if categories['morning_peak']:
        t, hr = categories['morning_peak']
        print(f"   ☀️ 朝のピーク: {format_time_minutes(t)} ({hr:.1f} bpm)")

    if categories['afternoon_dip']:
        t, hr = categories['afternoon_dip']
        print(f"   😴 昼のディップ: {format_time_minutes(t)} ({hr:.1f} bpm)")

    if categories['afternoon_peak']:
        t, hr = categories['afternoon_peak']
        print(f"   📈 午後のピーク: {format_time_minutes(t)} ({hr:.1f} bpm)")

    if categories['evening_peak']:
        t, hr = categories['evening_peak']
        print(f"   🌆 夕方のピーク: {format_time_minutes(t)} ({hr:.1f} bpm)")

    # 可視化
    print("\n📊 可視化を生成中...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    time_fine, hr_fine = results['spline']
    time_original, hr_original = results['original']
    output_file = os.path.join(script_dir, 'circadian_with_activity_markers.png')
    visualize_peaks_dips(time_fine, hr_fine, time_original, hr_original,
                        categories, output_file)

    # レポート生成
    print("\n📄 レポートを生成中...")
    report = generate_report(categories, results['peaks'], results['dips'])

    report_file = os.path.join(script_dir, 'WITH_ACTIVITY_ANALYSIS.md')
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"✅ レポートを生成: {report_file}")

    print("\n" + "=" * 70)
    print("✅ 分析完了！活動データを含めた心拍数変動を確認してください。")
    print(f"   レポート: {report_file}")
    print(f"   画像: {output_file}")
    print("=" * 70)


if __name__ == '__main__':
    main()
