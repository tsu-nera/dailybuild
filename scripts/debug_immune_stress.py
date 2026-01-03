#!/usr/bin/env python3
"""免疫ストレススコアの診断スクリプト"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.lib.analytics.mind import prepare_responsiveness_daily_data, prepare_sleep_patterns_daily_data
from src.lib.data_loader import load_fitbit_data


def diagnose_immune_stress_score(target_dates):
    """特定日の免疫ストレススコア計算を診断"""

    print("=" * 80)
    print("免疫ストレススコア診断")
    print("=" * 80)

    # データ読み込み
    print("\nデータ読み込み中...")
    df_hrv = load_fitbit_data(project_root / 'data/fitbit/hrv.csv')
    df_hr = load_fitbit_data(project_root / 'data/fitbit/heart_rate.csv')
    df_br = load_fitbit_data(project_root / 'data/fitbit/breathing_rate.csv')
    df_spo2 = load_fitbit_data(project_root / 'data/fitbit/spo2.csv')
    df_temp = load_fitbit_data(project_root / 'data/fitbit/temperature_skin.csv')
    df_sleep = load_fitbit_data(project_root / 'data/fitbit/sleep.csv')

    # 反応性データ準備
    responsiveness_data = prepare_responsiveness_daily_data(
        df_hrv, df_hr, df_br, df_spo2, df_temp
    )

    # 睡眠データ準備
    sleep_data = prepare_sleep_patterns_daily_data(df_sleep)

    # 診断対象日をチェック
    for target_date in target_dates:
        target_date_obj = datetime.strptime(target_date, '%Y-%m-%d').date()

        print("\n" + "=" * 80)
        print(f"診断日: {target_date} ({target_date_obj.strftime('%m/%d')})")
        print("=" * 80)

        # 対象日のデータを取得
        day_data = next((d for d in responsiveness_data if d['date'] == target_date_obj), None)
        sleep_day = next((s for s in sleep_data if s['date'] == target_date_obj), None)

        if not day_data:
            print(f"⚠️ {target_date}のデータが見つかりません")
            continue

        print("\n【生理指標の実測値】")
        print(f"  HRV (RMSSD):     {day_data.get('hrv_daily', 'N/A')} ms")
        print(f"  RHR:             {day_data.get('rhr', 'N/A')} bpm")
        print(f"  呼吸数:          {day_data.get('breathing_rate', 'N/A')} /min")
        print(f"  SpO2 (平均):     {day_data.get('spo2_avg', 'N/A')} %")
        print(f"  SpO2 (最小):     {day_data.get('spo2_min', 'N/A')} %")
        print(f"  皮膚温変動:      {day_data.get('temp_variation', 'N/A')} °C")
        if sleep_day:
            print(f"  睡眠効率:        {sleep_day.get('efficiency', 'N/A')} %")
            print(f"  覚醒時間:        {sleep_day.get('minutes_awake', 'N/A')} 分")

        print("\n【ベースラインと標準偏差】")
        print(f"  HRV baseline:    {day_data.get('hrv_daily_baseline', 'N/A')} ± {day_data.get('hrv_daily_baseline_std', 'N/A')} ms")
        print(f"  RHR baseline:    {day_data.get('rhr_baseline', 'N/A')} ± {day_data.get('rhr_baseline_std', 'N/A')} bpm")
        print(f"  呼吸数 baseline: {day_data.get('breathing_rate_baseline', 'N/A')} ± {day_data.get('breathing_rate_baseline_std', 'N/A')} /min")
        print(f"  SpO2 baseline:   {day_data.get('spo2_avg_baseline', 'N/A')} ± {day_data.get('spo2_avg_baseline_std', 'N/A')} %")
        print(f"  皮膚温 baseline: {day_data.get('temp_variation_baseline', 'N/A')} ± {day_data.get('temp_variation_baseline_std', 'N/A')} °C")

        print("\n【Z-スコア (標準偏差単位での乖離)】")
        hrv_z = day_data.get('hrv_daily_z_score')
        rhr_z = day_data.get('rhr_z_score')
        br_z = day_data.get('breathing_rate_z_score')
        spo2_z = day_data.get('spo2_avg_z_score')
        temp_z = day_data.get('temp_variation_z_score')

        print(f"  HRV Z-score:     {hrv_z if hrv_z is not None else 'N/A'} SD")
        print(f"  RHR Z-score:     {rhr_z if rhr_z is not None else 'N/A'} SD")
        print(f"  呼吸数 Z-score:  {br_z if br_z is not None else 'N/A'} SD")
        print(f"  SpO2 Z-score:    {spo2_z if spo2_z is not None else 'N/A'} SD")
        print(f"  皮膚温 Z-score:  {temp_z if temp_z is not None else 'N/A'} SD")

        print("\n【免疫ストレススコア計算の詳細】")
        print("  各指標の寄与分（重み付き）:")

        # スコア計算を再現
        spo2_contribution = 0.0
        if spo2_z is not None:
            spo2_contribution = max(0, -spo2_z) * 2.5
            print(f"    SpO2:          {-spo2_z:.2f} SD × 2.5 = {spo2_contribution:.3f}")

        hrv_contribution = 0.0
        if hrv_z is not None:
            hrv_contribution = max(0, -hrv_z) * 2.0
            print(f"    HRV:           {-hrv_z:.2f} SD × 2.0 = {hrv_contribution:.3f}")

        br_contribution = 0.0
        if br_z is not None:
            br_contribution = max(0, br_z) * 1.5
            print(f"    呼吸数:        {br_z:.2f} SD × 1.5 = {br_contribution:.3f}")

        temp_contribution = 0.0
        if temp_z is not None:
            temp_contribution = abs(temp_z) * 1.0
            print(f"    皮膚温:        |{temp_z:.2f}| SD × 1.0 = {temp_contribution:.3f}")

        sleep_eff_contribution = 0.0
        if sleep_day and sleep_day.get('efficiency') is not None:
            eff = sleep_day['efficiency']
            if eff < 80:
                sleep_eff_contribution = (80 - eff) / 10
                print(f"    睡眠効率:      (80 - {eff}) / 10 = {sleep_eff_contribution:.3f}")

        wake_time_contribution = 0.0
        if sleep_day and sleep_day.get('minutes_awake') is not None:
            awake = sleep_day['minutes_awake']
            if awake > 90:
                wake_time_contribution = (awake - 90) / 40
                print(f"    覚醒時間:      ({awake} - 90) / 40 = {wake_time_contribution:.3f}")

        rhr_contribution = 0.0
        if rhr_z is not None:
            rhr_contribution = max(0, rhr_z) * 0.5
            print(f"    RHR:           {rhr_z:.2f} SD × 0.5 = {rhr_contribution:.3f}")

        total_score = (
            spo2_contribution + hrv_contribution + br_contribution +
            temp_contribution + sleep_eff_contribution +
            wake_time_contribution + rhr_contribution
        ) / 9.5

        print(f"\n  総合スコア: ({spo2_contribution:.3f} + {hrv_contribution:.3f} + {br_contribution:.3f} + {temp_contribution:.3f} + {sleep_eff_contribution:.3f} + {wake_time_contribution:.3f} + {rhr_contribution:.3f}) / 9.5")
        print(f"            = {total_score:.3f}σ")

        # 判定レベル
        if total_score >= 2.0:
            level = "🔴 重度異常"
        elif total_score >= 1.5:
            level = "⚠️ 警告レベル"
        elif total_score >= 1.0:
            level = "⚠️ 軽度異常"
        else:
            level = "🟢 正常範囲"

        print(f"\n  判定: {level}")

        # 異常指標の列挙
        anomalies = []
        if spo2_z is not None and abs(spo2_z) >= 1.5:
            anomalies.append(f"SpO2 {spo2_z:.1f}SD")
        if hrv_z is not None and abs(hrv_z) >= 1.5:
            anomalies.append(f"HRV {hrv_z:.1f}SD")
        if br_z is not None and abs(br_z) >= 1.5:
            anomalies.append(f"呼吸数 {br_z:.1f}SD")
        if temp_z is not None and abs(temp_z) >= 1.5:
            anomalies.append(f"皮膚温 {temp_z:.1f}SD")
        if sleep_day and sleep_day.get('efficiency') and sleep_day['efficiency'] < 80:
            anomalies.append('睡眠効率低下')

        print(f"  主な異常指標: {', '.join(anomalies) if anomalies else '-'}")


if __name__ == '__main__':
    # 診断対象日
    target_dates = [
        '2025-12-27',  # 1.1σ (期待値: 1.6σ)
        '2025-12-28',  # 1.0σ (期待値: 1.8σ)
        '2025-12-31',  # 0.8σ (warningであるべき)
        '2026-01-01',  # 1.0σ (発熱日、重度異常であるべき)
    ]

    diagnose_immune_stress_score(target_dates)
