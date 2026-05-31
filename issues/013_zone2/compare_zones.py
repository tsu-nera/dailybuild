#!/usr/bin/env python
# coding: utf-8
"""
旧ロジック（Fitbit AZM: fat_burn/cardio/peak）vs 新ロジック（Karvonen %HRR Z1-Z5）比較レポート生成

期間: 直近3ヶ月（2026-02-17 〜 2026-05-17）
出力: issues/013_zone/report.md
"""

import datetime
import sys
from pathlib import Path

import pandas as pd

# リポジトリルートをパスに追加
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from src.lib.analytics.hr_zones import (
    compute_zone_bounds,
    calc_daily_zone_minutes,
    calc_max_hr,
    calc_resting_hr,
    load_personal_config,
    ZONE_NAMES,
    ZONE_LABELS,
)

# --- 設定 ---
END_DATE = datetime.date(2026, 5, 17)
START_DATE = END_DATE - datetime.timedelta(days=89)  # 90日間


def load_data():
    azm_path = repo_root / 'data' / 'fitbit' / 'active_zone_minutes.csv'
    hr_intraday_path = repo_root / 'data' / 'fitbit' / 'heart_rate_intraday.csv'
    hr_daily_path = repo_root / 'data' / 'fitbit' / 'heart_rate.csv'

    df_azm = pd.read_csv(azm_path, parse_dates=['date'])
    df_hr_intraday = pd.read_csv(hr_intraday_path, index_col='datetime', parse_dates=True)
    df_hr_daily = pd.read_csv(hr_daily_path)

    return df_azm, df_hr_intraday, df_hr_daily


def filter_period(df, date_col='date'):
    mask = (df[date_col] >= pd.Timestamp(START_DATE)) & (df[date_col] <= pd.Timestamp(END_DATE))
    return df[mask].copy()


def calc_new_zones(df_hr_intraday, df_hr_daily, personal_cfg):
    """新ロジック: Karvonen %HRR Z1-Z5"""
    max_hr = calc_max_hr(personal_cfg, END_DATE)
    resting_hr = calc_resting_hr(df_hr_daily, END_DATE, window_days=30, fallback=48)
    bounds = compute_zone_bounds(max_hr, resting_hr)

    df_zone = calc_daily_zone_minutes(df_hr_intraday, bounds)

    # 期間フィルタ
    df_zone = df_zone[
        (df_zone.index >= pd.Timestamp(START_DATE)) &
        (df_zone.index <= pd.Timestamp(END_DATE))
    ]

    return df_zone, max_hr, resting_hr, bounds


def build_report(df_azm, df_zone_new, max_hr, resting_hr, bounds):
    lines = []

    lines.append("# 心拍ゾーン算出ロジック比較レポート")
    lines.append("")
    lines.append(f"**期間**: {START_DATE} 〜 {END_DATE} (90日間)")
    lines.append(f"**生成日**: {datetime.date.today()}")
    lines.append("")

    # --- アルゴリズム概要 ---
    lines.append("## アルゴリズム概要")
    lines.append("")
    lines.append("| 項目 | 旧ロジック (Fitbit AZM) | 新ロジック (Karvonen %HRR) |")
    lines.append("| --- | --- | --- |")
    lines.append("| データソース | Fitbit API (AZM) | heart_rate_intraday.csv |")
    lines.append("| ゾーン定義 | fat_burn / cardio / peak | Z1〜Z5 (5段階) |")
    lines.append("| 境界算出 | Fitbit 独自 (非公開) | Tanaka式maxHR + カルボーネン%HRR |")
    lines.append("| RHR | Fitbit API提供 | 直近30日中央値 |")
    lines.append("")

    # --- 新ロジックパラメータ ---
    lines.append("## 新ロジック パラメータ（2026-05-17 基準）")
    lines.append("")
    lines.append(f"- **年齢**: 39歳")
    lines.append(f"- **最大心拍数 (Tanaka式)**: {max_hr} bpm")
    lines.append(f"- **安静時心拍数 (直近30日中央値)**: {resting_hr:.1f} bpm")
    lines.append(f"- **HRR**: {max_hr - resting_hr:.1f} bpm")
    lines.append("")
    lines.append("| ゾーン | ラベル | %HRR | 下限 (bpm) |")
    lines.append("| --- | --- | --- | --- |")
    thresholds = {'Z1': 0.50, 'Z2': 0.60, 'Z3': 0.70, 'Z4': 0.80, 'Z5': 0.90}
    for z in ZONE_NAMES:
        lines.append(f"| {z} | {ZONE_LABELS[z]} | {int(thresholds[z]*100)}% | {bounds[z]:.1f} |")
    lines.append("")

    # --- 集計比較 ---
    lines.append("## 3ヶ月集計比較")
    lines.append("")

    # 旧ロジック集計
    df_azm_period = filter_period(df_azm)
    old_total = df_azm_period['activeZoneMinutes'].sum()
    old_fat = df_azm_period['fatBurnActiveZoneMinutes'].sum()
    old_cardio = df_azm_period['cardioActiveZoneMinutes'].sum()
    old_peak = df_azm_period['peakActiveZoneMinutes'].fillna(0).sum()
    old_days = df_azm_period['activeZoneMinutes'].notna().sum()

    # 新ロジック集計
    new_z1 = df_zone_new['z1_min'].sum()
    new_z2 = df_zone_new['z2_min'].sum()
    new_z3 = df_zone_new['z3_min'].sum()
    new_z4 = df_zone_new['z4_min'].sum()
    new_z5 = df_zone_new['z5_min'].sum()
    new_total = df_zone_new['total_zone_min'].sum()
    new_days = len(df_zone_new)

    lines.append("### 旧ロジック (Fitbit AZM) 90日合計")
    lines.append("")
    lines.append(f"- **計測日数**: {old_days} 日")
    lines.append(f"- **総AZM**: {old_total:.0f} 分")
    lines.append(f"- fat_burn: {old_fat:.0f} 分")
    lines.append(f"- cardio: {old_cardio:.0f} 分")
    lines.append(f"- peak: {old_peak:.0f} 分")
    lines.append("")

    lines.append("### 新ロジック (Karvonen Z1-Z5) 90日合計")
    lines.append("")
    lines.append(f"- **計測日数**: {new_days} 日")
    lines.append(f"- **総ゾーン分**: {new_total:.0f} 分")
    lines.append(f"- Z1 (回復): {new_z1:.0f} 分")
    lines.append(f"- Z2 (有酸素): {new_z2:.0f} 分")
    lines.append(f"- Z3 (テンポ): {new_z3:.0f} 分")
    lines.append(f"- Z4 (閾値): {new_z4:.0f} 分")
    lines.append(f"- Z5 (VO2max): {new_z5:.0f} 分")
    lines.append("")

    # --- ゾーン対応マッピング考察 ---
    lines.append("### ゾーン対応マッピング考察")
    lines.append("")
    lines.append("Fitbit AZM のゾーン定義（非公開）と Karvonen %HRR の概念的対応:")
    lines.append("")
    lines.append("| Fitbit AZM | Karvonen %HRR | 説明 |")
    lines.append("| --- | --- | --- |")
    lines.append("| fat_burn (~50-69% HRmax) | Z2 (60-70% HRR) | 有酸素低強度。HRmax基準なので若干ずれあり |")
    lines.append("| cardio (~70-84% HRmax) | Z3-Z4 (70-90% HRR) | 中〜高強度域 |")
    lines.append("| peak (≥85% HRmax) | Z5 (≥90% HRR) | 最高強度 |")
    lines.append("")
    lines.append("> 旧: %HRmax基準、新: %HRR(カルボーネン)基準。HRR法は安静時HRを考慮するため、同じ%でも絶対値が異なる。")
    lines.append("")

    # --- 日別データ比較テーブル ---
    lines.append("## 日別データ比較（全90日）")
    lines.append("")
    lines.append("| 日付 | [旧] fat_burn | [旧] cardio | [旧] peak | [旧] AZM合計 | [新] Z1 | [新] Z2 | [新] Z3 | [新] Z4 | [新] Z5 | [新] 合計 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    all_dates = pd.date_range(start=START_DATE, end=END_DATE, freq='D')
    df_azm_idx = df_azm.set_index('date')

    for date in all_dates:
        date_str = date.strftime('%Y-%m-%d')
        ts = pd.Timestamp(date)

        # 旧ロジック
        if ts in df_azm_idx.index:
            row_azm = df_azm_idx.loc[ts]
            fat = f"{row_azm['fatBurnActiveZoneMinutes']:.0f}" if pd.notna(row_azm['fatBurnActiveZoneMinutes']) else "-"
            cardio = f"{row_azm['cardioActiveZoneMinutes']:.0f}" if pd.notna(row_azm['cardioActiveZoneMinutes']) else "-"
            peak = f"{row_azm['peakActiveZoneMinutes']:.0f}" if pd.notna(row_azm['peakActiveZoneMinutes']) else "-"
            azm_total = f"{row_azm['activeZoneMinutes']:.0f}" if pd.notna(row_azm['activeZoneMinutes']) else "-"
        else:
            fat = cardio = peak = azm_total = "-"

        # 新ロジック
        if ts in df_zone_new.index:
            row_new = df_zone_new.loc[ts]
            z1 = str(int(row_new['z1_min']))
            z2 = str(int(row_new['z2_min']))
            z3 = str(int(row_new['z3_min']))
            z4 = str(int(row_new['z4_min']))
            z5 = str(int(row_new['z5_min']))
            new_t = str(int(row_new['total_zone_min']))
        else:
            z1 = z2 = z3 = z4 = z5 = new_t = "-"

        lines.append(f"| {date_str} | {fat} | {cardio} | {peak} | {azm_total} | {z1} | {z2} | {z3} | {z4} | {z5} | {new_t} |")

    lines.append("")

    # --- 週次集計比較 ---
    lines.append("## 週次集計比較")
    lines.append("")
    lines.append("| 週 | [旧] fat_burn | [旧] cardio | [旧] peak | [旧] AZM合計 | [新] Z1+Z2 | [新] Z3+Z4 | [新] Z5 | [新] 合計 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    # 週ごとに集計
    df_azm_period2 = df_azm_period.copy()
    df_azm_period2['week'] = df_azm_period2['date'].dt.to_period('W')

    df_new_period = df_zone_new.copy()
    df_new_period['week'] = df_new_period.index.to_period('W')

    weeks = sorted(df_azm_period2['week'].unique().tolist())

    for week in weeks:
        w_azm = df_azm_period2[df_azm_period2['week'] == week]
        w_new = df_new_period[df_new_period['week'] == week]

        w_fat = w_azm['fatBurnActiveZoneMinutes'].sum()
        w_cardio = w_azm['cardioActiveZoneMinutes'].sum()
        w_peak = w_azm['peakActiveZoneMinutes'].fillna(0).sum()
        w_azm_total = w_azm['activeZoneMinutes'].sum()

        w_z12 = w_new['z1_min'].sum() + w_new['z2_min'].sum()
        w_z34 = w_new['z3_min'].sum() + w_new['z4_min'].sum()
        w_z5 = w_new['z5_min'].sum()
        w_new_total = w_new['total_zone_min'].sum()

        week_str = str(week.start_time.date())
        lines.append(f"| {week_str}週 | {w_fat:.0f} | {w_cardio:.0f} | {w_peak:.0f} | {w_azm_total:.0f} | {w_z12:.0f} | {w_z34:.0f} | {w_z5:.0f} | {w_new_total:.0f} |")

    lines.append("")

    # --- 総括 ---
    lines.append("## 総括・考察")
    lines.append("")
    lines.append("### スケール差異")
    scale = new_total / old_total if old_total > 0 else float('nan')
    lines.append(f"- 新ロジック総計 / 旧ロジック総計 = {new_total:.0f} / {old_total:.0f} = **{scale:.2f}倍**")
    lines.append(f"- 新ロジックは全ゾーン（Z1含む低強度）を計上するため総分数が大幅に多い")
    lines.append("")
    lines.append("### 高強度域（旧 cardio+peak vs 新 Z3+Z4+Z5）")
    old_high = old_cardio + old_peak
    new_high = new_z3 + new_z4 + new_z5
    lines.append(f"- 旧 cardio+peak: {old_high:.0f} 分")
    lines.append(f"- 新 Z3+Z4+Z5: {new_high:.0f} 分")
    ratio = new_high / old_high if old_high > 0 else float('nan')
    lines.append(f"- 比率: {ratio:.2f}倍")
    lines.append("")
    lines.append("### 主な違い")
    lines.append("1. **Z1（回復帯）の追加**: 旧ロジックにはなかった低強度帯が可視化される")
    lines.append("2. **基準の差異**: 旧=%HRmax、新=%HRR（カルボーネン）。同じ心拍でも異なるゾーンに分類される可能性")
    lines.append("3. **RHRの扱い**: 旧=Fitbit算出、新=直近30日中央値。今回RHR={:.1f}bpm".format(resting_hr))
    lines.append("4. **データソース**: 旧=Fitbit AZM API（クラウド集計）、新=1分インターバルデータからの自前集計")
    lines.append("")

    return "\n".join(lines)


def main():
    print(f"期間: {START_DATE} 〜 {END_DATE}")
    print("データ読み込み中...")

    df_azm, df_hr_intraday, df_hr_daily = load_data()
    personal_cfg = load_personal_config()

    print("新ロジック計算中...")
    df_zone_new, max_hr, resting_hr, bounds = calc_new_zones(df_hr_intraday, df_hr_daily, personal_cfg)

    print(f"新ロジック - max_hr: {max_hr}, resting_hr: {resting_hr:.1f}, bounds: {bounds}")
    print(f"新ロジック対象日数: {len(df_zone_new)}")

    report = build_report(df_azm, df_zone_new, max_hr, resting_hr, bounds)

    output_path = Path(__file__).parent / 'report.md'
    output_path.write_text(report, encoding='utf-8')
    print(f"\nレポート出力完了: {output_path}")


if __name__ == '__main__':
    main()
