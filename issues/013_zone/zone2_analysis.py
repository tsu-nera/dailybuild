#!/usr/bin/env python
# coding: utf-8
"""
Zone2（LT1アンカー）分析レポート — issue #21

目的(a): いわゆる Zone2 の量を計測する。
較正前の暫定として MAF / 現Z1 / 現Z2 を併記し、後日 Talk Test/DFA 実測値が
出たとき「どの暫定が実態に近かったか」を突合できるようにする。

期間: 直近3ヶ月（2026-02-17 〜 2026-05-17）
出力: issues/013_zone/zone2_report.md
"""

import datetime
import sys
from pathlib import Path

import pandas as pd

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / 'src'))

from lib.analytics import zone2, hr_zones

END_DATE = datetime.date(2026, 5, 17)
START_DATE = END_DATE - datetime.timedelta(days=89)


def main():
    hr_intraday_path = repo_root / 'data' / 'fitbit' / 'heart_rate_intraday.csv'
    hr_daily_path = repo_root / 'data' / 'fitbit' / 'heart_rate.csv'

    df_hr_intraday = pd.read_csv(hr_intraday_path, index_col='datetime', parse_dates=True)
    df_hr_daily = pd.read_csv(hr_daily_path)
    personal_cfg = hr_zones.load_personal_config()

    # --- MAF Zone2 ---
    z2_daily, z2_meta = zone2.prepare_zone2_daily_data(
        START_DATE, END_DATE, df_hr_intraday, personal_cfg, ref_date=END_DATE
    )

    # --- 現 %HRR Z1 / Z2（比較用） ---
    max_hr = hr_zones.calc_max_hr(personal_cfg, END_DATE)
    resting_hr = hr_zones.calc_resting_hr(df_hr_daily, END_DATE, 30, 48)
    bounds = hr_zones.compute_zone_bounds(max_hr, resting_hr, 'hrr')

    hr = pd.to_numeric(df_hr_intraday['heart_rate'], errors='coerce')
    mask = (df_hr_intraday.index >= pd.Timestamp(START_DATE)) & \
           (df_hr_intraday.index <= pd.Timestamp(END_DATE) + pd.Timedelta(days=1))
    hr = hr[mask].dropna()

    z1_lo, z1_hi = bounds['Z1'], bounds['Z2']
    z2_lo, z2_hi = bounds['Z2'], bounds['Z3']
    maf_lo, maf_hi = z2_meta['band_lower'], z2_meta['band_upper']

    z1_total = int(((hr >= z1_lo) & (hr < z1_hi)).sum())
    z2hrr_total = int(((hr >= z2_lo) & (hr < z2_hi)).sum())
    maf_total = sum(d['zone2_min'] for d in z2_daily if d['zone2_min'] is not None)

    lines = []
    lines.append("# Zone2（LT1アンカー）分析レポート")
    lines.append("")
    lines.append(f"**期間**: {START_DATE} 〜 {END_DATE} (90日間)")
    lines.append(f"**生成日**: {datetime.date.today()}")
    lines.append("")
    lines.append("> 目的(a): いわゆる Zone2（LT1直下の有酸素スイートスポット）の量を計測する。")
    lines.append("> LT1 較正前の暫定。Talk Test/DFA-α1 実測値が出たら `config/personal.yaml`")
    lines.append("> の `zone2.lt1.manual_bpm` を上書きし本レポートを再生成して突合する。")
    lines.append("")

    lines.append("## LT1 / Zone2 帯（現設定）")
    lines.append("")
    lines.append("| 項目 | 値 |")
    lines.append("| --- | --- |")
    src = z2_meta['lt1_source']
    src_note = f"MAF式 180-{z2_meta['age']}（暫定・低体力者では過大傾向）" if src == 'maf' else "実測値"
    lines.append(f"| LT1 | {z2_meta['lt1']:.0f} bpm（{src} = {src_note}） |")
    lines.append(f"| Zone2 帯 | [{maf_lo:.0f}, {maf_hi:.0f}) bpm（帯幅 {z2_meta['band_width']:.0f}bpm） |")
    lines.append("")

    lines.append("## 暫定3手法の比較（90日積算）")
    lines.append("")
    lines.append("| 手法 | 心拍帯 (bpm) | 90日合計 | 週平均 | 性格 |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    lines.append(f"| **MAF Zone2**（採用・暫定） | [{maf_lo:.0f}, {maf_hi:.0f}) | {maf_total} 分 | {maf_total/12.85:.1f} 分 | LT1アンカー。実測で上書き可 |")
    lines.append(f"| 現 %HRR Z1 | [{z1_lo:.0f}, {z1_hi:.0f}) | {z1_total} 分 | {z1_total/12.85:.1f} 分 | 予備心拍50-60%。Zone2狙いでない |")
    lines.append(f"| 現 %HRR Z2 | [{z2_lo:.0f}, {z2_hi:.0f}) | {z2hrr_total} 分 | {z2hrr_total/12.85:.1f} 分 | 予備心拍60-70%。MAFとほぼ同帯 |")
    lines.append("")
    lines.append("> MAF と 現Z2 は帯がほぼ一致（偶然の産物）。MAF採用はラベルの誠実さと")
    lines.append("> 「LT1単一真実→実測で較正」構造のため。現Z1はそもそもZone2を狙っていない。")
    lines.append("")

    # 週次推移
    lines.append("## MAF Zone2 週次推移")
    lines.append("")
    lines.append("| 週 | Zone2分 |")
    lines.append("| --- | ---: |")
    df_z2d = pd.DataFrame(z2_daily)
    df_z2d['week'] = pd.to_datetime(df_z2d['date']).dt.to_period('W')
    for wk, g in df_z2d.groupby('week'):
        v = g['zone2_min'].dropna().sum()
        lines.append(f"| {wk.start_time.date()}週 | {int(v)} |")
    lines.append("")

    lines.append("## 注意（恒久）")
    lines.append("")
    lines.append("- LT1=MAF は **未較正の暫定値**。低体力者では LT1 を過大評価し Zone2 を過小計上しうる")
    lines.append("- 正確化には Talk Test（研究検証済み）等で LT1 実測 → `manual_bpm` 上書きが必須")
    lines.append("- 将来: 胸ストラップ R-R + DFA-α1（α1≈0.75）で LT1 自動同定（別 issue）")
    lines.append("")

    out = Path(__file__).parent / 'zone2_report.md'
    out.write_text("\n".join(lines), encoding='utf-8')
    print(f"LT1={z2_meta['lt1']:.0f}bpm({src}) band=[{maf_lo:.0f},{maf_hi:.0f})")
    print(f"MAF Zone2={maf_total}分 / 現Z1={z1_total}分 / 現Z2={z2hrr_total}分 (90日)")
    print(f"出力: {out}")


if __name__ == '__main__':
    main()
