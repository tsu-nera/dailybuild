#!/usr/bin/env python
# coding: utf-8
"""
Zone2（LT1アンカー）計測ライブラリ

いわゆる "Zone2 トレーニング"（LT1=有酸素閾値の直下、脂質酸化が最大化する
スイートスポット）の時間を計測する。%HRR カルボーネン法（hr_zones.py）とは
目的が別であり、本モジュールは LT1 を単一真実としてアンカーする。

LT1 は本来 個人の乳酸/換気閾値を実測してアンカーするのが正道。現状は MAF式
(base - age) を暫定プレースホルダとし、Talk Test/DFA-α1 実測値で
config の manual_bpm により上書き較正できる構造とする。

経緯: issues/013_zone/report.md, GitHub issue #21
"""

import datetime

import pandas as pd

from lib.analytics.hr_zones import calc_age, load_personal_config  # noqa: F401


def calc_lt1(personal_cfg, ref_date):
    """LT1（有酸素閾値心拍）を算出する。

    優先順位: manual_bpm（実測） > method=maf（MAF式 base - age）。

    Parameters
    ----------
    personal_cfg : dict
        load_personal_config() の戻り値。
    ref_date : datetime.date
        age 算出の基準日（通常はレポート終了日）。

    Returns
    -------
    tuple[float, str]
        (lt1_bpm, source) — source は 'manual' または 'maf'。
    """
    zone2_cfg = personal_cfg.get('zone2', {}) or {}
    lt1_cfg = zone2_cfg.get('lt1', {}) or {}

    manual = lt1_cfg.get('manual_bpm')
    if manual is not None and manual != '':
        return float(manual), 'manual'

    method = lt1_cfg.get('method', 'maf')
    if method == 'maf':
        maf_base = lt1_cfg.get('maf_base', 180)
        birth_date = personal_cfg.get('birth_date')
        if isinstance(birth_date, str):
            birth_date = datetime.date.fromisoformat(birth_date)
        age = calc_age(birth_date, ref_date)
        return float(maf_base - age), 'maf'

    raise ValueError(f"未対応の LT1 method: {method}（manual_bpm を設定してください）")


def compute_zone2_band(lt1, band_width):
    """Zone2 の心拍帯（下限・上限）を算出する。

    狭義(San Millán的): Zone2 = [lt1 - band_width, lt1)。
    この帯自体が安静/睡眠を自然に除外するため別途の活動フィルタは不要。

    Parameters
    ----------
    lt1 : float
        LT1 心拍 (bpm)。
    band_width : float
        帯幅 (bpm)。

    Returns
    -------
    tuple[float, float]
        (lower, upper) = (lt1 - band_width, lt1)。
    """
    lower = float(lt1) - float(band_width)
    upper = float(lt1)
    assert lower < upper, f"Zone2 帯が不正です: [{lower}, {upper})"
    return lower, upper


def calc_daily_zone2_minutes(df_hr_intraday, band):
    """1分データから日別 Zone2 分を集計する。

    Parameters
    ----------
    df_hr_intraday : pd.DataFrame
        index=datetime (parse_dates)、列 heart_rate。1行=1分。
    band : tuple[float, float]
        compute_zone2_band() の戻り値 (lower, upper)。

    Returns
    -------
    pd.DataFrame
        index=正規化日付(pd.Timestamp)、列 zone2_min (int)。
    """
    lower, upper = band
    df = df_hr_intraday.copy()
    df['bpm'] = pd.to_numeric(df['heart_rate'], errors='coerce')
    df['in_zone2'] = (df['bpm'] >= lower) & (df['bpm'] < upper)
    df['date'] = df.index.normalize()

    grouped = df.groupby('date')['in_zone2'].sum().astype(int)
    df_result = grouped.to_frame(name='zone2_min')
    return df_result


def prepare_zone2_daily_data(start_date, end_date, df_hr_intraday, personal_cfg, ref_date=None):
    """Zone2 日別データを準備する。

    Parameters
    ----------
    start_date : datetime.date or str
        レポート開始日。
    end_date : datetime.date or str
        レポート終了日。
    df_hr_intraday : pd.DataFrame
        heart_rate_intraday.csv を読んだ DataFrame（index=datetime）。
    personal_cfg : dict
        load_personal_config() の戻り値。
    ref_date : datetime.date, optional
        LT1 の age 算出基準日。未指定時は end_date を使用。

    Returns
    -------
    tuple[list[dict], dict]
        (daily_list, meta)
        daily_list: 各日 {'date', 'zone2_min'}
        meta: lt1, lt1_source, band_lower, band_upper, band_width, age
    """
    if isinstance(end_date, str):
        end_date = datetime.date.fromisoformat(end_date)
    if isinstance(start_date, str):
        start_date = datetime.date.fromisoformat(start_date)

    ref = ref_date if ref_date is not None else end_date
    if hasattr(ref, 'date'):
        ref = ref.date()

    zone2_cfg = personal_cfg.get('zone2', {}) or {}
    band_width = zone2_cfg.get('band_width_bpm', 15)

    lt1, lt1_source = calc_lt1(personal_cfg, ref)
    band = compute_zone2_band(lt1, band_width)

    df_z2 = calc_daily_zone2_minutes(df_hr_intraday, band)

    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
    daily_list = []
    for date in all_dates:
        if date in df_z2.index:
            zone2_min = int(df_z2.loc[date, 'zone2_min'])
        else:
            zone2_min = None
        daily_list.append({'date': date, 'zone2_min': zone2_min})

    birth_date = personal_cfg.get('birth_date')
    if isinstance(birth_date, str):
        birth_date = datetime.date.fromisoformat(birth_date)

    meta = {
        'lt1': lt1,
        'lt1_source': lt1_source,
        'band_lower': band[0],
        'band_upper': band[1],
        'band_width': float(band_width),
        'age': calc_age(birth_date, ref),
    }

    return daily_list, meta


if __name__ == '__main__':
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    hr_intraday_path = repo_root / 'data' / 'fitbit' / 'heart_rate_intraday.csv'

    df_hr_intraday = pd.read_csv(hr_intraday_path, index_col='datetime', parse_dates=True)
    personal_cfg = load_personal_config()

    today = datetime.date.today()
    start = today - datetime.timedelta(days=29)

    daily_list, meta = prepare_zone2_daily_data(start, today, df_hr_intraday, personal_cfg)

    print(f"Period: {start} ~ {today}")
    print(f"Meta: {meta}")
    print(f"LT1={meta['lt1']:.0f}bpm ({meta['lt1_source']}), "
          f"Zone2 band=[{meta['band_lower']:.0f}, {meta['band_upper']:.0f}) bpm")

    total = sum(d['zone2_min'] for d in daily_list if d['zone2_min'] is not None)
    print(f"30日 Zone2 合計: {total} 分")

    # アサーション
    assert meta['band_lower'] < meta['band_upper'], "Zone2 帯が単調でない"
    assert meta['lt1'] > 0, "LT1 が不正"
    print("SMOKE OK")
