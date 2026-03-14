#!/usr/bin/env python3
"""
睡眠中CGM vs バイタルサイン 多日間分析スクリプト

6夜分のDexcom CGMデータ（2/15-2/21）を対象に、
HR/HRV/SpO2/BR/皮膚温との包括的な相関分析を行う。
"""

import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from scipy import stats
import seaborn as sns
from datetime import datetime

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / 'data'
OUTPUT_DIR = Path(__file__).parent


# =============================================================================
# データ読み込み
# =============================================================================

def load_all_data():
    """全CSVファイルを読み込む"""
    data = {}

    # 睡眠データ
    sleep_path = DATA_DIR / 'fitbit' / 'sleep.csv'
    data['sleep'] = pd.read_csv(sleep_path, parse_dates=['startTime', 'endTime'])

    # 心拍数 intraday
    hr_path = DATA_DIR / 'fitbit' / 'heart_rate_intraday.csv'
    data['hr'] = pd.read_csv(hr_path, parse_dates=['datetime'])

    # HRV intraday（存在する場合）
    hrv_path = DATA_DIR / 'fitbit' / 'hrv_intraday.csv'
    if hrv_path.exists():
        data['hrv'] = pd.read_csv(hrv_path, parse_dates=['datetime'])
        print(f"HRV intraday: {len(data['hrv'])}件 "
              f"({data['hrv']['datetime'].min().date()} ~ {data['hrv']['datetime'].max().date()})")
    else:
        data['hrv'] = pd.DataFrame()
        print("HRV intraday: データなし")

    # SpO2 intraday（存在する場合）
    spo2_path = DATA_DIR / 'fitbit' / 'spo2_intraday.csv'
    if spo2_path.exists():
        data['spo2'] = pd.read_csv(spo2_path, parse_dates=['datetime'])
        print(f"SpO2 intraday: {len(data['spo2'])}件 "
              f"({data['spo2']['datetime'].min().date()} ~ {data['spo2']['datetime'].max().date()})")
    else:
        data['spo2'] = pd.DataFrame()
        print("SpO2 intraday: データなし（fetch_intraday.py --spo2-only で取得可能）")

    # BR intraday（存在する場合）
    br_path = DATA_DIR / 'fitbit' / 'br_intraday.csv'
    if br_path.exists():
        data['br'] = pd.read_csv(br_path, parse_dates=['date'])
        print(f"BR intraday: {len(data['br'])}件")
    else:
        data['br'] = pd.DataFrame()
        print("BR intraday: データなし（fetch_intraday.py --br-only で取得可能）")

    # 皮膚温
    temp_path = DATA_DIR / 'fitbit' / 'temperature_skin.csv'
    data['temp_skin'] = pd.read_csv(temp_path, parse_dates=['date'])

    # Dexcom CGM
    cgm_path = DATA_DIR / 'dexcom.csv'
    data['cgm_raw'] = pd.read_csv(cgm_path, skiprows=range(1, 11))

    return data


def preprocess_cgm(cgm_raw):
    """CGMデータのクリーニング"""
    df = cgm_raw[cgm_raw['イベント タイプ'] == 'EGV'].copy()
    df['timestamp'] = pd.to_datetime(df['タイムスタンプ (YYYY-MM-DDThh:mm:ss)'])
    df['glucose'] = pd.to_numeric(df['グルコース値 (mg/dL)'], errors='coerce')
    df = df[['timestamp', 'glucose']].dropna().sort_values('timestamp').reset_index(drop=True)
    return df


def get_sleep_nights(sleep_df, cgm_df):
    """CGM期間内の睡眠記録を抽出"""
    cgm_start = cgm_df['timestamp'].min()
    cgm_end = cgm_df['timestamp'].max()

    mask = (
        (sleep_df['startTime'] >= cgm_start) &
        (sleep_df['endTime'] <= cgm_end) &
        (sleep_df['minutesAsleep'] >= 180)  # 3時間以上の睡眠のみ
    )
    nights = sleep_df[mask].copy().reset_index(drop=True)
    return nights


# =============================================================================
# 各夜の処理
# =============================================================================

def extract_sleep_window(df, time_col, sleep_start, sleep_end):
    """睡眠時間帯のデータを抽出"""
    return df[
        (df[time_col] >= sleep_start) &
        (df[time_col] <= sleep_end)
    ].copy()


def merge_intraday_signals(sleep_cgm, sleep_hr, sleep_hrv, sleep_spo2):
    """
    CGMを基準に各信号をmerge_asofでマージ

    CGM（5分間隔）をベースとして:
    - HRV（5分間隔）: tolerance=3min
    - SpO2（~1分間隔）: tolerance=3min
    - HR（1分間隔）: 5分平均後 tolerance=3min
    """
    if len(sleep_cgm) == 0:
        return pd.DataFrame()

    # CGMをベースに設定
    base = sleep_cgm.rename(columns={'timestamp': 'datetime'}).sort_values('datetime')

    # HR: 5分リサンプリング
    if len(sleep_hr) > 0:
        hr_5min = (
            sleep_hr.set_index('datetime')['heart_rate']
            .resample('5min')
            .mean()
            .reset_index()
        )
        base = pd.merge_asof(
            base,
            hr_5min.sort_values('datetime'),
            on='datetime',
            direction='nearest',
            tolerance=pd.Timedelta('3min')
        )

    # HRV
    if len(sleep_hrv) > 0:
        base = pd.merge_asof(
            base,
            sleep_hrv[['datetime', 'rmssd', 'hf', 'lf', 'coverage']].sort_values('datetime'),
            on='datetime',
            direction='nearest',
            tolerance=pd.Timedelta('3min')
        )

    # SpO2
    if len(sleep_spo2) > 0:
        base = pd.merge_asof(
            base,
            sleep_spo2[['datetime', 'spo2']].sort_values('datetime'),
            on='datetime',
            direction='nearest',
            tolerance=pd.Timedelta('3min')
        )

    return base


def compute_night_stats(merged, night_label):
    """夜別の相関分析"""
    stats_result = {'night': night_label, 'n': len(merged)}

    pairs = [
        ('glucose', 'heart_rate'),
        ('glucose', 'rmssd'),
        ('glucose', 'hf'),
        ('glucose', 'spo2'),
        ('heart_rate', 'rmssd'),
        ('heart_rate', 'spo2'),
        ('spo2', 'rmssd'),
    ]

    for col_x, col_y in pairs:
        key = f'r_{col_x}_{col_y}'
        p_key = f'p_{col_x}_{col_y}'
        if col_x in merged.columns and col_y in merged.columns:
            valid = merged[[col_x, col_y]].dropna()
            if len(valid) >= 5:
                r, p = stats.pearsonr(valid[col_x], valid[col_y])
                stats_result[key] = round(r, 3)
                stats_result[p_key] = round(p, 4)
            else:
                stats_result[key] = None
                stats_result[p_key] = None
        else:
            stats_result[key] = None
            stats_result[p_key] = None

    # 平均値
    for col in ['glucose', 'heart_rate', 'rmssd', 'spo2']:
        if col in merged.columns:
            stats_result[f'mean_{col}'] = round(merged[col].mean(), 2) if not merged[col].isna().all() else None

    return stats_result


# =============================================================================
# 可視化
# =============================================================================

def generate_nightly_figures(nights_data, nights_df):
    """各夜の時系列図を生成（Figure 1）"""
    n_nights = len(nights_data)
    if n_nights == 0:
        return None

    fig, axes = plt.subplots(n_nights, 3, figsize=(20, 4 * n_nights))
    plt.style.use('dark_background')
    fig.patch.set_facecolor('#1a1a1a')

    if n_nights == 1:
        axes = axes.reshape(1, -1)

    color_glucose = '#FF6B6B'
    color_hr = '#9370DB'
    color_hrv = '#4ECDC4'
    color_spo2 = '#FFD700'

    for i, (night_key, night_info) in enumerate(nights_data.items()):
        merged = night_info['merged']
        sleep_start = night_info['sleep_start']
        sleep_end = night_info['sleep_end']
        night_label = night_info['label']

        ax_ts = axes[i, 0]
        ax_scatter1 = axes[i, 1]
        ax_scatter2 = axes[i, 2]

        ax_ts.set_facecolor('#1a1a1a')
        ax_scatter1.set_facecolor('#1a1a1a')
        ax_scatter2.set_facecolor('#1a1a1a')

        # 時系列: CGM + HR (dual axis)
        if 'glucose' in merged.columns and 'heart_rate' in merged.columns:
            ax_hr = ax_ts.twinx()
            ax_ts.plot(merged['datetime'], merged['glucose'],
                       color=color_glucose, linewidth=2, alpha=0.9, label='CGM')
            ax_hr.plot(merged['datetime'], merged['heart_rate'],
                       color=color_hr, linewidth=1.5, alpha=0.7, label='HR')
            ax_ts.set_ylabel('Glucose (mg/dL)', color=color_glucose, fontsize=9)
            ax_hr.set_ylabel('HR (bpm)', color=color_hr, fontsize=9)
            ax_ts.tick_params(axis='y', labelcolor=color_glucose)
            ax_hr.tick_params(axis='y', labelcolor=color_hr)

        # HRV/SpO2 overlay
        if 'rmssd' in merged.columns:
            ax_hrv = ax_ts.twinx() if 'heart_rate' not in merged.columns else ax_hr.twinx()
            ax_hrv.spines['right'].set_position(('outward', 60))
            ax_hrv.plot(merged['datetime'], merged['rmssd'],
                        color=color_hrv, linewidth=1.5, alpha=0.6, linestyle='--', label='RMSSD')
            ax_hrv.set_ylabel('RMSSD (ms)', color=color_hrv, fontsize=8)
            ax_hrv.tick_params(axis='y', labelcolor=color_hrv)

        ax_ts.set_title(f'{night_label}\n{sleep_start.strftime("%m/%d %H:%M")}～{sleep_end.strftime("%H:%M")}',
                        fontsize=10, loc='left', fontweight='bold')
        ax_ts.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax_ts.grid(True, alpha=0.15)

        # Scatter: glucose vs HR
        ax_scatter1.set_facecolor('#1a1a1a')
        if 'glucose' in merged.columns and 'heart_rate' in merged.columns:
            valid = merged[['glucose', 'heart_rate']].dropna()
            if len(valid) >= 3:
                ax_scatter1.scatter(valid['glucose'], valid['heart_rate'],
                                    alpha=0.5, s=30, color=color_hr, edgecolors='white', linewidth=0.3)
                r = valid['glucose'].corr(valid['heart_rate'])
                z = np.polyfit(valid['glucose'], valid['heart_rate'], 1)
                p = np.poly1d(z)
                x_sorted = valid['glucose'].sort_values()
                ax_scatter1.plot(x_sorted, p(x_sorted), 'r--', linewidth=1.5, alpha=0.7)
                ax_scatter1.set_title(f'CGM vs HR  r={r:.3f}', fontsize=9, loc='left')
        ax_scatter1.set_xlabel('Glucose (mg/dL)', fontsize=8)
        ax_scatter1.set_ylabel('HR (bpm)', fontsize=8)
        ax_scatter1.grid(True, alpha=0.15)

        # Scatter: glucose vs RMSSD
        ax_scatter2.set_facecolor('#1a1a1a')
        if 'glucose' in merged.columns and 'rmssd' in merged.columns:
            valid = merged[['glucose', 'rmssd']].dropna()
            if len(valid) >= 3:
                ax_scatter2.scatter(valid['glucose'], valid['rmssd'],
                                    alpha=0.5, s=30, color=color_hrv, edgecolors='white', linewidth=0.3)
                r = valid['glucose'].corr(valid['rmssd'])
                z = np.polyfit(valid['glucose'], valid['rmssd'], 1)
                p = np.poly1d(z)
                x_sorted = valid['glucose'].sort_values()
                ax_scatter2.plot(x_sorted, p(x_sorted), 'r--', linewidth=1.5, alpha=0.7)
                ax_scatter2.set_title(f'CGM vs RMSSD  r={r:.3f}', fontsize=9, loc='left')
        ax_scatter2.set_xlabel('Glucose (mg/dL)', fontsize=8)
        ax_scatter2.set_ylabel('RMSSD (ms)', fontsize=8)
        ax_scatter2.grid(True, alpha=0.15)

    plt.tight_layout(pad=1.5)
    out_path = OUTPUT_DIR / 'multinight_nightly.png'
    plt.savefig(out_path, dpi=130, facecolor='#1a1a1a', bbox_inches='tight')
    plt.close()
    print(f"Figure 1 保存: {out_path}")
    return out_path


def generate_aggregate_figure(all_merged, night_stats_df):
    """統合分析図を生成（Figure 2）"""
    if len(all_merged) == 0:
        return None

    fig = plt.figure(figsize=(18, 14))
    fig.patch.set_facecolor('#1a1a1a')
    gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.35)

    available_cols = [c for c in ['glucose', 'heart_rate', 'rmssd', 'hf', 'spo2']
                      if c in all_merged.columns and not all_merged[c].isna().all()]
    col_labels = {
        'glucose': '血糖値', 'heart_rate': '心拍数', 'rmssd': 'RMSSD',
        'hf': 'HF', 'spo2': 'SpO2'
    }

    # 1. 相関ヒートマップ
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor('#1a1a1a')
    if len(available_cols) >= 2:
        corr_matrix = all_merged[available_cols].corr()
        labels = [col_labels.get(c, c) for c in available_cols]
        sns.heatmap(corr_matrix, annot=True, fmt='.2f', cmap='coolwarm',
                    center=0, vmin=-1, vmax=1, ax=ax1,
                    xticklabels=labels, yticklabels=labels,
                    annot_kws={'size': 9})
        ax1.set_title('相関ヒートマップ（全夜プール）', fontsize=10, loc='left', fontweight='bold')

    # 2. 夜別 glucose vs HR 相関バーチャート
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor('#1a1a1a')
    if 'r_glucose_heart_rate' in night_stats_df.columns:
        valid = night_stats_df.dropna(subset=['r_glucose_heart_rate'])
        colors = ['#FF6B6B' if r < 0 else '#4ECDC4' for r in valid['r_glucose_heart_rate']]
        bars = ax2.bar(range(len(valid)), valid['r_glucose_heart_rate'], color=colors, alpha=0.8)
        ax2.set_xticks(range(len(valid)))
        ax2.set_xticklabels(valid['night'], rotation=45, fontsize=8)
        ax2.axhline(y=0, color='white', linewidth=0.5)
        ax2.set_ylabel('Pearson r', fontsize=9)
        ax2.set_title('夜別: CGM vs HR 相関係数', fontsize=10, loc='left', fontweight='bold')
        ax2.grid(True, alpha=0.15, axis='y')

    # 3. 夜別 glucose vs RMSSD 相関バーチャート
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.set_facecolor('#1a1a1a')
    if 'r_glucose_rmssd' in night_stats_df.columns:
        valid = night_stats_df.dropna(subset=['r_glucose_rmssd'])
        if len(valid) > 0:
            colors = ['#FF6B6B' if r < 0 else '#4ECDC4' for r in valid['r_glucose_rmssd']]
            ax3.bar(range(len(valid)), valid['r_glucose_rmssd'], color=colors, alpha=0.8)
            ax3.set_xticks(range(len(valid)))
            ax3.set_xticklabels(valid['night'], rotation=45, fontsize=8)
            ax3.axhline(y=0, color='white', linewidth=0.5)
            ax3.set_ylabel('Pearson r', fontsize=9)
            ax3.set_title('夜別: CGM vs RMSSD 相関係数', fontsize=10, loc='left', fontweight='bold')
            ax3.grid(True, alpha=0.15, axis='y')

    # 4. プール scatter: glucose vs HR（色=夜別）
    ax4 = fig.add_subplot(gs[1, 0])
    ax4.set_facecolor('#1a1a1a')
    if 'glucose' in all_merged.columns and 'heart_rate' in all_merged.columns:
        nights_unique = all_merged['night'].unique()
        palette = plt.cm.Set2(np.linspace(0, 1, len(nights_unique)))
        for j, night in enumerate(nights_unique):
            subset = all_merged[all_merged['night'] == night][['glucose', 'heart_rate']].dropna()
            if len(subset) > 0:
                ax4.scatter(subset['glucose'], subset['heart_rate'],
                            alpha=0.5, s=25, color=palette[j], label=night)
        # 全体回帰
        valid_all = all_merged[['glucose', 'heart_rate']].dropna()
        if len(valid_all) >= 5:
            z = np.polyfit(valid_all['glucose'], valid_all['heart_rate'], 1)
            p = np.poly1d(z)
            x_sorted = valid_all['glucose'].sort_values()
            ax4.plot(x_sorted, p(x_sorted), 'r--', linewidth=2, alpha=0.8)
            r_all = valid_all['glucose'].corr(valid_all['heart_rate'])
            ax4.set_title(f'CGM vs HR（全夜）  r={r_all:.3f}', fontsize=10, loc='left', fontweight='bold')
        ax4.legend(fontsize=7, loc='best')
        ax4.set_xlabel('Glucose (mg/dL)', fontsize=9)
        ax4.set_ylabel('HR (bpm)', fontsize=9)
        ax4.grid(True, alpha=0.15)

    # 5. プール scatter: glucose vs RMSSD
    ax5 = fig.add_subplot(gs[1, 1])
    ax5.set_facecolor('#1a1a1a')
    if 'glucose' in all_merged.columns and 'rmssd' in all_merged.columns:
        nights_unique = all_merged['night'].unique()
        palette = plt.cm.Set2(np.linspace(0, 1, len(nights_unique)))
        for j, night in enumerate(nights_unique):
            subset = all_merged[all_merged['night'] == night][['glucose', 'rmssd']].dropna()
            if len(subset) > 0:
                ax5.scatter(subset['glucose'], subset['rmssd'],
                            alpha=0.5, s=25, color=palette[j], label=night)
        valid_all = all_merged[['glucose', 'rmssd']].dropna()
        if len(valid_all) >= 5:
            z = np.polyfit(valid_all['glucose'], valid_all['rmssd'], 1)
            p = np.poly1d(z)
            x_sorted = valid_all['glucose'].sort_values()
            ax5.plot(x_sorted, p(x_sorted), 'r--', linewidth=2, alpha=0.8)
            r_all = valid_all['glucose'].corr(valid_all['rmssd'])
            ax5.set_title(f'CGM vs RMSSD（全夜）  r={r_all:.3f}', fontsize=10, loc='left', fontweight='bold')
        ax5.legend(fontsize=7, loc='best')
        ax5.set_xlabel('Glucose (mg/dL)', fontsize=9)
        ax5.set_ylabel('RMSSD (ms)', fontsize=9)
        ax5.grid(True, alpha=0.15)

    # 6. プール scatter: glucose vs SpO2
    ax6 = fig.add_subplot(gs[1, 2])
    ax6.set_facecolor('#1a1a1a')
    if 'glucose' in all_merged.columns and 'spo2' in all_merged.columns:
        nights_unique = all_merged['night'].unique()
        palette = plt.cm.Set2(np.linspace(0, 1, len(nights_unique)))
        has_spo2 = False
        for j, night in enumerate(nights_unique):
            subset = all_merged[all_merged['night'] == night][['glucose', 'spo2']].dropna()
            if len(subset) > 0:
                ax6.scatter(subset['glucose'], subset['spo2'],
                            alpha=0.5, s=25, color=palette[j], label=night)
                has_spo2 = True
        if has_spo2:
            valid_all = all_merged[['glucose', 'spo2']].dropna()
            if len(valid_all) >= 5:
                z = np.polyfit(valid_all['glucose'], valid_all['spo2'], 1)
                p = np.poly1d(z)
                x_sorted = valid_all['glucose'].sort_values()
                ax6.plot(x_sorted, p(x_sorted), 'r--', linewidth=2, alpha=0.8)
                r_all = valid_all['glucose'].corr(valid_all['spo2'])
                ax6.set_title(f'CGM vs SpO2（全夜）  r={r_all:.3f}', fontsize=10, loc='left', fontweight='bold')
            ax6.legend(fontsize=7, loc='best')
        else:
            ax6.text(0.5, 0.5, 'SpO2データなし', transform=ax6.transAxes,
                     ha='center', va='center', fontsize=12, color='gray')
            ax6.set_title('CGM vs SpO2（データ未取得）', fontsize=10, loc='left', fontweight='bold')
        ax6.set_xlabel('Glucose (mg/dL)', fontsize=9)
        ax6.set_ylabel('SpO2 (%)', fontsize=9)
        ax6.grid(True, alpha=0.15)

    # 7. 夜別サマリー: 平均血糖 + 平均HR
    ax7 = fig.add_subplot(gs[2, 0])
    ax7.set_facecolor('#1a1a1a')
    summary_cols = [c for c in ['mean_glucose', 'mean_heart_rate', 'mean_rmssd'] if c in night_stats_df.columns]
    if 'mean_glucose' in summary_cols and 'mean_heart_rate' in summary_cols:
        valid = night_stats_df.dropna(subset=['mean_glucose', 'mean_heart_rate'])
        x = range(len(valid))
        ax7_hr = ax7.twinx()
        ax7.bar([xi - 0.2 for xi in x], valid['mean_glucose'], width=0.4,
                color='#FF6B6B', alpha=0.8, label='平均血糖')
        ax7_hr.bar([xi + 0.2 for xi in x], valid['mean_heart_rate'], width=0.4,
                   color='#9370DB', alpha=0.8, label='平均HR')
        ax7.set_xticks(x)
        ax7.set_xticklabels(valid['night'], rotation=45, fontsize=8)
        ax7.set_ylabel('Glucose (mg/dL)', color='#FF6B6B', fontsize=9)
        ax7_hr.set_ylabel('HR (bpm)', color='#9370DB', fontsize=9)
        ax7.set_title('夜別: 平均血糖 vs 平均HR', fontsize=10, loc='left', fontweight='bold')
        ax7.grid(True, alpha=0.15, axis='y')

    # 8. 夜別サマリー: 皮膚温 + 呼吸数（存在する場合）
    ax8 = fig.add_subplot(gs[2, 1])
    ax8.set_facecolor('#1a1a1a')
    temp_br_cols = [c for c in ['skin_temp', 'br_full_sleep'] if c in night_stats_df.columns]
    if temp_br_cols:
        valid = night_stats_df.dropna(subset=temp_br_cols[:1])
        if len(valid) > 0:
            x = range(len(valid))
            if 'skin_temp' in temp_br_cols:
                ax8.plot(x, valid['skin_temp'], 'o-', color='#FF8C00', linewidth=2, label='皮膚温変化(℃)')
                ax8.set_ylabel('皮膚温変化 (℃)', color='#FF8C00', fontsize=9)
            if 'br_full_sleep' in temp_br_cols:
                ax8_br = ax8.twinx()
                ax8_br.plot(x, valid['br_full_sleep'], 's--', color='#20B2AA', linewidth=2, label='呼吸数')
                ax8_br.set_ylabel('呼吸数 (回/分)', color='#20B2AA', fontsize=9)
            ax8.set_xticks(x)
            ax8.set_xticklabels(valid['night'], rotation=45, fontsize=8)
            ax8.set_title('夜別: 皮膚温・呼吸数', fontsize=10, loc='left', fontweight='bold')
            ax8.grid(True, alpha=0.15)
    else:
        ax8.text(0.5, 0.5, '皮膚温/BR データなし', transform=ax8.transAxes,
                 ha='center', va='center', fontsize=11, color='gray')
        ax8.set_title('夜別: 皮膚温・呼吸数', fontsize=10, loc='left', fontweight='bold')

    # 9. 夜別 RMSSD平均
    ax9 = fig.add_subplot(gs[2, 2])
    ax9.set_facecolor('#1a1a1a')
    if 'mean_rmssd' in night_stats_df.columns:
        valid = night_stats_df.dropna(subset=['mean_rmssd'])
        if len(valid) > 0:
            colors = ['#4ECDC4'] * len(valid)
            ax9.bar(range(len(valid)), valid['mean_rmssd'], color=colors, alpha=0.8)
            ax9.set_xticks(range(len(valid)))
            ax9.set_xticklabels(valid['night'], rotation=45, fontsize=8)
            ax9.set_ylabel('RMSSD (ms)', fontsize=9)
            ax9.set_title('夜別: 平均RMSSD（HRV）', fontsize=10, loc='left', fontweight='bold')
            ax9.grid(True, alpha=0.15, axis='y')
    else:
        ax9.text(0.5, 0.5, 'HRVデータなし', transform=ax9.transAxes,
                 ha='center', va='center', fontsize=11, color='gray')
        ax9.set_title('夜別: 平均RMSSD（HRV）', fontsize=10, loc='left', fontweight='bold')

    # 背景設定
    for ax in fig.get_axes():
        ax.set_facecolor('#1a1a1a')

    plt.suptitle('睡眠中CGM vs バイタルサイン 多日間統合分析',
                 fontsize=14, fontweight='bold', y=1.01)

    out_path = OUTPUT_DIR / 'multinight_aggregate.png'
    plt.savefig(out_path, dpi=130, facecolor='#1a1a1a', bbox_inches='tight')
    plt.close()
    print(f"Figure 2 保存: {out_path}")
    return out_path


# =============================================================================
# レポート生成
# =============================================================================

def generate_report(nights_data, night_stats_df, all_merged):
    """Markdownレポートを生成"""

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    n_nights = len(night_stats_df)
    n_total = len(all_merged)

    # 全夜プール相関
    pool_corrs = {}
    for col_x, col_y in [('glucose', 'heart_rate'), ('glucose', 'rmssd'),
                          ('glucose', 'spo2'), ('heart_rate', 'rmssd')]:
        if col_x in all_merged.columns and col_y in all_merged.columns:
            valid = all_merged[[col_x, col_y]].dropna()
            if len(valid) >= 5:
                r, p = stats.pearsonr(valid[col_x], valid[col_y])
                pool_corrs[f'{col_x}_vs_{col_y}'] = {'r': r, 'p': p, 'n': len(valid)}

    def fmt_corr(key):
        if key not in pool_corrs:
            return 'データ不足'
        c = pool_corrs[key]
        sig = '✅ 有意(p<0.05)' if c['p'] < 0.05 else '❌ 非有意'
        return f"r={c['r']:.3f}, p={c['p']:.4f}, n={c['n']} [{sig}]"

    # 夜別テーブル
    night_table_rows = []
    for _, row in night_stats_df.iterrows():
        r_hr = f"{row.get('r_glucose_heart_rate', 'N/A'):.3f}" if pd.notna(row.get('r_glucose_heart_rate')) else 'N/A'
        r_hrv = f"{row.get('r_glucose_rmssd', 'N/A'):.3f}" if pd.notna(row.get('r_glucose_rmssd')) else 'N/A'
        r_spo2 = f"{row.get('r_glucose_spo2', 'N/A'):.3f}" if pd.notna(row.get('r_glucose_spo2')) else 'N/A'
        m_g = f"{row.get('mean_glucose', 'N/A'):.1f}" if pd.notna(row.get('mean_glucose')) else 'N/A'
        m_hr = f"{row.get('mean_heart_rate', 'N/A'):.1f}" if pd.notna(row.get('mean_heart_rate')) else 'N/A'
        m_rmssd = f"{row.get('mean_rmssd', 'N/A'):.1f}" if pd.notna(row.get('mean_rmssd')) else 'N/A'
        n = row.get('n', 0)
        night_table_rows.append(
            f"| {row['night']} | {m_g} | {m_hr} | {m_rmssd} | {r_hr} | {r_hrv} | {r_spo2} | {n} |"
        )

    night_table = '\n'.join(night_table_rows)

    report = f"""# 睡眠中CGM vs バイタルサイン 多日間分析

**分析期間**: 2026-02-14 ～ 2026-02-21
**対象夜数**: {n_nights}夜
**総データポイント数**: {n_total}件（マージ後）

## サマリー

### データ利用状況

| データ | 状況 |
|--------|------|
| Dexcom CGM | ✅ 利用（5分間隔）|
| HR intraday | ✅ 利用（1分 → 5分リサンプリング）|
| HRV intraday | {'✅ 利用（5分間隔）' if 'rmssd' in all_merged.columns and not all_merged['rmssd'].isna().all() else '⚠️ データ不足（2/16以前のみ）'} |
| SpO2 intraday | {'✅ 利用' if 'spo2' in all_merged.columns and not all_merged['spo2'].isna().all() else '❌ 未取得（fetch_intraday.py --spo2-only で取得）'} |
| 皮膚温 | 夜別サマリーに含む |
| BR intraday | 夜別サマリーに含む |

---

## 全夜プール相関分析

N={n_total}点の全夜統合データでのPearson相関:

| ペア | 結果 |
|------|------|
| **CGM vs HR** | {fmt_corr('glucose_vs_heart_rate')} |
| **CGM vs HRV (RMSSD)** | {fmt_corr('glucose_vs_rmssd')} |
| **CGM vs SpO2** | {fmt_corr('glucose_vs_spo2')} |
| **HR vs RMSSD** | {fmt_corr('heart_rate_vs_rmssd')} |

---

## 夜別分析

| 夜 | 平均血糖 | 平均HR | 平均RMSSD | r(CGM-HR) | r(CGM-RMSSD) | r(CGM-SpO2) | n |
|----|----------|--------|-----------|-----------|--------------|-------------|---|
{night_table}

*N=6のため夜別相関の統計的有意性判定は参考値のみ*

---

## 可視化

### Figure 1: 各夜の時系列・散布図

![各夜の時系列](multinight_nightly.png)

### Figure 2: 統合分析

![統合分析](multinight_aggregate.png)

---

## 考察

### 全夜プール相関の解釈

"""

    # 自動解釈
    if 'glucose_vs_heart_rate' in pool_corrs:
        c = pool_corrs['glucose_vs_heart_rate']
        if c['r'] < -0.2 and c['p'] < 0.05:
            report += f"- **CGM ↑ → HR ↓（負の相関 r={c['r']:.3f}）**: 高血糖時に心拍数が低下する傾向。睡眠中の夜間血糖ピーク時に迷走神経が抑制され逆に心拍が変化する可能性。\n"
        elif c['r'] > 0.2 and c['p'] < 0.05:
            report += f"- **CGM ↑ → HR ↑（正の相関 r={c['r']:.3f}）**: 高血糖時に交感神経活性化が示唆される。\n"
        else:
            report += f"- **CGM vs HR 相関弱い（r={c['r']:.3f}）**: 明確な一方向の関係は確認できず。夜間の血糖変動範囲が小さい可能性。\n"

    if 'glucose_vs_rmssd' in pool_corrs:
        c = pool_corrs['glucose_vs_rmssd']
        if c['r'] < -0.2 and c['p'] < 0.05:
            report += f"- **CGM ↑ → RMSSD ↓（負の相関 r={c['r']:.3f}）**: 先行研究と一致。高血糖時に副交感神経活動が抑制される。\n"
        elif abs(c['r']) < 0.2:
            report += f"- **CGM vs RMSSD 相関弱い（r={c['r']:.3f}）**: HRVデータのカバレッジ不足（2/16以前のみ）が影響している可能性。\n"

    report += f"""
### 限界と次のステップ

1. **HRVデータギャップ**: 2/17以降のHRV intradayデータがない場合、相関分析の網羅性が低下
   - `python scripts/fetch_intraday.py --hrv-only --start-date 2026-02-17 --end-date 2026-02-21` で補完
2. **SpO2未取得**: SpO2データがあれば低酸素状態と血糖変動の関係を検証できる
   - `python scripts/fetch_intraday.py --spo2-only --start-date 2026-02-14 --end-date 2026-02-21` で取得
3. **N=6の限界**: 夜別サマリーレベルでの統計的検定は不適切（記述統計のみ有効）
4. **個人内変動**: 単一被験者のデータのため外部妥当性に注意

---

## 出力ファイル

- `ANALYSIS_MULTINIGHT.md` — このレポート
- `multinight_nightly.png` — 各夜の時系列・散布図
- `multinight_aggregate.png` — 統合分析図
- `merged_multinight_data.csv` — マージ済みデータ

---
*Generated: {now}*
*Script: analyze_multinight_cgm_vitals.py*
"""

    out_path = OUTPUT_DIR / 'ANALYSIS_MULTINIGHT.md'
    out_path.write_text(report, encoding='utf-8')
    print(f"レポート保存: {out_path}")
    return out_path


# =============================================================================
# メイン
# =============================================================================

def main():
    print("=" * 65)
    print("睡眠中CGM vs バイタルサイン 多日間分析")
    print("=" * 65)

    # 1. データ読み込み
    print("\n[1] データ読み込み")
    data = load_all_data()

    # 2. CGM前処理
    print("\n[2] CGM前処理")
    cgm_df = preprocess_cgm(data['cgm_raw'])
    print(f"CGMデータ: {len(cgm_df)}件 ({cgm_df.timestamp.min().date()} ~ {cgm_df.timestamp.max().date()})")

    # 3. 睡眠記録抽出
    print("\n[3] CGM期間内の睡眠記録")
    nights_df = get_sleep_nights(data['sleep'], cgm_df)
    print(f"対象夜数: {len(nights_df)}夜")
    for _, row in nights_df.iterrows():
        print(f"  {row['dateOfSleep']}: {row['startTime'].strftime('%m/%d %H:%M')} ~ {row['endTime'].strftime('%m/%d %H:%M')} ({row['minutesAsleep']:.0f}分)")

    # 4. 各夜のデータ処理
    print("\n[4] 各夜のデータマージ")
    nights_data = {}
    night_stats_list = []
    all_merged_list = []

    for _, night in nights_df.iterrows():
        date_label = night['dateOfSleep'] if isinstance(night['dateOfSleep'], str) else str(night['dateOfSleep'].date())
        sleep_start = night['startTime']
        sleep_end = night['endTime']
        night_label = f"{pd.to_datetime(date_label).strftime('%m/%d')}"

        print(f"\n  [{night_label}] {sleep_start.strftime('%m/%d %H:%M')} ~ {sleep_end.strftime('%H:%M')}")

        # 各信号の睡眠時間帯抽出
        sleep_cgm = extract_sleep_window(cgm_df, 'timestamp', sleep_start, sleep_end)
        sleep_hr = extract_sleep_window(data['hr'], 'datetime', sleep_start, sleep_end)
        sleep_hrv = extract_sleep_window(data['hrv'], 'datetime', sleep_start, sleep_end) if len(data['hrv']) > 0 else pd.DataFrame()
        sleep_spo2 = extract_sleep_window(data['spo2'], 'datetime', sleep_start, sleep_end) if len(data['spo2']) > 0 else pd.DataFrame()

        print(f"    CGM: {len(sleep_cgm)}件, HR: {len(sleep_hr)}件, HRV: {len(sleep_hrv)}件, SpO2: {len(sleep_spo2)}件")

        # マージ
        merged = merge_intraday_signals(sleep_cgm, sleep_hr, sleep_hrv, sleep_spo2)
        merged['night'] = night_label

        print(f"    マージ後: {len(merged)}件")

        nights_data[night_label] = {
            'merged': merged,
            'sleep_start': sleep_start,
            'sleep_end': sleep_end,
            'label': night_label,
        }

        if len(merged) > 0:
            all_merged_list.append(merged)

        # 夜別統計
        stats_result = compute_night_stats(merged, night_label)
        # BR/皮膚温追加
        date_obj = pd.to_datetime(date_label).date()
        if len(data['br']) > 0:
            br_row = data['br'][data['br']['date'].dt.date == date_obj]
            if len(br_row) > 0:
                stats_result['br_full_sleep'] = br_row.iloc[0].get('br_full_sleep')
        if len(data['temp_skin']) > 0:
            temp_row = data['temp_skin'][data['temp_skin']['date'].dt.date == date_obj]
            if len(temp_row) > 0:
                stats_result['skin_temp'] = temp_row.iloc[0].get('nightly_relative')

        night_stats_list.append(stats_result)

    # 5. 全夜プールデータ
    all_merged = pd.concat(all_merged_list, ignore_index=True) if all_merged_list else pd.DataFrame()
    night_stats_df = pd.DataFrame(night_stats_list)

    print(f"\n[5] 全夜統合: {len(all_merged)}件")

    # 6. 可視化
    print("\n[6] 可視化生成")
    generate_nightly_figures(nights_data, nights_df)
    generate_aggregate_figure(all_merged, night_stats_df)

    # 7. データ保存
    print("\n[7] データ保存")
    csv_path = OUTPUT_DIR / 'merged_multinight_data.csv'
    all_merged.to_csv(csv_path, index=False)
    print(f"マージデータ保存: {csv_path}")

    # 8. レポート生成
    print("\n[8] レポート生成")
    generate_report(nights_data, night_stats_df, all_merged)

    print("\n✅ 分析完了")
    return 0


if __name__ == '__main__':
    sys.exit(main())
