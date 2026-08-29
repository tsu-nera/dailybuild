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
from lib.analytics import hr_zones
from lib.utils.report_args import add_common_report_args, parse_period_args, determine_output_dir
from lib.utils.data_loader import load_csv_with_baseline_window, determine_target_period
from lib.utils.private_data import ensure_dir

BASE_DIR = project_root
HRV_CSV = BASE_DIR / 'data/fitbit/hrv.csv'
HEART_RATE_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'
HEART_RATE_INTRADAY_CSV = BASE_DIR / 'data/fitbit/heart_rate_intraday.csv'
SLEEP_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
SLEEP_LEVELS_CSV = BASE_DIR / 'data/fitbit/sleep_levels.csv'
BREATHING_RATE_CSV = BASE_DIR / 'data/fitbit/breathing_rate.csv'
SPO2_CSV = BASE_DIR / 'data/fitbit/spo2.csv'
CARDIO_SCORE_CSV = BASE_DIR / 'data/fitbit/cardio_score.csv'
TEMPERATURE_SKIN_CSV = BASE_DIR / 'data/fitbit/temperature_skin.csv'
ACTIVITY_CSV = BASE_DIR / 'data/fitbit/activity.csv'
BLOOD_PRESSURE_CSV = BASE_DIR / 'data/healthplanet_bp.csv'
CORE_TEMPERATURE_CSV = BASE_DIR / 'data/fitbit/temperature_core.csv'
ACTIVITY_LOGS_CSV = BASE_DIR / 'data/fitbit/activity_logs.csv'




def load_core_temperature(csv_path, target_start, target_end):
    """深部体温（Fitbitへの手動記録）を日次に丸めて読み込む

    Fitbitは時刻付きで1日に複数回記録できるため、その日の最初の測定
    （起床直後の想定）を採用する。
    """
    if not csv_path.exists():
        return pd.DataFrame()

    df = pd.read_csv(csv_path, parse_dates=['date_time'])
    if df.empty:
        return pd.DataFrame()

    df = df.sort_values('date_time')
    df['date'] = df['date_time'].dt.normalize()
    df = df[(df['date'] >= target_start) & (df['date'] <= target_end)]
    if df.empty:
        return pd.DataFrame()

    first = df.groupby('date').first()
    return pd.DataFrame({
        'core_temperature': first['temperature'],
        'core_temperature_time': first['date_time'].dt.strftime('%H:%M'),
    })


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


TEMP_DEV_THRESHOLD = 0.5
RHR_DEV_THRESHOLD = 3.0
SUSTAINED_DAYS = 2


def detect_sustained_illness_signal(responsiveness_data):
    """
    急性体調変化の持続シグナルを検知

    皮膚温がベースライン+0.5℃以上、かつ安静時心拍数がベースライン+3bpm以上の
    日が2日連続した場合にアラートを発火する。単日の逸脱では発火しない。

    閾値は過去627日分のデータで検証済み（発火 2.9回/年）。

    Args:
        responsiveness_data: 反応性の日別データリスト

    Returns:
        list[dict]: 発火日の情報（date, temp_dev, rhr_dev）
    """
    alerts = []
    streak = 0

    for day in responsiveness_data:
        temp_variation = day.get('temp_variation')
        temp_baseline = day.get('temp_variation_baseline')
        rhr = day.get('rhr')
        rhr_baseline = day.get('rhr_baseline')

        if (
            temp_variation is None
            or temp_baseline is None
            or rhr is None
            or rhr_baseline is None
        ):
            streak = 0
            continue

        condition_met = (
            temp_variation >= temp_baseline + TEMP_DEV_THRESHOLD
            and rhr >= rhr_baseline + RHR_DEV_THRESHOLD
        )

        if condition_met:
            streak += 1
        else:
            streak = 0

        if streak >= SUSTAINED_DAYS:
            alerts.append({
                'date': day['date'],
                'temp_dev': temp_variation - temp_baseline,
                'rhr_dev': rhr - rhr_baseline,
            })

    return alerts


def plot_comprehensive_trend(responsiveness_data, sleep_patterns_data, save_path):
    """
    HRV・RHRの推移グラフ（ベースライン付き）を生成

    Args:
        responsiveness_data: 反応性の日別データリスト
        sleep_patterns_data: 睡眠パターンの日別データリスト（未使用だが互換性のため残す）
        save_path: 保存パス
    """
    if not responsiveness_data:
        return

    dates = [d['date'] for d in responsiveness_data]
    date_labels = [pd.to_datetime(d).strftime('%m-%d') for d in dates]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    # 1. HRV + Baseline
    hrv_values = [d.get('hrv_daily') if d.get('hrv_daily') is not None else np.nan for d in responsiveness_data]
    hrv_baseline = [d.get('hrv_daily_baseline') if d.get('hrv_daily_baseline') is not None else np.nan for d in responsiveness_data]
    if any(not np.isnan(v) for v in hrv_values):
        ax1.plot(range(len(dates)), hrv_values, 'o-', color='#3498DB',
                 label='HRV', linewidth=2, markersize=5)
        if any(not np.isnan(v) for v in hrv_baseline):
            ax1.plot(range(len(dates)), hrv_baseline, '--', color='#95A5A6',
                     label='Baseline', linewidth=2, alpha=0.7)
    ax1.set_ylabel('HRV (ms)', fontsize=11)
    ax1.set_title('Heart Rate Variability (HRV)', fontsize=12, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(axis='y', alpha=0.3)

    # 2. RHR + Baseline
    rhr_values = [d.get('rhr') if d.get('rhr') is not None else np.nan for d in responsiveness_data]
    rhr_baseline = [d.get('rhr_baseline') if d.get('rhr_baseline') is not None else np.nan for d in responsiveness_data]
    if any(not np.isnan(v) for v in rhr_values):
        ax2.plot(range(len(dates)), rhr_values, 's-', color='#E74C3C',
                 label='RHR', linewidth=2, markersize=5)
        if any(not np.isnan(v) for v in rhr_baseline):
            ax2.plot(range(len(dates)), rhr_baseline, '--', color='#95A5A6',
                     label='Baseline', linewidth=2, alpha=0.7)
    ax2.set_ylabel('RHR (bpm)', fontsize=11)
    ax2.set_title('Resting Heart Rate (RHR)', fontsize=12, fontweight='bold')
    ax2.legend(loc='upper left', fontsize=10)
    ax2.grid(axis='y', alpha=0.3)
    ax2.set_xticks(range(len(dates)))
    ax2.set_xticklabels(date_labels, rotation=45)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()


def prepare_mind_report_data(responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, days, hr_zone_meta=None):
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
    hr_zone_meta : dict, optional
        心拍ゾーンメタ情報

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    illness_alerts = detect_sustained_illness_signal(responsiveness_daily)

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

        # 急性体調変化の持続シグナル
        'illness_alerts': illness_alerts,

        # 心拍ゾーンメタ情報
        'hr_zone_meta': hr_zone_meta,

        # チャート
        'charts': {
            'hrv_rhr': 'img/hrv_rhr.png',
            'hrv': 'img/hrv.png',
            'comprehensive_trend': 'img/comprehensive_trend.png',
        }
    }

    return context


def generate_report(output_dir, responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, days, hr_zone_meta=None, show_charts=True):
    """
    マークダウンレポートを生成（Jinja2テンプレート版）

    Args:
        output_dir: 出力ディレクトリ
        responsiveness_daily: 反応性の日別データリスト
        exertion_balance_daily: 運動バランスの日別データリスト
        sleep_patterns_daily: 睡眠パターンの日別データリスト
        period_str: 期間文字列
        days: 日数
        hr_zone_meta: 心拍ゾーンメタ情報
    """
    from lib.templates.renderer import MindReportRenderer

    # コンテキストデータ準備
    context = prepare_mind_report_data(responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, days, hr_zone_meta=hr_zone_meta)
    context['show_charts'] = show_charts

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
    add_common_report_args(parser, default_output=BASE_DIR / 'tmp/mind_report', default_days=14)
    args = parser.parse_args()

    # Parse period arguments
    week, month, year = parse_period_args(args)

    # 出力ディレクトリの決定
    output_dir = determine_output_dir(BASE_DIR, 'mind', args.output, week, month, year)

    print('='*60)
    print('メンタルコンディションレポート生成')
    print('='*60)
    print()

    # 1. 表示対象期間を確定
    try:
        target_start, target_end = determine_target_period(week, month, year, args.days)
    except ValueError as e:
        print(f"エラー: {e}")
        return 1

    print(f'表示期間: {target_start.strftime("%Y-%m-%d")} 〜 {target_end.strftime("%Y-%m-%d")}')
    print()

    # 2. ベースライン計算を考慮してデータ読み込み
    print('データ読み込み中...')
    data = {}

    # HRV（必須、60日ベースライン）
    if not HRV_CSV.exists():
        print(f"エラー: {HRV_CSV} が見つかりません")
        return 1
    data['hrv'] = load_csv_with_baseline_window(
        HRV_CSV, target_start, target_end,
        baseline_window=mind.BASELINE_WINDOWS['hrv_daily']
    )
    if data['hrv'].empty:
        print("エラー: HRVデータが見つかりません")
        return 1

    # 心拍数（30日ベースライン）
    if HEART_RATE_CSV.exists():
        data['heart_rate'] = load_csv_with_baseline_window(
            HEART_RATE_CSV, target_start, target_end,
            baseline_window=mind.BASELINE_WINDOWS['rhr']
        )

    # 呼吸数（30日ベースライン）
    if BREATHING_RATE_CSV.exists():
        data['breathing_rate'] = load_csv_with_baseline_window(
            BREATHING_RATE_CSV, target_start, target_end,
            baseline_window=mind.BASELINE_WINDOWS['breathing_rate']
        )

    # SpO2（30日ベースライン）
    if SPO2_CSV.exists():
        data['spo2'] = load_csv_with_baseline_window(
            SPO2_CSV, target_start, target_end,
            baseline_window=mind.BASELINE_WINDOWS['spo2_avg']
        )

    # 皮膚温（30日ベースライン）
    if TEMPERATURE_SKIN_CSV.exists():
        data['temperature_skin'] = load_csv_with_baseline_window(
            TEMPERATURE_SKIN_CSV, target_start, target_end,
            baseline_window=mind.BASELINE_WINDOWS['temp_variation']
        )

    # 深部体温（手動記録、ベースライン不要）
    data['core_temperature'] = load_core_temperature(
        CORE_TEMPERATURE_CSV, target_start, target_end
    )

    # 血圧（ベースライン不要、表示期間のみ）
    if BLOOD_PRESSURE_CSV.exists():
        data['blood_pressure'] = load_csv_with_baseline_window(
            BLOOD_PRESSURE_CSV, target_start, target_end,
            baseline_window=0
        )

    # アクティビティ（ベースライン不要、表示期間のみ）
    if ACTIVITY_CSV.exists():
        data['activity'] = load_csv_with_baseline_window(
            ACTIVITY_CSV, target_start, target_end,
            baseline_window=0
        )

    # 睡眠データ（dateOfSleep列、indexなし、ベースライン不要）
    if SLEEP_CSV.exists():
        data['sleep'] = load_csv_with_baseline_window(
            SLEEP_CSV, target_start, target_end,
            baseline_window=0,
            date_column='dateOfSleep',
            index_col=None
        )

    # 睡眠レベルデータ（dateOfSleep列、indexなし、ベースライン不要）
    if SLEEP_LEVELS_CSV.exists():
        data['sleep_levels'] = load_csv_with_baseline_window(
            SLEEP_LEVELS_CSV, target_start, target_end,
            baseline_window=0,
            date_column='dateOfSleep',
            index_col=None
        )

    # アクティビティログ（startTime列、indexなし、ベースライン不要）
    if ACTIVITY_LOGS_CSV.exists():
        data['activity_logs'] = load_csv_with_baseline_window(
            ACTIVITY_LOGS_CSV, target_start, target_end,
            baseline_window=0,
            date_column='startTime',
            index_col=None
        )

    # データ件数表示
    print(f'HRVデータ: {len(data["hrv"])}日分（ベースライン計算期間含む）')
    if 'heart_rate' in data:
        print(f'心拍数データ: {len(data["heart_rate"])}日分')
    if 'sleep' in data:
        print(f'睡眠データ: {len(data["sleep"])}日分')
    if 'sleep_levels' in data:
        print(f'睡眠レベルデータ: {len(data["sleep_levels"])}日分')
    if 'breathing_rate' in data:
        print(f'呼吸数データ: {len(data["breathing_rate"])}日分')
    if 'spo2' in data:
        print(f'SpO2データ: {len(data["spo2"])}日分')
    if 'temperature_skin' in data:
        print(f'皮膚温データ: {len(data["temperature_skin"])}日分')

    # 出力ディレクトリ（既に設定済み）
    ensure_dir(output_dir)
    img_dir = output_dir / 'img'
    if not args.no_charts:
        ensure_dir(img_dir)

    # 3. ベースライン計算
    print()
    print('ベースライン計算中...')

    # HRV（daily, deep両方）
    if 'hrv' in data and not data['hrv'].empty:
        data['hrv'] = mind.calculate_baseline_metrics(
            data['hrv'], 'daily_rmssd',
            baseline_window=mind.BASELINE_WINDOWS['hrv_daily']
        )
        data['hrv'] = mind.calculate_baseline_metrics(
            data['hrv'], 'deep_rmssd',
            baseline_window=mind.BASELINE_WINDOWS['hrv_deep']
        )

    # 安静時心拍数
    if 'heart_rate' in data and not data['heart_rate'].empty:
        data['heart_rate'] = mind.calculate_baseline_metrics(
            data['heart_rate'], 'resting_heart_rate',
            baseline_window=mind.BASELINE_WINDOWS['rhr']
        )

    # 呼吸数
    if 'breathing_rate' in data and not data['breathing_rate'].empty:
        data['breathing_rate'] = mind.calculate_baseline_metrics(
            data['breathing_rate'], 'breathing_rate',
            baseline_window=mind.BASELINE_WINDOWS['breathing_rate']
        )

    # SpO2
    if 'spo2' in data and not data['spo2'].empty:
        data['spo2'] = mind.calculate_baseline_metrics(
            data['spo2'], 'avg_spo2',
            baseline_window=mind.BASELINE_WINDOWS['spo2_avg']
        )

    # 皮膚温
    if 'temperature_skin' in data and not data['temperature_skin'].empty:
        data['temperature_skin'] = mind.calculate_baseline_metrics(
            data['temperature_skin'], 'nightly_relative',
            baseline_window=mind.BASELINE_WINDOWS['temp_variation']
        )

    # 4. 日別データ準備（表示期間のみ）
    print()
    print('日別データ準備中...')
    responsiveness_daily = mind.prepare_responsiveness_daily_data(
        start_date=target_start,
        end_date=target_end,
        df_hrv=data.get('hrv'),
        df_heart_rate=data.get('heart_rate'),
        df_breathing=data.get('breathing_rate'),
        df_temp=data.get('temperature_skin'),
        df_spo2=data.get('spo2'),
        df_bp=data.get('blood_pressure'),
        df_core_temp=data.get('core_temperature')
    )

    # 心拍ゾーン算出（hr_zones ライブラリ使用）
    personal_cfg = hr_zones.load_personal_config()
    df_hr_intraday = pd.read_csv(HEART_RATE_INTRADAY_CSV, index_col='datetime', parse_dates=True) if HEART_RATE_INTRADAY_CSV.exists() else None
    df_hr_daily_raw = pd.read_csv(HEART_RATE_CSV) if HEART_RATE_CSV.exists() else None
    hr_zone_meta = None
    df_zone = None
    if df_hr_intraday is not None and df_hr_daily_raw is not None:
        hr_zones_cfg = personal_cfg.get('hr_zones', {})
        resting_hr_cfg = hr_zones_cfg.get('resting_hr', {})
        window_days = resting_hr_cfg.get('window_days', 30)
        fallback = resting_hr_cfg.get('fallback', 48)
        method = hr_zones_cfg.get('method', 'hrr')
        import datetime as dt
        end_dt = target_end.date() if hasattr(target_end, 'date') else target_end
        max_hr = hr_zones.calc_max_hr(personal_cfg, end_dt)
        resting_hr = hr_zones.calc_resting_hr(df_hr_daily_raw, end_dt, window_days, fallback)
        bounds = hr_zones.compute_zone_bounds(max_hr, resting_hr, method)
        df_zone = hr_zones.calc_daily_zone_minutes(df_hr_intraday, bounds)
        import datetime as _dt
        birth_date = personal_cfg.get('birth_date')
        if isinstance(birth_date, str):
            birth_date = _dt.date.fromisoformat(birth_date)
        age = hr_zones.calc_age(birth_date, end_dt)
        hr_zone_meta = {
            'max_hr': max_hr,
            'resting_hr': resting_hr,
            'age': age,
            'method': method,
            'hrr': float(max_hr - resting_hr),
            'bounds': bounds,
            'window_days': window_days,
        }

    exertion_balance_daily = mind.prepare_exertion_balance_daily_data(
        start_date=target_start,
        end_date=target_end,
        df_activity=data.get('activity'),
        df_zone=df_zone
    )

    sleep_patterns_daily = mind.prepare_sleep_patterns_daily_data(
        start_date=target_start,
        end_date=target_end,
        df_sleep=data.get('sleep'),
        df_levels=data.get('sleep_levels')
    )

    print(f'  反応性データ: {len(responsiveness_daily)}日分')
    print(f'  運動バランスデータ: {len(exertion_balance_daily)}日分')
    print(f'  睡眠パターンデータ: {len(sleep_patterns_daily)}日分')

    # 期間文字列
    period_str = f'{target_start.strftime("%Y-%m-%d")} 〜 {target_end.strftime("%Y-%m-%d")}'

    # グラフ生成
    if not args.no_charts:
        print()
        print('グラフ生成中...')
        plot_hrv_chart(responsiveness_daily, img_dir / 'hrv.png')
        plot_hrv_rhr_chart(responsiveness_daily, img_dir / 'hrv_rhr.png')
        plot_comprehensive_trend(responsiveness_daily, sleep_patterns_daily, img_dir / 'comprehensive_trend.png')

    # レポート生成
    print()
    print('レポート生成中...')
    generate_report(output_dir, responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, period_str, len(responsiveness_daily), hr_zone_meta=hr_zone_meta, show_charts=not args.no_charts)

    print()
    print('='*60)
    print('レポート生成完了!')
    print('='*60)
    print(f'レポート: {output_dir / "REPORT.md"}')
    if not args.no_charts:
        print(f'画像: {img_dir}/')

    return 0


if __name__ == '__main__':
    exit(main())
