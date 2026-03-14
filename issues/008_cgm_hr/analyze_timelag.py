#!/usr/bin/env python3
"""
CGM vs HR/HRV 時間ラグ（Cross-Correlation）分析

血糖変化の何分後に自律神経（HR・HRV）が反応するかを
cross-correlation で定量化する。
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import correlate, correlation_lags

OUTPUT_DIR = Path(__file__).parent

LAG_MIN = -30   # 分
LAG_MAX = 60    # 分
SAMPLE_MIN = 5  # 1サンプル = 5分


# =============================================================================
# データ準備
# =============================================================================

def load_merged_data():
    path = OUTPUT_DIR / 'merged_multinight_data.csv'
    df = pd.read_csv(path, parse_dates=['datetime'])
    return df


def prepare_night_signals(night_df, cols):
    """
    指定列を持つ夜データを前処理:
    - 線形補間でNaN埋め（端はdrop）
    - z-score正規化
    """
    df = night_df[['datetime'] + cols].copy().sort_values('datetime').reset_index(drop=True)
    df[cols] = df[cols].interpolate(method='linear').dropna(axis=0)
    df = df.dropna(subset=cols).reset_index(drop=True)

    normalized = {}
    for col in cols:
        s = df[col]
        std = s.std()
        if std > 0:
            normalized[col] = (s - s.mean()) / std
        else:
            normalized[col] = s - s.mean()
    return df, normalized


# =============================================================================
# Cross-Correlation 計算
# =============================================================================

def compute_xcorr(x, y, lag_range_min=(LAG_MIN, LAG_MAX)):
    """
    x→y の cross-correlation を計算

    Returns:
        lags_min: ラグ配列（分）
        xcorr: 相関係数配列（-1〜+1）
        peak_lag: ピークラグ（分）
        peak_r: ピーク相関係数
    """
    x = np.array(x)
    y = np.array(y)
    n = len(x)

    corr = correlate(y, x, mode='full')
    lags = correlation_lags(n, n, mode='full')
    lags_min = lags * SAMPLE_MIN

    # 正規化（最大値=1になるように）
    corr = corr / (n * x.std() * y.std() + 1e-10)

    # ラグ範囲でフィルタ
    mask = (lags_min >= lag_range_min[0]) & (lags_min <= lag_range_min[1])
    lags_min = lags_min[mask]
    xcorr = corr[mask]

    peak_idx = np.argmax(np.abs(xcorr))
    peak_lag = lags_min[peak_idx]
    peak_r = xcorr[peak_idx]

    return lags_min, xcorr, peak_lag, peak_r


PAIRS = [
    ('glucose', 'heart_rate', 'CGM → HR'),
    ('glucose', 'rmssd',      'CGM → RMSSD'),
    ('glucose', 'spo2',       'CGM → SpO2'),
]

NIGHT_COLORS = ['#FF6B6B', '#4ECDC4', '#FFD700', '#9370DB', '#20B2AA']


# =============================================================================
# 可視化
# =============================================================================

def generate_figure(nights_xcorr, pooled_xcorr, night_labels):
    """
    2段構成:
    上: 夜別 cross-correlogram（3列）
    下: 全夜プール cross-correlogram（3列）
    """
    n_pairs = len(PAIRS)
    fig, axes = plt.subplots(2, n_pairs, figsize=(18, 10))
    fig.patch.set_facecolor('#1a1a1a')
    plt.style.use('dark_background')

    ci = 2 / np.sqrt(len(pooled_xcorr.get(PAIRS[0][0], {}).get('x', [1])) + 1)

    for col_idx, (x_col, y_col, label) in enumerate(PAIRS):
        # 上段: 夜別
        ax_top = axes[0, col_idx]
        ax_top.set_facecolor('#1a1a1a')
        ax_top.axvline(0, color='white', linewidth=0.8, linestyle='--', alpha=0.5)
        ax_top.axhline(0, color='white', linewidth=0.5, alpha=0.3)

        for night_idx, night_label in enumerate(night_labels):
            key = (night_label, x_col, y_col)
            if key not in nights_xcorr:
                continue
            lags, xcorr, peak_lag, peak_r = nights_xcorr[key]
            color = NIGHT_COLORS[night_idx % len(NIGHT_COLORS)]
            ax_top.plot(lags, xcorr, color=color, linewidth=1.5, alpha=0.8,
                        label=f'{night_label} (peak {peak_lag:+.0f}min, r={peak_r:.2f})')

        ax_top.set_title(label, fontsize=11, fontweight='bold', loc='left')
        ax_top.set_xlabel('Lag (min)', fontsize=9)
        ax_top.set_ylabel('Cross-correlation', fontsize=9)
        ax_top.legend(fontsize=7, loc='upper right', framealpha=0.6)
        ax_top.grid(True, alpha=0.12)
        ax_top.set_xlim(LAG_MIN, LAG_MAX)

        # 下段: プール
        ax_bot = axes[1, col_idx]
        ax_bot.set_facecolor('#1a1a1a')
        ax_bot.axvline(0, color='white', linewidth=0.8, linestyle='--', alpha=0.5)
        ax_bot.axhline(0, color='white', linewidth=0.5, alpha=0.3)

        pkey = (x_col, y_col)
        if pkey in pooled_xcorr:
            lags, xcorr, peak_lag, peak_r, n_pts = pooled_xcorr[pkey]

            # 95%信頼区間
            ci_band = 2 / np.sqrt(n_pts)
            ax_bot.fill_between(lags, -ci_band, ci_band, color='gray', alpha=0.2, label='95% CI')

            ax_bot.plot(lags, xcorr, color='#FF6B6B', linewidth=2.5, alpha=0.95)

            # ピークアノテーション
            ax_bot.axvline(peak_lag, color='yellow', linewidth=1.2, linestyle=':')
            ax_bot.annotate(f'peak: {peak_lag:+.0f} min\nr={peak_r:.3f}',
                            xy=(peak_lag, peak_r),
                            xytext=(peak_lag + 5, peak_r * 0.7 if peak_r > 0 else peak_r * 0.7),
                            fontsize=9, color='yellow',
                            arrowprops=dict(arrowstyle='->', color='yellow', lw=1.2))

            ax_bot.set_title(f'{label} [pooled N={n_pts}]', fontsize=11, fontweight='bold', loc='left')
            ax_bot.legend(fontsize=8, loc='upper left', framealpha=0.6)

        ax_bot.set_xlabel('Lag (min)', fontsize=9)
        ax_bot.set_ylabel('Cross-correlation', fontsize=9)
        ax_bot.grid(True, alpha=0.12)
        ax_bot.set_xlim(LAG_MIN, LAG_MAX)

    # 行ラベル
    axes[0, 0].set_ylabel('Per-night\nCross-correlation', fontsize=10, fontweight='bold')
    axes[1, 0].set_ylabel('Pooled (all nights)\nCross-correlation', fontsize=10, fontweight='bold')

    plt.suptitle('CGM vs Autonomic Signals: Time-Lag Cross-Correlation Analysis',
                 fontsize=13, fontweight='bold', y=1.01, color='white')

    plt.tight_layout(pad=1.5)
    out_path = OUTPUT_DIR / 'timelag_xcorr.png'
    plt.savefig(out_path, dpi=140, facecolor='#1a1a1a', bbox_inches='tight')
    plt.close()
    print(f"図保存: {out_path}")
    return out_path


# =============================================================================
# レポート生成
# =============================================================================

def generate_report(nights_xcorr, pooled_xcorr, night_labels):
    from datetime import datetime

    def sign_str(v):
        return f'+{v:.0f}' if v >= 0 else f'{v:.0f}'

    lines = []
    lines.append("# CGM vs HR/HRV 時間ラグ分析\n")
    lines.append(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append("")
    lines.append("## 分析概要\n")
    lines.append("血糖変化の何分後に自律神経（HR・HRV・SpO2）が反応するかを")
    lines.append("cross-correlation（交差相関）で定量化した。")
    lines.append(f"- ラグ範囲: {LAG_MIN}分 〜 {LAG_MAX}分")
    lines.append("- 正のラグ: 血糖変化 → 後から自律神経が反応（血糖が先行）")
    lines.append("- 負のラグ: 自律神経変化 → 後から血糖が変化（心拍が先行）")
    lines.append("")
    lines.append("---\n")
    lines.append("## 全夜プール Cross-Correlation ピーク\n")
    lines.append("| ペア | ピークラグ | ピーク相関 | 解釈 |")
    lines.append("|------|-----------|-----------|------|")

    for x_col, y_col, label in PAIRS:
        pkey = (x_col, y_col)
        if pkey in pooled_xcorr:
            lags, xcorr, peak_lag, peak_r, n_pts = pooled_xcorr[pkey]
            if peak_lag > 5:
                interp = f"血糖変化の約{peak_lag:.0f}分後に{y_col}が反応"
            elif peak_lag < -5:
                interp = f"{y_col}変化の約{-peak_lag:.0f}分後に血糖が変化"
            else:
                interp = "ほぼ同時変動（ラグなし）"
            direction = '正' if peak_r > 0 else '負'
            lines.append(f"| {label} | {sign_str(peak_lag)} 分 | r={peak_r:.3f}（{direction}の相関） | {interp} |")
        else:
            lines.append(f"| {label} | — | — | データ不足 |")

    lines.append("")
    lines.append("---\n")
    lines.append("## 夜別ピークラグ一覧\n")
    lines.append("| 夜 | CGM→HR peak | CGM→RMSSD peak | CGM→SpO2 peak |")
    lines.append("|----|-------------|----------------|----------------|")

    for night_label in night_labels:
        row = [f"| {night_label}"]
        for x_col, y_col, _ in PAIRS:
            key = (night_label, x_col, y_col)
            if key in nights_xcorr:
                _, _, peak_lag, peak_r = nights_xcorr[key]
                row.append(f"{sign_str(peak_lag)}分 (r={peak_r:.2f})")
            else:
                row.append("—")
        lines.append(" | ".join(row) + " |")

    lines.append("")
    lines.append("---\n")
    lines.append("## 可視化\n")
    lines.append("![Cross-Correlation Analysis](timelag_xcorr.png)\n")
    lines.append("")
    lines.append("---\n")
    lines.append("## 生理学的解釈\n")

    # 自動解釈
    for x_col, y_col, label in PAIRS:
        pkey = (x_col, y_col)
        if pkey not in pooled_xcorr:
            continue
        _, _, peak_lag, peak_r, n_pts = pooled_xcorr[pkey]
        lines.append(f"### {label}")
        if abs(peak_lag) <= 5:
            lines.append(f"- ピークラグ {sign_str(peak_lag)}分: 血糖と{y_col}はほぼ**同時変動**")
            lines.append("  - 共通の第三因子（睡眠ステージ転換など）が両者を同時に動かしている可能性")
        elif 5 < peak_lag <= 20:
            lines.append(f"- ピークラグ +{peak_lag:.0f}分: 血糖上昇の約{peak_lag:.0f}分後に{y_col}が反応")
            lines.append("  - インスリン分泌→血糖応答→交感神経活性化の時定数に対応する可能性")
        elif peak_lag > 20:
            lines.append(f"- ピークラグ +{peak_lag:.0f}分: 血糖上昇から{peak_lag:.0f}分後に{y_col}が変化")
            lines.append("  - 遅延応答。睡眠ステージ変化などの交絡因子の影響が大きい可能性")
        else:
            lines.append(f"- ピークラグ {sign_str(peak_lag)}分: {y_col}が血糖より先に変化")
            lines.append("  - 交感神経先行→血糖応答、またはデータの非対称性による可能性")
        lines.append("")

    lines.append("---\n")
    lines.append("## 注意事項\n")
    lines.append("- N=5夜、各夜80〜100点の短時間時系列のため解釈は暫定的")
    lines.append("- 睡眠ステージの影響（Deep→REM転換時の自律神経変化）が交絡している可能性あり")
    lines.append("- cross-correlationはlinear関係のみを捉える（非線形応答は見逃す）")
    lines.append("")

    report = "\n".join(lines)
    out_path = OUTPUT_DIR / 'ANALYSIS_TIMELAG.md'
    out_path.write_text(report, encoding='utf-8')
    print(f"レポート保存: {out_path}")
    return out_path


# =============================================================================
# メイン
# =============================================================================

def main():
    print("=" * 60)
    print("CGM vs HR/HRV 時間ラグ（Cross-Correlation）分析")
    print("=" * 60)

    df = load_merged_data()
    print(f"データ読み込み: {len(df)}件, {df['night'].nunique()}夜")

    night_labels = sorted(df['night'].unique())
    nights_xcorr = {}

    # 夜別 cross-correlation
    print("\n[夜別 Cross-Correlation]")
    for night_label in night_labels:
        night_df = df[df['night'] == night_label]
        for x_col, y_col, label in PAIRS:
            cols_needed = [x_col, y_col]
            if y_col not in night_df.columns:
                continue
            try:
                _, normalized = prepare_night_signals(night_df, cols_needed)
                if len(normalized.get(x_col, [])) < 10:
                    continue
                lags, xcorr, peak_lag, peak_r = compute_xcorr(
                    normalized[x_col].values,
                    normalized[y_col].values
                )
                nights_xcorr[(night_label, x_col, y_col)] = (lags, xcorr, peak_lag, peak_r)
                print(f"  {night_label} | {label}: peak {peak_lag:+.0f}min, r={peak_r:.3f}")
            except Exception as e:
                print(f"  {night_label} | {label}: エラー ({e})")

    # 全夜プール cross-correlation
    print("\n[全夜プール Cross-Correlation]")
    pooled_xcorr = {}
    for x_col, y_col, label in PAIRS:
        cols_needed = [x_col, y_col]
        valid_nights = [
            df[df['night'] == nl]
            for nl in night_labels
            if (nl, x_col, y_col) in nights_xcorr
        ]
        if not valid_nights:
            continue

        # 各夜の normalized signal を結合
        all_x, all_y = [], []
        for night_df in valid_nights:
            try:
                _, normalized = prepare_night_signals(night_df, cols_needed)
                all_x.extend(normalized[x_col].values.tolist())
                all_y.extend(normalized[y_col].values.tolist())
            except Exception:
                pass

        if len(all_x) < 20:
            continue

        all_x = np.array(all_x)
        all_y = np.array(all_y)
        lags, xcorr, peak_lag, peak_r = compute_xcorr(all_x, all_y)
        pooled_xcorr[(x_col, y_col)] = (lags, xcorr, peak_lag, peak_r, len(all_x))
        print(f"  {label}: peak {peak_lag:+.0f}min, r={peak_r:.3f}, N={len(all_x)}")

    # 可視化
    print("\n[可視化生成]")
    generate_figure(nights_xcorr, pooled_xcorr, night_labels)

    # レポート
    print("\n[レポート生成]")
    generate_report(nights_xcorr, pooled_xcorr, night_labels)

    print("\n✅ 完了")
    return 0


if __name__ == '__main__':
    sys.exit(main())
