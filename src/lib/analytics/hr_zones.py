#!/usr/bin/env python
# coding: utf-8
"""
心拍ゾーン計算ライブラリ

%HRRカルボーネン法による心拍ゾーン算出を提供。
"""

import datetime
from pathlib import Path

import pandas as pd
import yaml

# ゾーン定義
ZONE_NAMES = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5']
ZONE_LABELS = {'Z1': '回復', 'Z2': '有酸素', 'Z3': 'テンポ', 'Z4': '閾値', 'Z5': 'VO2max'}
ZONE_THRESHOLDS = {'hrr': {'Z1': 0.50, 'Z2': 0.60, 'Z3': 0.70, 'Z4': 0.80, 'Z5': 0.90}}


def load_personal_config(config_path=None):
    """個人プロファイルをロードする。

    Parameters
    ----------
    config_path : str or Path, optional
        personal.yaml のパス。未指定時はリポジトリルートの config/personal.yaml を使用。

    Returns
    -------
    dict
        personal.yaml の内容。

    Raises
    ------
    FileNotFoundError
        config/personal.yaml が存在しない場合。
    """
    if config_path is None:
        # __file__ から repo ルートを特定
        p = Path(__file__).resolve()
        repo_root = None
        for parent in p.parents:
            if parent.name == 'dailybuild' or (parent / 'config').is_dir():
                repo_root = parent
                break
        if repo_root is None:
            raise FileNotFoundError("リポジトリルートが見つかりません。config/personal.yaml のパスを明示してください。")
        config_path = repo_root / 'config' / 'personal.yaml'
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"personal.yaml が見つかりません: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def calc_age(birth_date, ref_date):
    """年齢を算出する。

    Parameters
    ----------
    birth_date : datetime.date
        生年月日。
    ref_date : datetime.date
        基準日（通常はレポート終了日）。

    Returns
    -------
    int
        年齢（歳）。
    """
    age = ref_date.year - birth_date.year
    # 誕生日未到来分を引く
    if (ref_date.month, ref_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def calc_max_hr(personal_cfg, ref_date):
    """最大心拍数を算出する。

    Parameters
    ----------
    personal_cfg : dict
        load_personal_config() の戻り値。
    ref_date : datetime.date
        基準日。

    Returns
    -------
    int
        最大心拍数 (bpm)。
    """
    hr_zones_cfg = personal_cfg.get('hr_zones', {})
    override = hr_zones_cfg.get('max_hr_override')
    if override is not None and override != '':
        return int(override)

    # Tanaka 推定式: 208 - 0.7 × age
    birth_date = personal_cfg.get('birth_date')
    if isinstance(birth_date, str):
        birth_date = datetime.date.fromisoformat(birth_date)
    age = calc_age(birth_date, ref_date)
    return round(208 - 0.7 * age)


def calc_resting_hr(df_hr_daily, ref_date, window_days, fallback):
    """安静時心拍数を算出する。

    直近 window_days 日間の中央値を返す。

    Parameters
    ----------
    df_hr_daily : pd.DataFrame
        heart_rate.csv を読んだ DataFrame。列: date, resting_heart_rate。
        未ソート・欠損あり前提。
    ref_date : datetime.date
        ウィンドウの終了日（基準日）。
    window_days : int
        ウィンドウサイズ（日数）。
    fallback : float or int
        ウィンドウ内にデータが無い場合の代替値。

    Returns
    -------
    float
        安静時心拍数 (bpm)。
    """
    df = df_hr_daily.copy()
    df['date'] = pd.to_datetime(df['date'])

    ref_ts = pd.Timestamp(ref_date)
    window_start = ref_ts - pd.Timedelta(days=window_days - 1)

    mask = (df['date'] >= window_start) & (df['date'] <= ref_ts)
    df_window = df[mask]

    rhr_series = pd.to_numeric(df_window['resting_heart_rate'], errors='coerce').dropna()

    if len(rhr_series) == 0:
        return float(fallback)

    return float(rhr_series.median())


def compute_zone_bounds(max_hr, resting_hr, method='hrr'):
    """心拍ゾーンの下限境界を算出する。

    Parameters
    ----------
    max_hr : int
        最大心拍数 (bpm)。
    resting_hr : float
        安静時心拍数 (bpm)。
    method : str
        ゾーン算出方法（現在は 'hrr' のみ対応）。

    Returns
    -------
    dict
        各ゾーンの下限値 {'Z1': float, 'Z2': float, ..., 'Z5': float}。
    """
    thresholds = ZONE_THRESHOLDS[method]
    hrr = max_hr - resting_hr

    bounds = {}
    for zone in ZONE_NAMES:
        k = thresholds[zone]
        bounds[zone] = resting_hr + k * hrr

    # 下限が単調増加であることを検証
    prev = None
    for zone in ZONE_NAMES:
        if prev is not None:
            assert bounds[zone] > prev, f"ゾーン境界が単調増加ではありません: {bounds}"
        prev = bounds[zone]

    return bounds


def classify_hr(bpm, bounds):
    """心拍数をゾーンに分類する。

    Parameters
    ----------
    bpm : float or int
        心拍数 (bpm)。
    bounds : dict
        compute_zone_bounds() の戻り値。

    Returns
    -------
    str or None
        ゾーン名 ('Z1'〜'Z5')。Z1未満の場合は None。
    """
    if bpm < bounds['Z1']:
        return None

    # 最上位ゾーンから順に判定
    for zone in reversed(ZONE_NAMES):
        if bpm >= bounds[zone]:
            return zone

    return None


def calc_daily_zone_minutes(df_hr_intraday, bounds):
    """1分データから日別ゾーン分数を集計する。

    Parameters
    ----------
    df_hr_intraday : pd.DataFrame
        index=datetime (parse_dates)、列 heart_rate。1行=1分。
    bounds : dict
        compute_zone_bounds() の戻り値。

    Returns
    -------
    pd.DataFrame
        index=正規化日付(pd.Timestamp)、列 z1_min, z2_min, z3_min, z4_min, z5_min (int)、
        total_zone_min (int)。
    """
    df = df_hr_intraday.copy()
    df['bpm'] = pd.to_numeric(df['heart_rate'], errors='coerce')
    df['zone'] = df['bpm'].apply(lambda x: classify_hr(x, bounds) if pd.notna(x) else None)
    df['date'] = df.index.normalize()

    result_rows = []
    for date, group in df.groupby('date'):
        row = {'date': date}
        for z in ZONE_NAMES:
            col = z.lower() + '_min'
            row[col] = int((group['zone'] == z).sum())
        row['total_zone_min'] = sum(row[z.lower() + '_min'] for z in ZONE_NAMES)
        result_rows.append(row)

    if not result_rows:
        return pd.DataFrame(columns=['z1_min', 'z2_min', 'z3_min', 'z4_min', 'z5_min', 'total_zone_min'])

    df_result = pd.DataFrame(result_rows).set_index('date')
    return df_result


def prepare_hr_zone_daily_data(start_date, end_date, df_hr_intraday, df_hr_daily, personal_cfg):
    """心拍ゾーン日別データを準備する。

    Parameters
    ----------
    start_date : datetime.date or str
        レポート開始日。
    end_date : datetime.date or str
        レポート終了日（ref_date として使用）。
    df_hr_intraday : pd.DataFrame
        heart_rate_intraday.csv を読んだ DataFrame（index=datetime）。
    df_hr_daily : pd.DataFrame
        heart_rate.csv を読んだ DataFrame（列: date, resting_heart_rate）。
    personal_cfg : dict
        load_personal_config() の戻り値。

    Returns
    -------
    tuple[list[dict], dict]
        (daily_list, meta)
        daily_list: 各日の dict リスト
        meta: max_hr, resting_hr, age, method, hrr, bounds, window_days
    """
    if isinstance(end_date, str):
        end_date = datetime.date.fromisoformat(end_date)
    if isinstance(start_date, str):
        start_date = datetime.date.fromisoformat(start_date)

    hr_zones_cfg = personal_cfg.get('hr_zones', {})
    resting_hr_cfg = hr_zones_cfg.get('resting_hr', {})
    window_days = resting_hr_cfg.get('window_days', 30)
    fallback = resting_hr_cfg.get('fallback', 48)
    method = hr_zones_cfg.get('method', 'hrr')

    birth_date = personal_cfg.get('birth_date')
    if isinstance(birth_date, str):
        birth_date = datetime.date.fromisoformat(birth_date)

    # end_date を ref_date として算出（レポート1回=1組の境界）
    max_hr = calc_max_hr(personal_cfg, end_date)
    resting_hr = calc_resting_hr(df_hr_daily, end_date, window_days, fallback)
    age = calc_age(birth_date, end_date)
    bounds = compute_zone_bounds(max_hr, resting_hr, method)
    hrr = float(max_hr - resting_hr)

    # 日別ゾーン集計
    df_zone = calc_daily_zone_minutes(df_hr_intraday, bounds)

    # 全日付を列挙
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
    daily_list = []

    for date in all_dates:
        row = {'date': date}
        if date in df_zone.index:
            row['z1_min'] = int(df_zone.loc[date, 'z1_min'])
            row['z2_min'] = int(df_zone.loc[date, 'z2_min'])
            row['z3_min'] = int(df_zone.loc[date, 'z3_min'])
            row['z4_min'] = int(df_zone.loc[date, 'z4_min'])
            row['z5_min'] = int(df_zone.loc[date, 'z5_min'])
            row['total_zone_min'] = int(df_zone.loc[date, 'total_zone_min'])
        else:
            row['z1_min'] = None
            row['z2_min'] = None
            row['z3_min'] = None
            row['z4_min'] = None
            row['z5_min'] = None
            row['total_zone_min'] = None
        daily_list.append(row)

    meta = {
        'max_hr': max_hr,
        'resting_hr': resting_hr,
        'age': age,
        'method': method,
        'hrr': hrr,
        'bounds': bounds,
        'window_days': window_days,
    }

    return daily_list, meta


if __name__ == '__main__':
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    print(f"Repo root: {repo_root}")

    # データロード
    hr_intraday_path = repo_root / 'data' / 'fitbit' / 'heart_rate_intraday.csv'
    hr_daily_path = repo_root / 'data' / 'fitbit' / 'heart_rate.csv'

    df_hr_intraday = pd.read_csv(hr_intraday_path, index_col='datetime', parse_dates=True)
    df_hr_daily = pd.read_csv(hr_daily_path)

    personal_cfg = load_personal_config()
    print(f"personal_cfg loaded: birth_date={personal_cfg.get('birth_date')}")

    # 直近7日
    today = datetime.date.today()
    end_date = today
    start_date = today - datetime.timedelta(days=6)

    print(f"Period: {start_date} ~ {end_date}")

    daily_list, meta = prepare_hr_zone_daily_data(start_date, end_date, df_hr_intraday, df_hr_daily, personal_cfg)

    print(f"\nMeta:")
    for k, v in meta.items():
        print(f"  {k}: {v}")

    print(f"\nDaily data:")
    for day in daily_list:
        print(f"  {day}")

    # アサーション: bounds が厳密単調増加
    bounds = meta['bounds']
    resting_hr = meta['resting_hr']
    max_hr = meta['max_hr']

    prev_val = None
    for zone in ZONE_NAMES:
        val = bounds[zone]
        if prev_val is not None:
            assert val > prev_val, f"bounds not strictly monotone: {bounds}"
        prev_val = val

    # resting_hr < Z1 < Z2 < Z3 < Z4 < Z5 < max_hr
    assert resting_hr < bounds['Z1'], f"resting_hr({resting_hr}) >= Z1({bounds['Z1']})"
    assert bounds['Z5'] < max_hr, f"Z5({bounds['Z5']}) >= max_hr({max_hr})"

    print("\nSMOKE OK")
