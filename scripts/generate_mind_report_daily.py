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
from lib.utils.report_args import add_common_report_args, parse_period_args, determine_output_dir

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


def prepare_mind_report_data(stats, daily_data, period_str):
    """
    メンタルレポート用のコンテキストデータを準備

    Parameters
    ----------
    stats : dict
        メンタル統計
    daily_data : list
        日別データ
    period_str : str
        期間文字列

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    from lib.templates.filters import format_change

    hrv_stats = stats.get('hrv_stats') or {}
    sleep_stats = stats.get('sleep_stats') or {}
    rhr_stats = stats.get('rhr_stats') or {}
    br_stats = stats.get('br_stats')
    spo2_stats = stats.get('spo2_stats')
    cardio_stats = stats.get('cardio_stats')
    temp_stats = stats.get('temp_stats')

    # サマリーメトリクス構築
    summary_metrics = []
    if hrv_stats:
        summary_metrics.append({
            'label': 'HRV (RMSSD)',
            'average': f"{hrv_stats.get('avg_rmssd', 0):.1f}ms",
            'change': format_change(hrv_stats.get('change_rmssd', 0), 'ms'),
            'trend': mind.format_trend(stats.get('hrv_trend', 'stable'))
        })
    if rhr_stats:
        summary_metrics.append({
            'label': '安静時心拍数',
            'average': f"{rhr_stats.get('avg_rhr', 0):.1f}bpm",
            'change': format_change(rhr_stats.get('change_rhr', 0), 'bpm', positive_is_good=False),
            'trend': mind.format_trend(stats.get('rhr_trend', 'stable'))
        })
    if sleep_stats:
        summary_metrics.append({
            'label': '睡眠時間',
            'average': f"{sleep_stats.get('avg_sleep_hours', 0):.1f}時間",
            'change': '-',
            'trend': '-'
        })
        summary_metrics.append({
            'label': '睡眠効率',
            'average': f"{sleep_stats.get('avg_efficiency', 0):.0f}%",
            'change': '-',
            'trend': '-'
        })

    # 自律神経セクション
    autonomic = {}
    if hrv_stats:
        autonomic['hrv_stats'] = {
            'avg_rmssd': f"{hrv_stats.get('avg_rmssd', 0):.1f}",
            'std_rmssd': f"{hrv_stats.get('std_rmssd', 0):.1f}",
            'min_rmssd': f"{hrv_stats.get('min_rmssd', 0):.1f}",
            'max_rmssd': f"{hrv_stats.get('max_rmssd', 0):.1f}",
            'first_rmssd': f"{hrv_stats.get('first_rmssd', 0):.1f}",
            'last_rmssd': f"{hrv_stats.get('last_rmssd', 0):.1f}",
            'change_rmssd': format_change(hrv_stats.get('change_rmssd', 0), 'ms')
        }
    if rhr_stats:
        autonomic['rhr_stats'] = {
            'avg_rhr': f"{rhr_stats.get('avg_rhr', 0):.1f}",
            'min_rhr': f"{rhr_stats.get('min_rhr', 0):.0f}",
            'max_rhr': f"{rhr_stats.get('max_rhr', 0):.0f}",
            'first_rhr': f"{rhr_stats.get('first_rhr', 0):.0f}",
            'last_rhr': f"{rhr_stats.get('last_rhr', 0):.0f}",
            'change_rhr': format_change(rhr_stats.get('change_rhr', 0), 'bpm', positive_is_good=False)
        }

    # 睡眠セクション
    sleep_section_data = None
    if sleep_stats:
        sleep_section_data = {
            'avg_sleep_hours': f"{sleep_stats.get('avg_sleep_hours', 0):.1f}",
            'avg_efficiency': f"{sleep_stats.get('avg_efficiency', 0):.0f}",
            'avg_deep_minutes': f"{sleep_stats.get('avg_deep_minutes', 0):.0f}",
            'deep_pct': f"{sleep_stats.get('deep_pct', 0):.0f}",
            'avg_rem_minutes': f"{sleep_stats.get('avg_rem_minutes', 0):.0f}",
            'rem_pct': f"{sleep_stats.get('rem_pct', 0):.0f}"
        }

    # 生理的指標セクション
    physiology = {}
    if br_stats:
        physiology['br_stats'] = {
            'avg_breathing_rate': f"{br_stats['avg_breathing_rate']:.1f}",
            'min_breathing_rate': f"{br_stats['min_breathing_rate']:.1f}",
            'max_breathing_rate': f"{br_stats['max_breathing_rate']:.1f}"
        }
    if spo2_stats:
        physiology['spo2_stats'] = {
            'avg_spo2': f"{spo2_stats['avg_spo2']:.1f}",
            'min_spo2': f"{spo2_stats['min_spo2']:.1f}",
            'max_spo2': f"{spo2_stats['max_spo2']:.1f}"
        }
    if cardio_stats:
        physiology['cardio_stats'] = {
            'last_vo2_max': f"{cardio_stats['last_vo2_max']:.1f}",
            'avg_vo2_max': f"{cardio_stats['avg_vo2_max']:.1f}",
            'min_vo2_max': f"{cardio_stats['min_vo2_max']:.1f}",
            'max_vo2_max': f"{cardio_stats['max_vo2_max']:.1f}"
        }
    if temp_stats:
        physiology['temp_stats'] = {
            'avg_temp_variation': f"{temp_stats['avg_temp_variation']:.2f}",
            'min_temp_variation': f"{temp_stats['min_temp_variation']:.2f}",
            'max_temp_variation': f"{temp_stats['max_temp_variation']:.2f}",
            'std_temp_variation': f"{temp_stats['std_temp_variation']:.2f}"
        }

    # 日別データ
    daily_data_formatted = []
    for d in daily_data:
        date_str = pd.to_datetime(d['date']).strftime('%m-%d')
        hrv_val = f"{d.get('daily_rmssd', 0):.1f}" if d.get('daily_rmssd') else "-"
        rhr_val = f"{d.get('resting_heart_rate', 0):.0f}" if d.get('resting_heart_rate') else "-"
        sleep_val = f"{d.get('sleep_hours', 0):.1f}h" if d.get('sleep_hours') else "-"
        eff_val = f"{d.get('sleep_efficiency', 0):.0f}%" if d.get('sleep_efficiency') else "-"

        daily_data_formatted.append({
            'date': date_str,
            'hrv': hrv_val,
            'rhr': rhr_val,
            'sleep_hours': sleep_val,
            'efficiency': eff_val
        })

    context = {
        'report_title': 'メンタルコンディションレポート',
        'period': {
            'period_str': period_str,
            'days': stats['days']
        },
        'summary_metrics': summary_metrics,
        'autonomic': autonomic,
        'sleep_stats': sleep_section_data,
        'physiology': physiology if physiology else None,
        'daily_data': daily_data_formatted,
        'charts': {
            'hrv_rhr': 'img/hrv_rhr.png',
            'hrv': 'img/hrv.png'
        }
    }

    return context


def generate_report(output_dir, stats, daily_data, period_str):
    """
    マークダウンレポートを生成（Jinja2テンプレート版）

    Args:
        output_dir: 出力ディレクトリ
        stats: メンタル統計
        daily_data: 日別データ
        period_str: 期間文字列
    """
    from lib.templates.renderer import MindReportRenderer

    # コンテキストデータ準備
    context = prepare_mind_report_data(stats, daily_data, period_str)

    # テンプレートレンダリング
    renderer = MindReportRenderer()
    report_content = renderer.render_daily_report(context)

    # レポート出力
    report_path = output_dir / 'REPORT.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f'Report: {report_path}')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Mental Condition Report')
    add_common_report_args(parser, default_output=BASE_DIR / 'tmp/mind_report', default_days=7)
    args = parser.parse_args()

    # Parse period arguments
    week, month, year = parse_period_args(args)

    # 出力ディレクトリの決定
    output_dir = determine_output_dir(BASE_DIR, 'mind', args.output, week, month, year)

    print('='*60)
    print('メンタルコンディションレポート生成')
    print('='*60)
    print()

    # データ読み込み（全データ）
    data = load_data(days=None)
    if not data or 'hrv' not in data:
        print("エラー: HRVデータが必要です")
        return 1

    # 共通フィルタリング関数を使用
    from lib.utils.report_args import filter_dataframe_by_period

    # HRV（必須）
    data['hrv'] = filter_dataframe_by_period(
        data['hrv'], 'date', week, month, year, args.days, is_index=True
    )

    # その他のデータ（indexが日付）
    for key in ['heart_rate', 'breathing_rate', 'spo2', 'cardio_score', 'temperature_skin']:
        if key in data:
            data[key] = filter_dataframe_by_period(
                data[key], 'date', week, month, year, args.days, is_index=True
            )

    # 睡眠データ（dateOfSleep列を使用、indexではない）
    if 'sleep' in data:
        data['sleep'] = filter_dataframe_by_period(
            data['sleep'], 'dateOfSleep', week, month, year, args.days, is_index=False
        )

    # フィルタリング結果を表示
    if week is not None:
        print(f'{year}年 第{week}週に絞り込み')
    elif month is not None:
        print(f'{year}年 {month}月に絞り込み')
    elif args.days is not None:
        print(f'直近{args.days}日分に絞り込み')

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

    # 出力ディレクトリ（既に設定済み）
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
