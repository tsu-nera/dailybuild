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
ACTIVITY_CSV = BASE_DIR / 'data/fitbit/activity.csv'
ACTIVE_ZONE_MINUTES_CSV = BASE_DIR / 'data/fitbit/active_zone_minutes.csv'
ACTIVITY_LOGS_CSV = BASE_DIR / 'data/fitbit/activity_logs.csv'


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

    # アクティビティ
    if ACTIVITY_CSV.exists():
        df = pd.read_csv(ACTIVITY_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['activity'] = df

    # アクティブゾーン分
    if ACTIVE_ZONE_MINUTES_CSV.exists():
        df = pd.read_csv(ACTIVE_ZONE_MINUTES_CSV, parse_dates=['date'], index_col='date')
        if days:
            df = df.tail(days)
        data['active_zone_minutes'] = df

    # アクティビティログ
    if ACTIVITY_LOGS_CSV.exists():
        df = pd.read_csv(ACTIVITY_LOGS_CSV)
        df['startTime'] = pd.to_datetime(df['startTime'], format='ISO8601')
        if days:
            df = df.tail(days)
        data['activity_logs'] = df

    return data


def plot_hrv_chart(responsiveness_data, save_path):
    """
    HRV推移グラフを生成

    Args:
        responsiveness_data: 反応性の日別データリスト
        save_path: 保存パス
    """
    if not responsiveness_data:
        return

    dates = [d['date'] for d in responsiveness_data]
    date_labels = [pd.to_datetime(d).strftime('%m-%d') for d in dates]

    fig, ax = plt.subplots(figsize=(10, 5))

    # HRV
    hrv_values = [d.get('hrv_daily') if d.get('hrv_daily') is not None else np.nan for d in responsiveness_data]
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


def plot_hrv_rhr_chart(responsiveness_data, save_path):
    """
    HRV vs 心拍数の二軸グラフを生成

    Args:
        responsiveness_data: 反応性の日別データリスト
        save_path: 保存パス
    """
    if not responsiveness_data:
        return

    dates = [d['date'] for d in responsiveness_data]
    date_labels = [pd.to_datetime(d).strftime('%m-%d') for d in dates]

    fig, ax1 = plt.subplots(figsize=(10, 5))

    # HRV (左軸)
    hrv_values = [d.get('hrv_daily') if d.get('hrv_daily') is not None else np.nan for d in responsiveness_data]
    if any(not np.isnan(v) for v in hrv_values):
        ax1.plot(range(len(dates)), hrv_values, 'o-', color='#3498DB',
                 label='HRV (RMSSD)', linewidth=2, markersize=6)
    ax1.set_ylabel('RMSSD (ms)', color='#3498DB')
    ax1.tick_params(axis='y', labelcolor='#3498DB')

    # RHR (右軸)
    ax2 = ax1.twinx()
    rhr_values = [d.get('rhr') if d.get('rhr') is not None else np.nan for d in responsiveness_data]
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


def prepare_mind_report_data(responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, days):
    """
    3軸メンタルレポート用のコンテキストデータを準備

    Parameters
    ----------
    responsiveness_daily : list
        反応性の日別データリスト
    exertion_balance_daily : list
        運動バランスの日別データリスト
    sleep_patterns_daily : list
        睡眠パターンの日別データリスト
    period_str : str
        期間文字列
    days : int
        日数

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    context = {
        'report_title': '🧠 メンタルレポート',
        'period': {
            'period_str': period_str,
            'days': days
        },

        # 反応性の日別データ（そのまま渡す）
        'responsiveness_data': responsiveness_daily,

        # 運動バランスの日別データ（そのまま渡す）
        'exertion_balance_data': exertion_balance_daily,

        # 睡眠パターンの日別データ（そのまま渡す）
        'sleep_patterns_data': sleep_patterns_daily,

        # チャート
        'charts': {
            'hrv_rhr': 'img/hrv_rhr.png',
            'hrv': 'img/hrv.png',
        }
    }

    return context


def generate_report(output_dir, responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, days):
    """
    マークダウンレポートを生成（Jinja2テンプレート版）

    Args:
        output_dir: 出力ディレクトリ
        responsiveness_daily: 反応性の日別データリスト
        exertion_balance_daily: 運動バランスの日別データリスト
        sleep_patterns_daily: 睡眠パターンの日別データリスト
        period_str: 期間文字列
        days: 日数
    """
    from lib.templates.renderer import MindReportRenderer

    # コンテキストデータ準備
    context = prepare_mind_report_data(responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, days)

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
    for key in ['heart_rate', 'breathing_rate', 'spo2', 'cardio_score', 'temperature_skin', 'activity', 'active_zone_minutes']:
        if key in data:
            data[key] = filter_dataframe_by_period(
                data[key], 'date', week, month, year, args.days, is_index=True
            )

    # 睡眠データ（dateOfSleep列を使用、indexではない）
    if 'sleep' in data:
        data['sleep'] = filter_dataframe_by_period(
            data['sleep'], 'dateOfSleep', week, month, year, args.days, is_index=False
        )

    # アクティビティログ（startTime列）
    if 'activity_logs' in data:
        data['activity_logs'] = filter_dataframe_by_period(
            data['activity_logs'], 'startTime', week, month, year, args.days, is_index=False
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

    # 期間の取得
    dates = data['hrv'].index
    start_date = dates.min()
    end_date = dates.max()

    # 3軸それぞれの日別データを準備
    print()
    print('日別データ準備中...')
    responsiveness_daily = mind.prepare_responsiveness_daily_data(
        start_date=start_date,
        end_date=end_date,
        df_hrv=data.get('hrv'),
        df_heart_rate=data.get('heart_rate'),
        df_breathing=data.get('breathing_rate'),
        df_temp=data.get('temperature_skin'),
        df_spo2=data.get('spo2')
    )

    exertion_balance_daily = mind.prepare_exertion_balance_daily_data(
        start_date=start_date,
        end_date=end_date,
        df_activity=data.get('activity'),
        df_azm=data.get('active_zone_minutes')
    )

    sleep_patterns_daily = mind.prepare_sleep_patterns_daily_data(
        start_date=start_date,
        end_date=end_date,
        df_sleep=data.get('sleep')
    )

    print(f'  反応性データ: {len(responsiveness_daily)}日分')
    print(f'  運動バランスデータ: {len(exertion_balance_daily)}日分')
    print(f'  睡眠パターンデータ: {len(sleep_patterns_daily)}日分')

    # 期間文字列
    period_str = f'{start_date.strftime("%Y-%m-%d")} 〜 {end_date.strftime("%Y-%m-%d")}'

    # グラフ生成
    print()
    print('グラフ生成中...')
    plot_hrv_chart(responsiveness_daily, img_dir / 'hrv.png')
    plot_hrv_rhr_chart(responsiveness_daily, img_dir / 'hrv_rhr.png')

    # レポート生成
    print()
    print('レポート生成中...')
    generate_report(output_dir, responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, len(responsiveness_daily))

    print()
    print('='*60)
    print('レポート生成完了!')
    print('='*60)
    print(f'レポート: {output_dir / "REPORT.md"}')
    print(f'画像: {img_dir}/')

    return 0


if __name__ == '__main__':
    exit(main())
