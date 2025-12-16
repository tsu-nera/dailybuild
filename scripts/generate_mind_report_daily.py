#!/usr/bin/env python
# coding: utf-8
"""
メンタルコンディションレポート生成スクリプト

Usage:
    python generate_mind_report_daily.py --days 7
    python generate_mind_report_daily.py --days 14 --output reports/mind
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.analytics import mind

BASE_DIR = project_root
HRV_CSV = BASE_DIR / 'data/fitbit/hrv.csv'
HEART_RATE_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'
SLEEP_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
BREATHING_RATE_CSV = BASE_DIR / 'data/fitbit/breathing_rate.csv'
SPO2_CSV = BASE_DIR / 'data/fitbit/spo2.csv'
CARDIO_SCORE_CSV = BASE_DIR / 'data/fitbit/cardio_score.csv'
TEMPERATURE_SKIN_CSV = BASE_DIR / 'data/fitbit/temperature_skin.csv'


def load_data(days=None):
    """
    各種データを読み込み

    Args:
        days: 読み込む日数（Noneで全データ）

    Returns:
        dict: 各データフレーム
    """
    data = {}

    # HRV（必須）
    if HRV_CSV.exists():
        df = pd.read_csv(HRV_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['hrv'] = df
    else:
        print(f"警告: {HRV_CSV} が見つかりません")
        return None

    # 心拍数
    if HEART_RATE_CSV.exists():
        df = pd.read_csv(HEART_RATE_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['heart_rate'] = df

    # 睡眠
    if SLEEP_CSV.exists():
        df = pd.read_csv(SLEEP_CSV)
        df['dateOfSleep'] = pd.to_datetime(df['dateOfSleep'])
        if days:
            df = df.tail(days)
        data['sleep'] = df

    # 呼吸数（オプション）
    if BREATHING_RATE_CSV.exists():
        df = pd.read_csv(BREATHING_RATE_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['breathing_rate'] = df

    # SpO2（オプション）
    if SPO2_CSV.exists():
        df = pd.read_csv(SPO2_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['spo2'] = df

    # 心肺スコア（オプション）
    if CARDIO_SCORE_CSV.exists():
        df = pd.read_csv(CARDIO_SCORE_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['cardio_score'] = df

    # 皮膚温（オプション）
    if TEMPERATURE_SKIN_CSV.exists():
        df = pd.read_csv(TEMPERATURE_SKIN_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['temperature_skin'] = df

    return data


def plot_hrv_chart(daily_data, save_path):
    """
    HRV推移グラフを生成

    Args:
        daily_data: 日別データリスト
        save_path: 保存パス
    """
    if not daily_data:
        return

    dates = [d['date'] for d in daily_data]
    date_labels = [pd.to_datetime(d).strftime('%m-%d') for d in dates]

    fig, ax = plt.subplots(figsize=(10, 5))

    # HRV
    hrv_values = [d.get('daily_rmssd', np.nan) for d in daily_data]
    if any(not np.isnan(v) for v in hrv_values):
        ax.plot(range(len(dates)), hrv_values, 'o-', color='#3498DB',
                label='HRV (RMSSD)', linewidth=2, markersize=6)

    ax.set_ylabel('RMSSD (ms)')
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels(date_labels, rotation=45)
    ax.set_title('HRV Trend')
    ax.grid(axis='y', alpha=0.3)
    ax.legend(loc='upper left')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def plot_hrv_rhr_chart(daily_data, save_path):
    """
    HRV vs 心拍数の二軸グラフを生成

    Args:
        daily_data: 日別データリスト
        save_path: 保存パス
    """
    if not daily_data:
        return

    dates = [d['date'] for d in daily_data]
    date_labels = [pd.to_datetime(d).strftime('%m-%d') for d in dates]

    fig, ax1 = plt.subplots(figsize=(10, 5))

    # HRV (左軸)
    hrv_values = [d.get('daily_rmssd', np.nan) for d in daily_data]
    if any(not np.isnan(v) for v in hrv_values):
        ax1.plot(range(len(dates)), hrv_values, 'o-', color='#3498DB',
                 label='HRV (RMSSD)', linewidth=2, markersize=6)
    ax1.set_ylabel('RMSSD (ms)', color='#3498DB')
    ax1.tick_params(axis='y', labelcolor='#3498DB')

    # RHR (右軸)
    ax2 = ax1.twinx()
    rhr_values = [d.get('resting_heart_rate', np.nan) for d in daily_data]
    if any(not np.isnan(v) for v in rhr_values):
        ax2.plot(range(len(dates)), rhr_values, 's-', color='#E74C3C',
                 label='RHR', linewidth=2, markersize=6)
    ax2.set_ylabel('RHR (bpm)', color='#E74C3C')
    ax2.tick_params(axis='y', labelcolor='#E74C3C')

    ax1.set_xticks(range(len(dates)))
    ax1.set_xticklabels(date_labels, rotation=45)
    ax1.set_title('HRV vs Resting Heart Rate')
    ax1.grid(axis='y', alpha=0.3)

    # 凡例を統合
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def format_change(value, unit):
    """変化量をフォーマット"""
    if value is None or np.isnan(value):
        return "-"
    if value >= 0:
        return f"+{value:.1f}{unit}"
    return f"{value:.1f}{unit}"


def generate_report(output_dir, stats, daily_data, period_str):
    """
    マークダウンレポートを生成

    Args:
        output_dir: 出力ディレクトリ
        stats: メンタル統計
        daily_data: 日別データ
        period_str: 期間文字列
    """
    report_path = output_dir / 'REPORT.md'

    hrv_stats = stats.get('hrv_stats') or {}
    sleep_stats = stats.get('sleep_stats') or {}
    rhr_stats = stats.get('rhr_stats') or {}
    br_stats = stats.get('br_stats')
    spo2_stats = stats.get('spo2_stats')
    cardio_stats = stats.get('cardio_stats')
    temp_stats = stats.get('temp_stats')

    # トレンド表示
    hrv_trend_str = mind.format_trend(stats.get('hrv_trend', 'stable'))
    rhr_trend_str = mind.format_trend(stats.get('rhr_trend', 'stable'))

    # サマリーテーブル（主要指標の概要）
    summary_rows = []
    if hrv_stats:
        summary_rows.append(f"| HRV (RMSSD) | {hrv_stats.get('avg_rmssd', 0):.1f}ms | {format_change(hrv_stats.get('change_rmssd', 0), 'ms')} | {hrv_trend_str} |")
    if rhr_stats:
        summary_rows.append(f"| 安静時心拍数 | {rhr_stats.get('avg_rhr', 0):.1f}bpm | {format_change(rhr_stats.get('change_rhr', 0), 'bpm')} | {rhr_trend_str} |")
    if sleep_stats:
        summary_rows.append(f"| 睡眠時間 | {sleep_stats.get('avg_sleep_hours', 0):.1f}時間 | - | - |")
        summary_rows.append(f"| 睡眠効率 | {sleep_stats.get('avg_efficiency', 0):.0f}% | - | - |")

    summary_table = '\n'.join(summary_rows)

    # HRVセクション
    hrv_section = ""
    if hrv_stats:
        hrv_section = f"""
### HRV (心拍変動)

| 指標 | 値 |
|------|-----|
| 平均RMSSD | {hrv_stats.get('avg_rmssd', 0):.1f}ms |
| 変動幅 (SD) | {hrv_stats.get('std_rmssd', 0):.1f}ms |
| 範囲 | {hrv_stats.get('min_rmssd', 0):.1f} 〜 {hrv_stats.get('max_rmssd', 0):.1f}ms |
| 開始→終了 | {hrv_stats.get('first_rmssd', 0):.1f} → {hrv_stats.get('last_rmssd', 0):.1f}ms ({format_change(hrv_stats.get('change_rmssd', 0), 'ms')}) |
"""

    # RHRセクション
    rhr_section = ""
    if rhr_stats:
        rhr_section = f"""
### 安静時心拍数

| 指標 | 値 |
|------|-----|
| 平均RHR | {rhr_stats.get('avg_rhr', 0):.1f}bpm |
| 範囲 | {rhr_stats.get('min_rhr', 0):.0f} 〜 {rhr_stats.get('max_rhr', 0):.0f}bpm |
| 開始→終了 | {rhr_stats.get('first_rhr', 0):.0f} → {rhr_stats.get('last_rhr', 0):.0f}bpm ({format_change(rhr_stats.get('change_rhr', 0), 'bpm')}) |

> HRV上昇 & RHR低下 = 回復良好、HRV低下 & RHR上昇 = ストレス/疲労
"""

    # 睡眠セクション
    sleep_section = ""
    if sleep_stats:
        sleep_section = f"""
---

## 睡眠

| 指標 | 値 | 推奨 |
|------|-----|------|
| 平均睡眠時間 | {sleep_stats.get('avg_sleep_hours', 0):.1f}時間 | 7-9時間 |
| 平均効率 | {sleep_stats.get('avg_efficiency', 0):.0f}% | 85%以上 |
| 深い睡眠 | {sleep_stats.get('avg_deep_minutes', 0):.0f}分 ({sleep_stats.get('deep_pct', 0):.0f}%) | 13-23% |
| レム睡眠 | {sleep_stats.get('avg_rem_minutes', 0):.0f}分 ({sleep_stats.get('rem_pct', 0):.0f}%) | 20-25% |
"""

    # 生理的指標セクション
    physio_section = ""
    physio_items = []

    if br_stats:
        physio_items.append(f"""
### 呼吸数

| 指標 | 値 | 正常範囲 |
|------|-----|----------|
| 平均 | {br_stats['avg_breathing_rate']:.1f}回/分 | 12-20回/分 |
| 範囲 | {br_stats['min_breathing_rate']:.1f} 〜 {br_stats['max_breathing_rate']:.1f}回/分 | - |
""")

    if spo2_stats:
        physio_items.append(f"""
### 血中酸素濃度 (SpO2)

| 指標 | 値 | 正常範囲 |
|------|-----|----------|
| 平均 | {spo2_stats['avg_spo2']:.1f}% | 95-100% |
| 範囲 | {spo2_stats['min_spo2']:.1f} 〜 {spo2_stats['max_spo2']:.1f}% | - |
""")

    if cardio_stats:
        physio_items.append(f"""
### 心肺スコア (VO2 Max)

| 指標 | 値 |
|------|-----|
| 最新 | {cardio_stats['last_vo2_max']:.1f} ml/kg/min |
| 平均 | {cardio_stats['avg_vo2_max']:.1f} ml/kg/min |
| 範囲 | {cardio_stats['min_vo2_max']:.1f} 〜 {cardio_stats['max_vo2_max']:.1f} ml/kg/min |
""")

    if temp_stats:
        physio_items.append(f"""
### 皮膚温変動（睡眠中）

| 指標 | 値 |
|------|-----|
| 平均変動 | {temp_stats['avg_temp_variation']:.2f}°C |
| 範囲 | {temp_stats['min_temp_variation']:.2f} 〜 {temp_stats['max_temp_variation']:.2f}°C |
| 変動幅 (SD) | {temp_stats['std_temp_variation']:.2f}°C |

> 基礎体温からの差分。一貫性が高い（変動幅が小さい）ほど安定した睡眠状態
""")

    if physio_items:
        physio_section = f"""
---

## 生理的指標
{''.join(physio_items)}"""

    # 日別データテーブル
    daily_rows = []
    for d in daily_data:
        date_str = pd.to_datetime(d['date']).strftime('%m-%d')
        hrv_val = f"{d.get('daily_rmssd', 0):.1f}" if d.get('daily_rmssd') else "-"
        rhr_val = f"{d.get('resting_heart_rate', 0):.0f}" if d.get('resting_heart_rate') else "-"
        sleep_val = f"{d.get('sleep_hours', 0):.1f}h" if d.get('sleep_hours') else "-"
        eff_val = f"{d.get('sleep_efficiency', 0):.0f}%" if d.get('sleep_efficiency') else "-"
        daily_rows.append(f"| {date_str} | {hrv_val} | {rhr_val} | {sleep_val} | {eff_val} |")

    daily_table = '\n'.join(daily_rows)

    report = f"""# メンタルコンディションレポート

**期間**: {period_str}（{stats['days']}日間）

---

## サマリー

| 指標 | 平均 | 変化 | トレンド |
|------|------|------|----------|
{summary_table}

---

## 自律神経バランス

> HRVは副交感神経活動の指標。高いほどリラックス・回復状態。
{hrv_section}{rhr_section}{sleep_section}{physio_section}

---

## 日別データ

| 日付 | HRV (ms) | RHR (bpm) | 睡眠 | 効率 |
|------|----------|-----------|------|------|
{daily_table}

---

## 推移グラフ

### HRV vs 心拍数

![HRV-RHR](img/hrv_rhr.png)

### HRV推移

![HRV](img/hrv.png)
"""

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f'Report: {report_path}')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Mental Condition Report')
    parser.add_argument('--output', type=Path, default=BASE_DIR / 'tmp/mind_report')
    parser.add_argument('--days', type=int, default=7)
    args = parser.parse_args()

    print('='*60)
    print('メンタルコンディションレポート生成')
    print('='*60)
    print()

    # データ読み込み
    data = load_data(args.days)
    if not data or 'hrv' not in data:
        print("エラー: HRVデータが必要です")
        return 1

    print(f'HRVデータ: {len(data["hrv"])}日分')
    if 'heart_rate' in data:
        print(f'心拍数データ: {len(data["heart_rate"])}日分')
    if 'sleep' in data:
        print(f'睡眠データ: {len(data["sleep"])}日分')
    if 'breathing_rate' in data:
        print(f'呼吸数データ: {len(data["breathing_rate"])}日分')
    if 'spo2' in data:
        print(f'SpO2データ: {len(data["spo2"])}日分')
    if 'cardio_score' in data:
        print(f'心肺スコアデータ: {len(data["cardio_score"])}日分')
    if 'temperature_skin' in data:
        print(f'皮膚温データ: {len(data["temperature_skin"])}日分')

    # 出力ディレクトリ
    output_dir = args.output
    img_dir = output_dir / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

    # 統計計算
    print()
    print('統計計算中...')
    stats = mind.calc_mind_stats_for_period(
        df_hrv=data.get('hrv'),
        df_rhr=data.get('heart_rate'),
        df_sleep=data.get('sleep'),
        df_br=data.get('breathing_rate'),
        df_spo2=data.get('spo2'),
        df_cardio=data.get('cardio_score'),
        df_temp=data.get('temperature_skin'),
    )

    hrv_stats = stats.get('hrv_stats') or {}
    rhr_stats = stats.get('rhr_stats') or {}
    print(f'  HRV平均: {hrv_stats.get("avg_rmssd", 0):.1f}ms')
    print(f'  RHR平均: {rhr_stats.get("avg_rhr", 0):.1f}bpm')

    # 日別データ構築
    daily_data = mind.build_daily_data(
        df_hrv=data.get('hrv'),
        df_rhr=data.get('heart_rate'),
        df_sleep=data.get('sleep'),
        df_br=data.get('breathing_rate'),
        df_spo2=data.get('spo2'),
    )

    # 期間文字列
    dates = data['hrv'].index
    start = dates.min().strftime('%Y-%m-%d')
    end = dates.max().strftime('%Y-%m-%d')
    period_str = f'{start} 〜 {end}'

    # グラフ生成
    print()
    print('グラフ生成中...')
    plot_hrv_chart(daily_data, img_dir / 'hrv.png')
    plot_hrv_rhr_chart(daily_data, img_dir / 'hrv_rhr.png')

    # レポート生成
    print()
    print('レポート生成中...')
    generate_report(output_dir, stats, daily_data, period_str)

    print()
    print('='*60)
    print('レポート生成完了!')
    print('='*60)
    print(f'レポート: {output_dir / "REPORT.md"}')
    print(f'画像: {img_dir}/')

    return 0


if __name__ == '__main__':
    exit(main())
