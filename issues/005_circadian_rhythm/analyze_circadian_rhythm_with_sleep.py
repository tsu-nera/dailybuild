#!/usr/bin/env python3
"""
サーカディアンリズム分析スクリプト（睡眠中データ含む）

睡眠中のデータも含めて分析することで、Bathyphaseを正確に推定する。

Usage:
    python scripts/analyze_circadian_rhythm_with_sleep.py
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # GUIなし環境対応

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.lib.analytics.circadian import (
    two_harmonic_model,
    prepare_hourly_data,
    fit_circadian_rhythm,
    format_time
)


def main():
    """メイン処理"""
    print("=" * 60)
    print("サーカディアンリズム分析（睡眠中データ含む）")
    print("=" * 60)

    # データファイルパス
    hr_intraday_file = 'data/fitbit/heart_rate_intraday.csv'
    sleep_file = 'data/fitbit/sleep.csv'
    output_dir = 'issues/005_circadian_rhythm'

    # 出力ディレクトリを作成
    os.makedirs(output_dir, exist_ok=True)

    # データ読み込み
    print("\n📊 データを読み込み中...")
    hr_df = pd.read_csv(hr_intraday_file, index_col='datetime', parse_dates=True)
    sleep_df = pd.read_csv(sleep_file, parse_dates=['startTime', 'endTime'])

    print(f"   Heart Rate Intraday: {len(hr_df):,}件")
    print(f"   期間: {hr_df.index.min()} ~ {hr_df.index.max()}")

    # 1時間ごとの平均を計算（睡眠除外なし）
    print("\n⏰ 1時間ごとの平均を計算中（睡眠中も含む）...")
    hourly_hr = prepare_hourly_data(hr_df, sleep_df=None)  # sleep_df=None で除外しない

    # 各時間帯のデータ件数を表示
    print("\n📈 時間帯ごとのデータ状況:")
    for hour in range(24):
        count = len(hr_df[hr_df.index.hour == hour])
        mean_hr = hourly_hr[hour]
        status = "OK" if not np.isnan(mean_hr) else "欠損"
        print(f"   {hour:02d}時: {count:4d}件, 平均HR: {mean_hr:5.1f} bpm ({status})")

    # 2調和フーリエモデルでフィッティング
    print("\n🔬 2調和フーリエモデルでフィッティング中...")
    params = fit_circadian_rhythm(hourly_hr)

    print("\n✅ サーカディアンパラメータ:")
    print(f"   μ（平均心拍数）: {params['mu']:.2f} bpm")
    print(f"   A_CR（サーカディアン振幅）: {params['A_CR']:.2f} bpm")
    print(f"   A₁（第1調和、24時間周期）: {params['A1']:.2f} bpm")
    print(f"   A₂（第2調和、12時間周期）: {params['A2']:.2f} bpm")
    print(f"   Bathyphase（最低時刻）: {format_time(params['bathyphase'])}")
    print(f"   Acrophase（最高時刻）: {format_time(params['acrophase'])}")
    print(f"   R²（決定係数）: {params['r_squared']:.3f}")
    print(f"   A₂/A₁ 比率: {params['A2_A1_ratio']:.3f}")
    print(f"   第1調和の寄与率: {params['variance_1st_pct']:.1f}%")

    # 可視化
    print("\n📈 可視化を生成中...")
    t_fine = np.linspace(0, 24, 1000)
    hr_fitted = two_harmonic_model(t_fine, params['mu'], params['A1'],
                                   params['phi1'], params['A2'], params['phi2'])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

    # プロット1: データとフィッティング曲線
    t_hourly = np.arange(24)
    valid_mask = ~np.isnan(hourly_hr)

    ax1.scatter(t_hourly[valid_mask], hourly_hr[valid_mask],
               color='blue', s=50, alpha=0.6, label='1-hour average HR')
    ax1.plot(t_fine, hr_fitted, 'r-', linewidth=2, label='Two-harmonic Fourier model')

    # 第1調和のみの曲線
    hr_1st_only = params['mu'] + params['A1'] * np.sin(2 * np.pi * t_fine / 24 + params['phi1'])
    ax1.plot(t_fine, hr_1st_only, 'g--', linewidth=1.5, alpha=0.7,
            label='First harmonic only (24h)')

    # Bathyphase & Acrophase をマーク
    ax1.axvline(params['bathyphase'], color='cyan', linestyle='--', alpha=0.5,
               label=f"Bathyphase ({format_time(params['bathyphase'])})")
    ax1.axvline(params['acrophase'], color='orange', linestyle='--', alpha=0.5,
               label=f"Acrophase ({format_time(params['acrophase'])})")

    # 平均起床時刻と就寝時刻をマーク
    avg_wake_hour = sleep_df['endTime'].dt.hour.mean() + sleep_df['endTime'].dt.minute.mean() / 60
    avg_bed_hour = sleep_df['startTime'].dt.hour.mean() + sleep_df['startTime'].dt.minute.mean() / 60

    ax1.axvline(avg_wake_hour, color='green', linestyle=':', alpha=0.3,
               label=f"Avg wake time ({format_time(avg_wake_hour)})")
    ax1.axvline(avg_bed_hour, color='purple', linestyle=':', alpha=0.3,
               label=f"Avg bed time ({format_time(avg_bed_hour)})")

    ax1.set_xlabel('Time (hour)', fontsize=12)
    ax1.set_ylabel('Heart Rate (bpm)', fontsize=12)
    ax1.set_title('Circadian Rhythm Analysis - Two-harmonic Fourier Model (with sleep data)',
                 fontsize=14, fontweight='bold')
    ax1.legend(loc='upper right', fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, 24)
    ax1.set_xticks(np.arange(0, 25, 2))

    # プロット2: 残差
    fitted_hourly = two_harmonic_model(t_hourly[valid_mask], params['mu'], params['A1'],
                                      params['phi1'], params['A2'], params['phi2'])
    residuals = hourly_hr[valid_mask] - fitted_hourly

    ax2.bar(t_hourly[valid_mask], residuals, color='gray', alpha=0.6, width=0.8)
    ax2.axhline(0, color='black', linestyle='-', linewidth=0.8)
    ax2.set_xlabel('Time (hour)', fontsize=12)
    ax2.set_ylabel('Residuals (bpm)', fontsize=12)
    ax2.set_title('Fitting Residuals', fontsize=12, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, 24)
    ax2.set_xticks(np.arange(0, 25, 2))

    plt.tight_layout()
    image_file = os.path.join(output_dir, 'circadian_with_sleep.png')
    plt.savefig(image_file, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"✅ 可視化画像を保存: {image_file}")

    # Markdownレポート生成
    print("\n📄 Markdownレポートを生成中...")

    # 位相差を計算
    bathyphase_wake_diff = avg_wake_hour - params['bathyphase']
    if bathyphase_wake_diff < 0:
        bathyphase_wake_diff += 24

    acrophase_bed_diff = avg_bed_hour - params['acrophase']
    if acrophase_bed_diff < 0:
        acrophase_bed_diff += 24

    valid_hours = np.sum(~np.isnan(hourly_hr))
    data_quality = "良好" if valid_hours >= 20 else "要検討"
    amplitude_status = "正常範囲" if 5.0 <= params['A_CR'] <= 10.0 else "要確認"
    r_squared_status = "非常に良好" if params['r_squared'] > 0.95 else "良好" if params['r_squared'] > 0.85 else "要検討"

    markdown = f"""# サーカディアンリズム分析レポート（睡眠中データ含む）

**分析日**: 2026-01-07
**データ期間**: 2025-12-09 ~ 2026-01-07（30日間）
**分析手法**: 2調和フーリエモデル（論文: Circadian rhythm of heart rate and activity, 2025）
**注**: 睡眠中のデータも含めて分析しています

---

## サマリー

| 指標 | 値 | 評価 | 参考値（論文） |
|------|-----|------|---------------|
| **サーカディアン振幅（A_CR）** | **{params['A_CR']:.2f} bpm** | {amplitude_status} | 5-10 bpm |
| **決定係数（R²）** | **{params['r_squared']:.3f}** | {r_squared_status} | ≥ 0.95 |
| **Bathyphase（最低時刻）** | **{format_time(params['bathyphase'])}** | - | 起床の1-3時間前 |
| **Acrophase（最高時刻）** | **{format_time(params['acrophase'])}** | - | 就寝の3-9時間前 |
| **A₂/A₁ 比率** | **{params['A2_A1_ratio']:.3f}** | {'正常' if params['A2_A1_ratio'] < 1.0 else 'ウルトラディアン支配的'} | 0.31-0.34 |

---

## サーカディアンパラメータ詳細

### 基本パラメータ

- **μ（24時間平均心拍数）**: {params['mu']:.2f} bpm
- **A₁（第1調和の振幅、24時間周期）**: {params['A1']:.2f} bpm
- **A₂（第2調和の振幅、12時間周期）**: {params['A2']:.2f} bpm
- **φ₁（第1調和の位相）**: {params['phi1']:.3f} rad
- **φ₂（第2調和の位相）**: {params['phi2']:.3f} rad

### 導出パラメータ

- **A_CR（サーカディアン振幅）**: {params['A_CR']:.2f} bpm
  計算式: √(A₁² + A₂²) = √({params['A1']:.2f}² + {params['A2']:.2f}²)

- **Bathyphase（心拍数最低時刻）**: {format_time(params['bathyphase'])}
  起床時刻（平均 {format_time(avg_wake_hour)}）の **{bathyphase_wake_diff:.1f}時間前**

- **Acrophase（心拍数最高時刻）**: {format_time(params['acrophase'])}
  就寝時刻（平均 {format_time(avg_bed_hour)}）の **{acrophase_bed_diff:.1f}時間前**

---

## モデルの精度

- **決定係数（R²）**: {params['r_squared']:.3f}
  → モデルは心拍数変動の **{params['r_squared']*100:.1f}%** を説明

- **第1調和の寄与率**: {params['variance_1st_pct']:.1f}%
  → 24時間周期の成分の寄与

- **第2調和の寄与率**: {100 - params['variance_1st_pct']:.1f}%
  → 12時間周期の成分が波形の非対称性を捕捉

---

## ウルトラディアンリズム

- **A₂/A₁ 比率**: {params['A2_A1_ratio']:.3f}

{'ウルトラディアンリズム（12時間周期）が支配的です。' if params['A2_A1_ratio'] > 1.0 else '24時間周期が支配的で、正常範囲です。'}

論文によれば、50%の人で A₂/A₁ > 0.31（男性）または > 0.34（女性）です。
A₂/A₁ > 1.0 の場合、ウルトラディアンリズム（12時間周期）が支配的となります。

---

## データ品質

- **有効な時間帯**: {valid_hours}/24時間
- **データ品質**: {data_quality}
- **総データ件数**: {len(hr_df):,}件

---

## 可視化

![サーカディアンリズム](circadian_with_sleep.png)

**グラフの見方**:
- **青い点**: 30日間の各時間帯の平均心拍数（睡眠中含む）
- **赤い線**: 2調和フーリエモデルのフィッティング曲線
- **緑の破線**: 第1調和のみ（24時間周期のみ）
- **シアン破線**: Bathyphase（心拍数最低時刻）
- **オレンジ破線**: Acrophase（心拍数最高時刻）
- **緑の点線**: 平均起床時刻
- **紫の点線**: 平均就寝時刻

---

## 解釈

### サーカディアン振幅

サーカディアン振幅は **{params['A_CR']:.1f} bpm** です。

論文データでは、男性21-30歳で平均 7.6±2.8 bpm、女性で 6.2±2.5 bpm です。
振幅は年齢とともに減少し、男性の方が女性より大きい傾向があります。

### 位相関係

**Bathyphase（心拍数最低時刻）**: {format_time(params['bathyphase'])}
- 起床時刻の **{bathyphase_wake_diff:.1f}時間前**
- 論文の期待値: 起床の1-3時間前（中央値: 2.32時間前）

**Acrophase（心拍数最高時刻）**: {format_time(params['acrophase'])}
- 就寝時刻の **{acrophase_bed_diff:.1f}時間前**
- 論文の期待値: 就寝の3-9時間前（中央値: 5.86時間前）

### モデルの精度

決定係数（R²）は **{params['r_squared']:.3f}** で、{r_squared_status}です。

論文では R² ≥ 0.95 が期待されます。
第1調和のみでは約85%の分散しか説明できませんが、第2調和を追加することで約98%まで向上します。

---

## 参考文献

- Natarajan et al., "Circadian rhythm of heart rate and activity: A cross-sectional study",
  Chronobiology International, 42:1, 108-121 (2025)
  [PubMed](https://pubmed.ncbi.nlm.nih.gov/39807770/)

---

**生成日時**: 2026-01-07
**分析ツール**: dailybuild サーカディアンリズム分析モジュール
"""

    report_file = os.path.join(output_dir, 'PAPER_ANALYSIS_WITH_SLEEP.md')
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(markdown)

    print(f"✅ Markdownレポートを生成: {report_file}")

    print("\n" + "=" * 60)
    print("✅ 分析完了！")
    print(f"   レポート: {report_file}")
    print(f"   画像: {image_file}")
    print("=" * 60)


if __name__ == '__main__':
    main()
