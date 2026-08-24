#!/usr/bin/env python
# coding: utf-8
"""
週次隔（Interval）メンタルレポート生成スクリプト
7日間ごとの平均値を算出し、前週比の変化を可視化する。

Usage:
    python generate_mind_report_interval.py [--weeks <N>]
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))
from lib.utils.private_data import ensure_dir

# データファイルパス
BASE_DIR = project_root
HRV_CSV = BASE_DIR / 'data/fitbit/hrv.csv'
HEART_RATE_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'
BREATHING_RATE_CSV = BASE_DIR / 'data/fitbit/breathing_rate.csv'
SPO2_CSV = BASE_DIR / 'data/fitbit/spo2.csv'


def prepare_interval_report_data(weekly):
    """
    週次隔レポート用のコンテキストデータを準備

    Parameters
    ----------
    weekly : DataFrame
        週次集計データ（index: (iso_year, iso_week)）

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    from lib.templates.filters import format_change

    # 週次データを降順でソート（最新が上）
    weekly_desc = weekly.sort_index(ascending=False)

    # 週次データリストを構築
    weekly_data = []
    for (year, week), row in weekly_desc.iterrows():
        # 週ラベル
        week_label = f"{year}-W{week:02d}"

        weekly_data.append({
            'week_label': week_label,
            # 自律神経系
            'hrv': f"{row['hrv']:.1f}ms" if pd.notna(row['hrv']) else '-',
            'hrv_diff': format_change(row['hrv_diff'], 'ms') if pd.notna(row.get('hrv_diff')) else '-',
            'rhr': f"{row['rhr']:.1f}bpm" if pd.notna(row['rhr']) else '-',
            'rhr_diff': format_change(row['rhr_diff'], 'bpm', positive_is_good=False) if pd.notna(row.get('rhr_diff')) else '-',
            'breathing': f"{row['breathing']:.1f}/min" if pd.notna(row['breathing']) else '-',
            'breathing_diff': format_change(row['breathing_diff'], '/min', positive_is_good=False) if pd.notna(row.get('breathing_diff')) else '-',
            'spo2': f"{row['spo2']:.1f}%" if pd.notna(row['spo2']) else '-',
            'spo2_diff': format_change(row['spo2_diff'], '%') if pd.notna(row.get('spo2_diff')) else '-',
        })

    context = {
        'report_title': '🧠 メンタル週次レポート',
        'description': '7日間平均値の推移。前週比でトレンドを確認。',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'weekly_data': weekly_data,
        'hrv_rhr_trend_image': 'img/hrv_rhr_trend.png',
    }

    return context


def main():
    import argparse

    parser = argparse.ArgumentParser(description='メンタル週次隔レポート生成')
    parser.add_argument('--weeks', type=int, default=8, help='表示する週数')
    parser.add_argument('--output', type=Path, default=BASE_DIR / 'reports/mind/interval/REPORT.md')
    args = parser.parse_args()

    print('='*60)
    print('メンタル週次隔レポート生成')
    print('='*60)
    print()

    # データ読み込み
    data = {}

    # HRV
    if HRV_CSV.exists():
        df = pd.read_csv(HRV_CSV, index_col=0, parse_dates=True)
        data['hrv'] = df

    # 心拍数
    if HEART_RATE_CSV.exists():
        df = pd.read_csv(HEART_RATE_CSV, index_col=0, parse_dates=True)
        data['heart_rate'] = df

    # 呼吸数
    if BREATHING_RATE_CSV.exists():
        df = pd.read_csv(BREATHING_RATE_CSV, index_col=0, parse_dates=True)
        data['breathing_rate'] = df

    # SpO2
    if SPO2_CSV.exists():
        df = pd.read_csv(SPO2_CSV, index_col=0, parse_dates=True)
        data['spo2'] = df

    # データ件数表示
    print('データ読み込み完了:')
    for key, df in data.items():
        print(f'  {key}: {len(df)}件')
    print()

    # ISO週番号を追加
    for key, df in data.items():
        df['iso_year'] = df.index.isocalendar().year
        df['iso_week'] = df.index.isocalendar().week

    # 週ごとの集計
    weekly_list = []

    # 全週を取得（いずれかのデータソースから）
    all_weeks = set()
    for df in data.values():
        if len(df) > 0:
            weeks = df.groupby(['iso_year', 'iso_week']).size().index
            all_weeks.update(weeks)

    all_weeks = sorted(all_weeks)

    for (year, week) in all_weeks:
        week_data = {
            'iso_year': year,
            'iso_week': week,
        }

        # HRV
        if 'hrv' in data and len(data['hrv']) > 0:
            group = data['hrv'][(data['hrv']['iso_year'] == year) & (data['hrv']['iso_week'] == week)]
            if len(group) > 0:
                week_data['hrv'] = group['daily_rmssd'].mean()
            else:
                week_data['hrv'] = np.nan
        else:
            week_data['hrv'] = np.nan

        # RHR
        if 'heart_rate' in data and len(data['heart_rate']) > 0:
            group = data['heart_rate'][(data['heart_rate']['iso_year'] == year) & (data['heart_rate']['iso_week'] == week)]
            if len(group) > 0:
                week_data['rhr'] = group['resting_heart_rate'].mean()
            else:
                week_data['rhr'] = np.nan
        else:
            week_data['rhr'] = np.nan

        # 呼吸数
        if 'breathing_rate' in data and len(data['breathing_rate']) > 0:
            group = data['breathing_rate'][(data['breathing_rate']['iso_year'] == year) & (data['breathing_rate']['iso_week'] == week)]
            if len(group) > 0:
                week_data['breathing'] = group['breathing_rate'].mean()
            else:
                week_data['breathing'] = np.nan
        else:
            week_data['breathing'] = np.nan

        # SpO2
        if 'spo2' in data and len(data['spo2']) > 0:
            group = data['spo2'][(data['spo2']['iso_year'] == year) & (data['spo2']['iso_week'] == week)]
            if len(group) > 0:
                week_data['spo2'] = group['avg_spo2'].mean()
            else:
                week_data['spo2'] = np.nan
        else:
            week_data['spo2'] = np.nan

        weekly_list.append(week_data)

    weekly = pd.DataFrame(weekly_list)
    weekly = weekly.set_index(['iso_year', 'iso_week']).sort_index()

    # 指標ごとの前週差分（Delta）を計算
    weekly['hrv_diff'] = weekly['hrv'].diff()
    weekly['rhr_diff'] = weekly['rhr'].diff()
    weekly['breathing_diff'] = weekly['breathing'].diff()
    weekly['spo2_diff'] = weekly['spo2'].diff()

    # 直近N週間に絞る
    weekly = weekly.tail(args.weeks)

    # トレンドグラフ生成
    img_dir = args.output.parent / 'img'
    ensure_dir(img_dir)

    print('プロット中: HRV/RHRトレンド...')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    # 週ラベル作成
    week_labels = [f"{year}-W{week:02d}" for year, week in weekly.index]

    # 1. HRV
    if weekly['hrv'].notna().any():
        ax1.plot(week_labels, weekly['hrv'], 'o-', color='#3498DB', linewidth=2, markersize=5)
    ax1.set_ylabel('HRV (ms)', fontsize=11)
    ax1.set_title('Heart Rate Variability (Weekly Average)', fontsize=12, fontweight='bold')
    ax1.grid(axis='y', alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)

    # 2. RHR
    if weekly['rhr'].notna().any():
        ax2.plot(week_labels, weekly['rhr'], 's-', color='#E74C3C', linewidth=2, markersize=5)
    ax2.set_ylabel('RHR (bpm)', fontsize=11)
    ax2.set_title('Resting Heart Rate (Weekly Average)', fontsize=12, fontweight='bold')
    ax2.grid(axis='y', alpha=0.3)
    ax2.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.savefig(img_dir / 'hrv_rhr_trend.png', dpi=150, bbox_inches='tight')
    plt.close()

    # コンテキストデータ準備
    context = prepare_interval_report_data(weekly=weekly)

    # テンプレートレンダリング
    from lib.templates.renderer import MindReportRenderer
    renderer = MindReportRenderer()
    report_content = renderer.render_interval_report(context)

    # レポート出力
    output_path = args.output
    ensure_dir(output_path.parent)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print()
    print('='*60)
    print('レポート生成完了!')
    print('='*60)
    print(f'レポート: {output_path}')
    print(f'画像: {img_dir}/')

    return 0


if __name__ == "__main__":
    sys.exit(main())
