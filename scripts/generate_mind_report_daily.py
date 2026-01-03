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
from lib.utils.data_loader import load_csv_with_baseline_window, determine_target_period

BASE_DIR = project_root
HRV_CSV = BASE_DIR / 'data/fitbit/hrv.csv'
HEART_RATE_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'
SLEEP_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
SLEEP_LEVELS_CSV = BASE_DIR / 'data/fitbit/sleep_levels.csv'
BREATHING_RATE_CSV = BASE_DIR / 'data/fitbit/breathing_rate.csv'
SPO2_CSV = BASE_DIR / 'data/fitbit/spo2.csv'
CARDIO_SCORE_CSV = BASE_DIR / 'data/fitbit/cardio_score.csv'
TEMPERATURE_SKIN_CSV = BASE_DIR / 'data/fitbit/temperature_skin.csv'
ACTIVITY_CSV = BASE_DIR / 'data/fitbit/activity.csv'
ACTIVE_ZONE_MINUTES_CSV = BASE_DIR / 'data/fitbit/active_zone_minutes.csv'
ACTIVITY_LOGS_CSV = BASE_DIR / 'data/fitbit/activity_logs.csv'




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


def format_immune_stress_table(responsiveness_data, sleep_patterns_data):
    """
    免疫ストレススコア推移の表をテキストで生成

    Args:
        responsiveness_data: 反応性の日別データリスト
        sleep_patterns_data: 睡眠パターンの日別データリスト

    Returns:
        str: フォーマット済みの表テキスト
    """
    sleep_dict = {s['date']: s for s in sleep_patterns_data}
    lines = []

    for day in responsiveness_data:
        date_str = day['date'].strftime('%m/%d')
        score = day.get('immune_stress_score', 0.0)
        level = day.get('immune_stress_level', '🟢 正常範囲')

        # 異常指標を収集
        anomalies = []
        if day.get('spo2_avg_z_score') and abs(day['spo2_avg_z_score']) >= 1.5:
            anomalies.append(f"SpO2 {day['spo2_avg_z_score']:.1f}SD")
        if day.get('hrv_daily_z_score') and abs(day['hrv_daily_z_score']) >= 1.5:
            anomalies.append(f"HRV {day['hrv_daily_z_score']:.1f}SD")
        if day.get('breathing_rate_z_score') and abs(day['breathing_rate_z_score']) >= 1.5:
            anomalies.append(f"呼吸数 {day['breathing_rate_z_score']:.1f}SD")
        if day.get('temp_variation_z_score') and abs(day['temp_variation_z_score']) >= 1.5:
            anomalies.append(f"皮膚温 {day['temp_variation_z_score']:.1f}SD")

        sleep_day = sleep_dict.get(day['date'])
        if sleep_day and sleep_day.get('efficiency') and sleep_day['efficiency'] < 80:
            anomalies.append('睡眠効率低下')

        anomaly_str = ', '.join(anomalies) if anomalies else '-'

        line = f"{date_str}    {score:.1f}σ                   {level}     {anomaly_str}"
        lines.append(line)

    return '\n'.join(lines)


def calculate_immune_stress_scores(responsiveness_data, sleep_patterns_data, debug=False):
    """
    免疫ストレススコアを計算（FINAL_ANALYSIS.md Appendix A.3の式に基づく）

    Args:
        responsiveness_data: 反応性の日別データリスト
        sleep_patterns_data: 睡眠パターンの日別データリスト
        debug: デバッグ出力を有効にする（特定日のみ）

    Returns:
        responsiveness_dataに'immune_stress_score'を追加したリスト
    """
    # 睡眠データをdictに変換（日付でルックアップ）
    sleep_dict = {s['date']: s for s in sleep_patterns_data}

    # デバッグ対象日
    import pandas as pd
    debug_dates = [
        pd.Timestamp('2025-12-27'),
        pd.Timestamp('2025-12-28'),
        pd.Timestamp('2025-12-31'),
        pd.Timestamp('2026-01-01'),
        pd.Timestamp('2026-01-02'),
        pd.Timestamp('2026-01-03'),
    ]

    # デバッグ確認
    if debug:
        print(f"\n[DEBUG] デバッグモード有効、対象日: {debug_dates}")
        print(f"[DEBUG] データ数: {len(responsiveness_data)}")
        print(f"[DEBUG] 実際の日付:")
        for day in responsiveness_data:
            print(f"  - {day['date']} (type: {type(day['date'])}, in debug_dates: {day['date'] in debug_dates})")

    for day in responsiveness_data:
        # デバッグ: 日付チェック
        if debug:
            if day['date'] in debug_dates:
                print(f"\n[DEBUG] ✓ 日付マッチ: {day['date']} (type: {type(day['date'])})")

        # 各指標のz-scoreを取得（異常方向を統一: 高い方が悪い）
        spo2_z = 0.0
        hrv_z = 0.0
        breathing_z = 0.0
        temp_z = 0.0
        sleep_eff_z = 0.0
        wake_time_z = 0.0
        rhr_z = 0.0

        # SpO2異常（低い方が悪い → 符号反転）
        if day.get('spo2_avg_z_score') is not None:
            spo2_z = -day['spo2_avg_z_score']  # 負のz-scoreが悪い → 正に変換

        # HRV異常（低い方が悪い → 符号反転）
        if day.get('hrv_daily_z_score') is not None:
            hrv_z = -day['hrv_daily_z_score']  # 負のz-scoreが悪い → 正に変換

        # 呼吸数異常（高い方が悪い → そのまま）
        if day.get('breathing_rate_z_score') is not None:
            breathing_z = day['breathing_rate_z_score']

        # 皮膚温異常（高い方が悪い → 絶対値）
        if day.get('temp_variation_z_score') is not None:
            temp_z = abs(day['temp_variation_z_score'])  # 上昇も下降も異常として扱う

        # 睡眠効率異常（低い方が悪い → 符号反転）
        sleep_day = sleep_dict.get(day['date'])
        if sleep_day and sleep_day.get('efficiency') is not None:
            # 簡易計算: 80%未満をペナルティ化（より詳細な計算も可能）
            eff = sleep_day['efficiency']
            if eff < 80:
                sleep_eff_z = (80 - eff) / 10  # 80%からの乖離を簡易スコア化

        # 覚醒時間異常（高い方が悪い）
        # minutes_awakeはsleep_patterns_dataに含まれているはず
        # ベースラインとの差分をz-scoreとして使用する場合は別途計算が必要
        # ここでは簡易的に、異常に長い覚醒時間（90分以上）をペナルティ化
        if sleep_day and sleep_day.get('minutes_awake') is not None:
            awake = sleep_day['minutes_awake']
            # 簡易計算: 平均60分として、90分以上をペナルティ化
            if awake > 90:
                wake_time_z = (awake - 90) / 40  # 90分からの超過を簡易スコア化

        # RHR異常（高い方が悪い → そのまま）
        if day.get('rhr_z_score') is not None:
            rhr_z = day['rhr_z_score']

        # デバッグ出力（特定日のみ）
        if debug and day['date'] in debug_dates:
            print(f"\n{'='*80}")
            print(f"【免疫ストレススコア計算詳細】 {day['date']}")
            print(f"{'='*80}")
            print(f"\n【生理指標の実測値】")
            print(f"  HRV (RMSSD):     {day.get('hrv_daily', 'N/A')} ms")
            print(f"  RHR:             {day.get('rhr', 'N/A')} bpm")
            print(f"  呼吸数:          {day.get('breathing_rate', 'N/A')} /min")
            print(f"  SpO2 (平均):     {day.get('spo2_avg', 'N/A')} %")
            print(f"  SpO2 (最小):     {day.get('spo2_min', 'N/A')} %")
            print(f"  皮膚温変動:      {day.get('temp_variation', 'N/A')} °C")
            if sleep_day:
                print(f"  睡眠効率:        {sleep_day.get('efficiency', 'N/A')} %")
                print(f"  覚醒時間:        {sleep_day.get('minutes_awake', 'N/A')} 分")

            print(f"\n【ベースラインと標準偏差】")
            print(f"  HRV baseline:    {day.get('hrv_daily_baseline', 'N/A'):.1f} ± {day.get('hrv_daily_baseline_std', 'N/A'):.1f} ms")
            print(f"  RHR baseline:    {day.get('rhr_baseline', 'N/A'):.1f} ± {day.get('rhr_baseline_std', 'N/A'):.1f} bpm")
            print(f"  呼吸数 baseline: {day.get('breathing_rate_baseline', 'N/A'):.1f} ± {day.get('breathing_rate_baseline_std', 'N/A'):.1f} /min")
            print(f"  SpO2 baseline:   {day.get('spo2_avg_baseline', 'N/A'):.1f} ± {day.get('spo2_avg_baseline_std', 'N/A'):.1f} %")
            print(f"  皮膚温 baseline: {day.get('temp_variation_baseline', 'N/A'):.1f} ± {day.get('temp_variation_baseline_std', 'N/A'):.1f} °C")

            print(f"\n【Z-スコア】")
            print(f"  HRV Z-score:     {day.get('hrv_daily_z_score', 'N/A'):.2f} SD")
            print(f"  RHR Z-score:     {day.get('rhr_z_score', 'N/A'):.2f} SD")
            print(f"  呼吸数 Z-score:  {day.get('breathing_rate_z_score', 'N/A'):.2f} SD")
            print(f"  SpO2 Z-score:    {day.get('spo2_avg_z_score', 'N/A'):.2f} SD")
            print(f"  皮膚温 Z-score:  {day.get('temp_variation_z_score', 'N/A'):.2f} SD")

            print(f"\n【免疫ストレススコア計算】")
            print(f"  各指標の寄与分（異常方向に変換後 × 重み）:")

        # 免疫ストレス総合スコア計算（重み付き平均）
        # 異常方向のz-scoreのみを使用（正常範囲より良い値は0にクリップ）
        #
        # 重み設定の根拠:
        # - SpO2 (2.0): 潜伏期の早期兆候、変動しやすいため単独では重度異常にしない
        # - HRV (2.0): 発病直前の重要指標、疲労・ストレス・免疫の総合的指標
        # - 呼吸数 (1.5): 発病直前の兆候
        # - 皮膚温 (1.0): 発病時の明確な指標（発熱）
        # - 睡眠効率/覚醒時間 (1.0): 回復力の指標
        # - RHR (0.5): 補助的指標
        spo2_contrib = max(0, spo2_z) * 2.0  # 2.5 → 2.0 に調整
        hrv_contrib = max(0, hrv_z) * 2.0
        breathing_contrib = max(0, breathing_z) * 1.5
        temp_contrib = temp_z * 1.0
        sleep_eff_contrib = max(0, sleep_eff_z) * 1.0
        wake_time_contrib = max(0, wake_time_z) * 1.0
        rhr_contrib = max(0, rhr_z) * 0.5

        if debug and day['date'] in debug_dates:
            print(f"    SpO2:          {spo2_z:+.2f} SD (反転後) × 2.0 = {spo2_contrib:.3f}")
            print(f"    HRV:           {hrv_z:+.2f} SD (反転後) × 2.0 = {hrv_contrib:.3f}")
            print(f"    呼吸数:        {breathing_z:+.2f} SD × 1.5 = {breathing_contrib:.3f}")
            print(f"    皮膚温:        {temp_z:+.2f} SD (絶対値) × 1.0 = {temp_contrib:.3f}")
            print(f"    睡眠効率:      {sleep_eff_z:.2f} (簡易計算) × 1.0 = {sleep_eff_contrib:.3f}")
            print(f"    覚醒時間:      {wake_time_z:.2f} (簡易計算) × 1.0 = {wake_time_contrib:.3f}")
            print(f"    RHR:           {rhr_z:+.2f} SD × 0.5 = {rhr_contrib:.3f}")

        immune_stress_score = (
            spo2_contrib + hrv_contrib + breathing_contrib +
            temp_contrib + sleep_eff_contrib +
            wake_time_contrib + rhr_contrib
        ) / 5.0  # 感度調整: 9.5 → 5.0（実際の症状により一致させる）

        if debug and day['date'] in debug_dates:
            total_sum = spo2_contrib + hrv_contrib + breathing_contrib + temp_contrib + sleep_eff_contrib + wake_time_contrib + rhr_contrib
            print(f"\n  総合: ({total_sum:.3f}) / 5.0 = {immune_stress_score:.3f}σ")

        day['immune_stress_score'] = immune_stress_score

        # 判定レベル（FINAL_ANALYSIS.mdに基づく）
        if immune_stress_score >= 2.0:
            day['immune_stress_level'] = '🔴 重度異常'
        elif immune_stress_score >= 1.5:
            day['immune_stress_level'] = '⚠️ 警告レベル'
        elif immune_stress_score >= 1.0:
            day['immune_stress_level'] = '⚠️ 軽度異常'
        else:
            day['immune_stress_level'] = '🟢 正常範囲'

    return responsiveness_data


def detect_health_alerts(responsiveness_data, sleep_patterns_data):
    """
    体調アラートを検知

    Args:
        responsiveness_data: 反応性の日別データリスト
        sleep_patterns_data: 睡眠パターンの日別データリスト

    Returns:
        list[dict]: アラート情報のリスト
    """
    alerts = []

    for day in responsiveness_data:
        date = day['date']
        alert_items = []

        # HRV乖離チェック
        if day.get('hrv_daily_deviation_pct') is not None:
            dev = day['hrv_daily_deviation_pct']
            if dev < -15:
                alert_items.append(f"HRV大幅低下 ({dev:.1f}%)")
            elif dev < -10:
                alert_items.append(f"HRV低下 ({dev:.1f}%)")

        # RHR乖離チェック
        if day.get('rhr_deviation_pct') is not None:
            dev = day['rhr_deviation_pct']
            if dev > 5:
                alert_items.append(f"RHR上昇 (+{dev:.1f}%)")

        # 体温変動チェック（絶対値ベース）
        if day.get('temp_variation') is not None and day.get('temp_variation_baseline') is not None:
            temp_val = day['temp_variation']
            temp_baseline = day['temp_variation_baseline']
            temp_dev = temp_val - temp_baseline
            # ベースラインから±0.5℃以上の乖離で警告
            if abs(temp_dev) > 0.5:
                alert_items.append(f"体温変動異常 ({temp_dev:+.2f}℃)")

        # 睡眠効率チェック
        sleep_day = next((s for s in sleep_patterns_data if s['date'] == date), None)
        if sleep_day and sleep_day.get('efficiency') is not None:
            eff = sleep_day['efficiency']
            if eff < 80:
                alert_items.append(f"睡眠効率低下 ({eff:.0f}%)")

        # アラートがあれば追加
        if alert_items:
            alerts.append({
                'date': date,
                'messages': alert_items,
                'severity': 'high' if len(alert_items) >= 3 else 'medium' if len(alert_items) >= 2 else 'low'
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


def prepare_mind_report_data(responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, alerts, period_str, days):
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
    alerts : list
        検知されたアラートリスト
    period_str : str
        期間文字列
    days : int
        日数

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    # 免疫ストレススコア推移のテキストを生成
    immune_stress_table = format_immune_stress_table(responsiveness_daily, sleep_patterns_daily)

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

        # アラート
        'alerts': alerts,

        # 免疫ストレススコア推移表（フォーマット済みテキスト）
        'immune_stress_table': immune_stress_table,

        # チャート
        'charts': {
            'hrv_rhr': 'img/hrv_rhr.png',
            'hrv': 'img/hrv.png',
            'comprehensive_trend': 'img/comprehensive_trend.png',
        }
    }

    return context


def generate_report(output_dir, responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, alerts, period_str, days):
    """
    マークダウンレポートを生成（Jinja2テンプレート版）

    Args:
        output_dir: 出力ディレクトリ
        responsiveness_daily: 反応性の日別データリスト
        exertion_balance_daily: 運動バランスの日別データリスト
        sleep_patterns_daily: 睡眠パターンの日別データリスト
        alerts: アラートリスト
        period_str: 期間文字列
        days: 日数
    """
    from lib.templates.renderer import MindReportRenderer

    # コンテキストデータ準備
    context = prepare_mind_report_data(responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, alerts, period_str, days)

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

    # アクティビティ（ベースライン不要、表示期間のみ）
    if ACTIVITY_CSV.exists():
        data['activity'] = load_csv_with_baseline_window(
            ACTIVITY_CSV, target_start, target_end,
            baseline_window=0
        )

    # アクティブゾーン分（ベースライン不要）
    if ACTIVE_ZONE_MINUTES_CSV.exists():
        data['active_zone_minutes'] = load_csv_with_baseline_window(
            ACTIVE_ZONE_MINUTES_CSV, target_start, target_end,
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
    img_dir = output_dir / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

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
        df_spo2=data.get('spo2')
    )

    exertion_balance_daily = mind.prepare_exertion_balance_daily_data(
        start_date=target_start,
        end_date=target_end,
        df_activity=data.get('activity'),
        df_azm=data.get('active_zone_minutes')
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

    # 免疫ストレススコア計算
    print()
    print('免疫ストレススコア計算中...')
    responsiveness_daily = calculate_immune_stress_scores(responsiveness_daily, sleep_patterns_daily, debug=True)
    print(f'  免疫ストレススコア計算完了')

    # 期間文字列
    period_str = f'{target_start.strftime("%Y-%m-%d")} 〜 {target_end.strftime("%Y-%m-%d")}'

    # アラート検知
    print()
    print('アラート検知中...')
    alerts = detect_health_alerts(responsiveness_daily, sleep_patterns_daily)
    print(f'  検知されたアラート: {len(alerts)}件')

    # グラフ生成
    print()
    print('グラフ生成中...')
    plot_hrv_chart(responsiveness_daily, img_dir / 'hrv.png')
    plot_hrv_rhr_chart(responsiveness_daily, img_dir / 'hrv_rhr.png')
    plot_comprehensive_trend(responsiveness_daily, sleep_patterns_daily, img_dir / 'comprehensive_trend.png')

    # レポート生成
    print()
    print('レポート生成中...')
    generate_report(output_dir, responsiveness_daily, exertion_balance_daily, sleep_patterns_daily, alerts, period_str, len(responsiveness_daily))

    print()
    print('='*60)
    print('レポート生成完了!')
    print('='*60)
    print(f'レポート: {output_dir / "REPORT.md"}')
    print(f'画像: {img_dir}/')

    return 0


if __name__ == '__main__':
    exit(main())
