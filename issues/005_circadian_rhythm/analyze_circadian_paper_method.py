#!/usr/bin/env python3
"""
サーカディアンリズム - 論文の手法に完全準拠

論文の条件を厳密に適用：
1. activity_logsの運動時間を除外
2. 歩数0の時間帯のみ使用（現在・前の1分間にステップなし）
3. 睡眠中を除外
4. 2調和フーリエモデルでフィッティング
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.lib.analytics.circadian import (
    two_harmonic_model,
    fit_circadian_rhythm,
    format_time,
    exclude_sleep_periods,
    load_activity_periods,
    exclude_activity_periods,
)


def apply_paper_filters(hr_df, steps_df, activity_periods, sleep_df):
    """
    論文の条件を厳密に適用

    1. activity_logsの運動時間を除外
    2. 歩数0の時間帯のみ（現在・前の1分間にステップなし）
    3. 睡眠中を除外
    """
    print("\n📋 論文の条件を適用中...")
    print("=" * 60)

    original_count = len(hr_df)

    # 1. 心拍数と歩数をマージ
    hr_steps = hr_df.merge(steps_df, left_index=True, right_index=True, how='inner')
    print(f"1. HR + Steps マージ: {len(hr_steps):,}件 ({len(hr_steps)/original_count*100:.1f}%)")

    # 2. activity_logsの運動時間を除外
    hr_filtered = hr_steps.copy()
    for start_time, end_time in activity_periods:
        mask = (hr_filtered.index >= start_time) & (hr_filtered.index <= end_time)
        hr_filtered = hr_filtered[~mask]

    print(f"2. 運動時間除外後: {len(hr_filtered):,}件 ({len(hr_filtered)/original_count*100:.1f}%)")

    # 3. 歩数0の時間帯のみ（現在・前の1分間にステップなし）
    # 前の1分間の歩数を取得
    hr_filtered = hr_filtered.sort_index()
    hr_filtered['steps_prev'] = hr_filtered['steps'].shift(1)

    # 現在・前の1分間ともに歩数0
    hr_resting = hr_filtered[
        (hr_filtered['steps'] == 0) &
        ((hr_filtered['steps_prev'] == 0) | (hr_filtered['steps_prev'].isna()))
    ].copy()

    print(f"3. 歩数0（現在・前1分）: {len(hr_resting):,}件 ({len(hr_resting)/original_count*100:.1f}%)")

    # 4. 睡眠中を除外
    hr_awake = exclude_sleep_periods(hr_resting, sleep_df)

    print(f"4. 睡眠除外後: {len(hr_awake):,}件 ({len(hr_awake)/original_count*100:.1f}%)")
    print(f"\n総除外率: {(1 - len(hr_awake)/original_count)*100:.1f}%")

    return hr_awake


def prepare_hourly_data_paper_method(hr_awake):
    """
    論文の手法：30日間のデータから1時間ごとの平均を計算
    """
    hourly_means = []
    for hour in range(24):
        hour_data = hr_awake[hr_awake.index.hour == hour]
        if len(hour_data) > 0:
            hourly_means.append(hour_data['heart_rate'].mean())
        else:
            hourly_means.append(np.nan)

    return np.array(hourly_means)


def visualize_paper_method(hourly_hr, params, output_file):
    """論文の手法での可視化"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    t = np.arange(24)
    valid_mask = ~np.isnan(hourly_hr)

    # 上段：データとフィッティング曲線
    ax1.scatter(t[valid_mask], hourly_hr[valid_mask],
               color='darkblue', s=60, alpha=0.7,
               label='Hourly average HR (paper method)', zorder=3)

    # フィッティング曲線
    t_fine = np.linspace(0, 24, 1000)
    hr_fitted = two_harmonic_model(t_fine, params['mu'], params['A1'],
                                   params['phi1'], params['A2'], params['phi2'])
    ax1.plot(t_fine, hr_fitted, 'r-', linewidth=3,
            label='Two-harmonic Fourier model', zorder=4)

    # 第1調和のみ
    hr_1st = params['mu'] + params['A1'] * np.sin(2 * np.pi * t_fine / 24 + params['phi1'])
    ax1.plot(t_fine, hr_1st, 'g--', linewidth=2, alpha=0.7,
            label='First harmonic only (24h)', zorder=2)

    # Bathyphase & Acrophase
    ax1.axvline(params['bathyphase'], color='cyan', linestyle='--', alpha=0.6,
               linewidth=2, label=f"Bathyphase ({format_time(params['bathyphase'])})")
    ax1.axvline(params['acrophase'], color='orange', linestyle='--', alpha=0.6,
               linewidth=2, label=f"Acrophase ({format_time(params['acrophase'])})")

    ax1.set_xlabel('Time (hour)', fontsize=13, fontweight='bold')
    ax1.set_ylabel('Heart Rate (bpm)', fontsize=13, fontweight='bold')
    ax1.set_title('Circadian Rhythm - Paper Method (Two-harmonic Fourier Model)',
                 fontsize=15, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, 24)
    ax1.set_xticks(np.arange(0, 25, 2))

    # 下段：残差
    fitted_hourly = two_harmonic_model(t[valid_mask], params['mu'], params['A1'],
                                      params['phi1'], params['A2'], params['phi2'])
    residuals = hourly_hr[valid_mask] - fitted_hourly

    ax2.bar(t[valid_mask], residuals, color='gray', alpha=0.6, width=0.8)
    ax2.axhline(0, color='black', linestyle='-', linewidth=1)
    ax2.set_xlabel('Time (hour)', fontsize=13, fontweight='bold')
    ax2.set_ylabel('Residuals (bpm)', fontsize=13, fontweight='bold')
    ax2.set_title('Fitting Residuals', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, 24)
    ax2.set_xticks(np.arange(0, 25, 2))

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"✅ 可視化画像を保存: {output_file}")


def generate_paper_method_report(params, hourly_hr):
    """論文手法のレポート生成"""

    valid_hours = np.sum(~np.isnan(hourly_hr))
    amplitude_status = "正常範囲" if 5.0 <= params['A_CR'] <= 10.0 else "範囲外"
    r_squared_status = "非常に良好" if params['r_squared'] >= 0.95 else "良好" if params['r_squared'] >= 0.85 else "要検討"

    report = f"""# サーカディアンリズム分析 - 論文手法完全準拠版

**分析日**: 2026-01-07
**データ期間**: 2025-12-09 ~ 2026-01-07（30日間）
**分析手法**: 2調和フーリエモデル（論文完全準拠）

---

## 適用した条件（論文準拠）

1. ✅ activity_logsの運動時間を除外
2. ✅ 歩数0の時間帯のみ（現在・前の1分間にステップなし）
3. ✅ 睡眠中のデータを除外
4. ✅ 30日間のデータから1時間ごとの平均を計算
5. ✅ 2調和フーリエモデルでフィッティング

**参考論文**: Natarajan et al., "Circadian rhythm of heart rate and activity: A cross-sectional study",
Chronobiology International, 42:1, 108-121 (2025)

---

## サーカディアンパラメータ

| パラメータ | あなた | 論文の期待値 | 評価 |
|-----------|--------|------------|------|
| **μ（24時間平均HR）** | {params['mu']:.2f} bpm | - | - |
| **A₁（第1調和の振幅）** | {abs(params['A1']):.2f} bpm | - | 24時間周期 |
| **A₂（第2調和の振幅）** | {abs(params['A2']):.2f} bpm | - | 12時間周期 |
| **A_CR（サーカディアン振幅）** | **{params['A_CR']:.2f} bpm** | 5-10 bpm | {amplitude_status} |
| **Bathyphase** | **{format_time(params['bathyphase'])}** | 起床の1-3時間前 | - |
| **Acrophase** | **{format_time(params['acrophase'])}** | 就寝の3-9時間前 | - |
| **R²（決定係数）** | **{params['r_squared']:.3f}** | ≥ 0.95 | {r_squared_status} |
| **A₂/A₁ 比率** | {abs(params['A2_A1_ratio']):.3f} | 0.31-0.34 | {'正常' if abs(params['A2_A1_ratio']) < 1.0 else 'ウルトラディアン支配的'} |
| **第1調和の寄与率** | {params['variance_1st_pct']:.1f}% | 約85% | {'✅ 正常' if params['variance_1st_pct'] >= 70 else '⚠️ 低い'} |

---

## 詳細パラメータ

### 基本パラメータ

- **μ（24時間平均心拍数）**: {params['mu']:.2f} bpm
- **A₁（第1調和の振幅、24時間周期）**: {params['A1']:.2f} bpm
- **φ₁（第1調和の位相）**: {params['phi1']:.3f} rad
- **A₂（第2調和の振幅、12時間周期）**: {params['A2']:.2f} bpm
- **φ₂（第2調和の位相）**: {params['phi2']:.3f} rad

### 導出パラメータ

**A_CR（サーカディアン振幅）**: {params['A_CR']:.2f} bpm

計算式: √(A₁² + A₂²) = √({params['A1']:.2f}² + {params['A2']:.2f}²)

これは1日の中での心拍数の変動幅を表します。
- 論文データ: 男性21-30歳 7.6±2.8 bpm、女性 6.2±2.5 bpm
- あなた: {params['A_CR']:.2f} bpm ({amplitude_status})

**Bathyphase（心拍数最低時刻）**: {format_time(params['bathyphase'])}

深い睡眠の時間帯。論文では通常、起床の1-3時間前（中央値: 2.32時間前）です。

**Acrophase（心拍数最高時刻）**: {format_time(params['acrophase'])}

1日で最も活動的な時間帯。論文では通常、就寝の3-9時間前（中央値: 5.86時間前）です。

---

## モデルの精度

**決定係数（R²）**: {params['r_squared']:.3f}

モデルは心拍数変動の **{params['r_squared']*100:.1f}%** を説明しています。

- R² ≥ 0.95: 非常に良好（論文の期待値）
- R² ≥ 0.85: 良好
- R² < 0.85: 要検討

**第1調和の寄与率**: {params['variance_1st_pct']:.1f}%

24時間周期の成分がどれだけ支配的かを示します。
- 論文では約85%の人が第1調和で説明される
- あなた: {params['variance_1st_pct']:.1f}% ({'正常範囲' if params['variance_1st_pct'] >= 70 else '低め - より複雑なリズム'})

**第2調和の寄与率**: {100 - params['variance_1st_pct']:.1f}%

12時間周期の成分が波形の非対称性を補正します。

---

## ウルトラディアンリズム

**A₂/A₁ 比率**: {params['A2_A1_ratio']:.3f}

この値は12時間周期の成分の強さを示します。

- A₂/A₁ < 0.4: 24時間周期が支配的（正常）
- A₂/A₁ > 1.0: 12時間周期が支配的（ウルトラディアンリズム）

論文では、50%の人で A₂/A₁ > 0.31（男性）または > 0.34（女性）です。

---

## データ品質

- **有効な時間帯**: {valid_hours}/24時間
- **フィルタリング条件**: 論文と同じ
  - 運動時間除外
  - 歩数0（現在・前1分間）
  - 睡眠中除外

---

## 可視化

![2調和フーリエモデル](circadian_paper_method.png)

**グラフの見方**:
- **青い点**: 30日間の各時間帯の平均心拍数
- **赤い線**: 2調和フーリエモデルのフィッティング曲線
- **緑の破線**: 第1調和のみ（24時間周期のみ）
- **シアン破線**: Bathyphase（心拍数最低時刻）
- **オレンジ破線**: Acrophase（心拍数最高時刻）

---

## 1時間ごとのデータ

| 時刻 | 心拍数 (bpm) |
|------|-------------|
"""

    for hour in range(24):
        hr = hourly_hr[hour]
        report += f"| {hour:02d}:00 | {hr:.1f} |\n"

    report += """
---

## 参考文献

- Natarajan et al., "Circadian rhythm of heart rate and activity: A cross-sectional study",
  Chronobiology International, 42:1, 108-121 (2025)
  [PubMed](https://pubmed.ncbi.nlm.nih.gov/39807770/)

---

**生成日時**: 2026-01-07
**分析ツール**: dailybuild サーカディアンリズム分析モジュール（論文手法完全準拠版）
"""

    return report


def main():
    print("=" * 70)
    print("サーカディアンリズム分析 - 論文手法完全準拠版")
    print("=" * 70)

    # データ読み込み
    print("\n📊 データ読み込み中...")
    hr_df = pd.read_csv('data/fitbit/heart_rate_intraday.csv',
                       index_col='datetime', parse_dates=True)
    steps_df = pd.read_csv('data/fitbit/steps_intraday.csv',
                          index_col='datetime', parse_dates=True)
    sleep_df = pd.read_csv('data/fitbit/sleep.csv',
                          parse_dates=['startTime', 'endTime'])

    print(f"   心拍数: {len(hr_df):,}件")
    print(f"   歩数: {len(steps_df):,}件")
    print(f"   睡眠: {len(sleep_df)}レコード")

    # activity_logsから運動時間を抽出
    activity_periods = load_activity_periods()
    print(f"\n📋 Activity Logs: {len(activity_periods)}件の運動記録")

    # 論文の条件を適用
    hr_awake = apply_paper_filters(hr_df, steps_df, activity_periods, sleep_df)

    # 1時間ごとの平均を計算
    print("\n⏰ 1時間ごとの平均を計算中（論文の手法）...")
    hourly_hr = prepare_hourly_data_paper_method(hr_awake)

    print(f"\n📈 時間帯ごとのデータ:")
    for hour in range(24):
        count = len(hr_awake[hr_awake.index.hour == hour])
        hr_val = hourly_hr[hour]
        print(f"   {hour:02d}時: {count:4d}件, 平均 {hr_val:.1f} bpm")

    # 2調和フーリエモデルでフィッティング
    print("\n🔬 2調和フーリエモデルをフィッティング中...")
    params = fit_circadian_rhythm(hourly_hr)

    print(f"\n✅ サーカディアンパラメータ（論文の手法）:")
    print(f"   μ（24時間平均心拍数）: {params['mu']:.2f} bpm")
    print(f"   A_CR（サーカディアン振幅）: {params['A_CR']:.2f} bpm")
    print(f"   A₁（第1調和、24時間周期）: {params['A1']:.2f} bpm")
    print(f"   A₂（第2調和、12時間周期）: {params['A2']:.2f} bpm")
    print(f"   Bathyphase（最低時刻）: {format_time(params['bathyphase'])}")
    print(f"   Acrophase（最高時刻）: {format_time(params['acrophase'])}")
    print(f"   R²（決定係数）: {params['r_squared']:.3f}")
    print(f"   A₂/A₁ 比率: {params['A2_A1_ratio']:.3f}")
    print(f"   第1調和の寄与率: {params['variance_1st_pct']:.1f}%")

    # 論文の期待値と比較
    print(f"\n📊 論文の期待値との比較:")
    print(f"   A_CR: {params['A_CR']:.2f} bpm (期待: 5-10 bpm) - {'✅ 正常' if 5 <= params['A_CR'] <= 10 else '⚠️ 範囲外'}")
    print(f"   R²: {params['r_squared']:.3f} (期待: ≥0.95) - {'✅ 非常に良好' if params['r_squared'] >= 0.95 else '✅ 良好' if params['r_squared'] >= 0.85 else '⚠️ 要検討'}")
    print(f"   第1調和: {params['variance_1st_pct']:.1f}% (期待: 約85%) - {'✅ 正常' if params['variance_1st_pct'] >= 70 else '⚠️ 低い'}")

    # 可視化
    print("\n📈 可視化を生成中...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, 'circadian_paper_method.png')
    visualize_paper_method(hourly_hr, params, output_file)

    # レポート生成
    print("\n📄 レポートを生成中...")
    report = generate_paper_method_report(params, hourly_hr)

    report_file = os.path.join(script_dir, 'PAPER_ANALYSIS.md')
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"✅ レポートを生成: {report_file}")

    print("\n" + "=" * 70)
    print("✅ 分析完了！論文の手法に完全準拠した分析です。")
    print(f"   レポート: {report_file}")
    print(f"   画像: {output_file}")
    print("=" * 70)


if __name__ == '__main__':
    main()
