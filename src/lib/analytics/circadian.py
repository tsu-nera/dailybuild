"""
Circadian Rhythm Analysis Module

論文: "Circadian rhythm of heart rate and activity: A cross-sectional study" (2025)
      Chronobiology International, 42:1, 108-121

2調和フーリエモデルを使用してFitbit心拍数データからサーカディアンリズムを抽出する。
"""

import pandas as pd
import numpy as np
from scipy.optimize import curve_fit
from typing import Optional, Dict, Tuple


def two_harmonic_model(t: np.ndarray, mu: float, A1: float, phi1: float,
                      A2: float, phi2: float) -> np.ndarray:
    """
    2調和フーリエモデル（論文 Equation 1, p.110）

    CR(t) = μ + A₁·sin(2πt/24hr + φ₁) + A₂·sin(2πt/12hr + φ₂)

    Parameters
    ----------
    t : np.ndarray
        時刻（0-23の整数、時間単位）
    mu : float
        24時間の平均心拍数 (bpm)
    A1 : float
        第1調和の振幅（24時間周期） (bpm)
    phi1 : float
        第1調和の位相（ラジアン）
    A2 : float
        第2調和の振幅（12時間周期） (bpm)
    phi2 : float
        第2調和の位相（ラジアン）

    Returns
    -------
    np.ndarray
        予測心拍数 (bpm)
    """
    return (mu +
            A1 * np.sin(2 * np.pi * t / 24 + phi1) +
            A2 * np.sin(2 * np.pi * t / 12 + phi2))


def exclude_sleep_periods(hr_df: pd.DataFrame, sleep_df: pd.DataFrame) -> pd.DataFrame:
    """
    心拍数データから睡眠時間帯を除外

    Parameters
    ----------
    hr_df : pd.DataFrame
        心拍数データ（datetimeインデックス、'heart_rate'列）
    sleep_df : pd.DataFrame
        睡眠データ（'startTime', 'endTime'列）

    Returns
    -------
    pd.DataFrame
        睡眠時間除外後の心拍数データ
    """
    hr_awake = hr_df.copy()

    # 睡眠時刻でフィルタリング
    for _, sleep in sleep_df.iterrows():
        start_time = pd.to_datetime(sleep['startTime'])
        end_time = pd.to_datetime(sleep['endTime'])

        # 睡眠時間帯のデータをマスク
        mask = (hr_awake.index >= start_time) & (hr_awake.index <= end_time)
        hr_awake = hr_awake[~mask]

    return hr_awake


def prepare_hourly_data(hr_df: pd.DataFrame, sleep_df: Optional[pd.DataFrame] = None) -> np.ndarray:
    """
    論文の手法に従って、30日間のデータから1時間ごとの平均心拍数を計算

    Parameters
    ----------
    hr_df : pd.DataFrame
        心拍数Intradayデータ（datetimeインデックス、'heart_rate'列）
    sleep_df : pd.DataFrame, optional
        睡眠データ（睡眠中のデータ除外用）

    Returns
    -------
    np.ndarray
        24個の1時間平均心拍数（0時〜23時）
    """
    # 睡眠中のデータを除外
    if sleep_df is not None:
        hr_awake = exclude_sleep_periods(hr_df, sleep_df)
    else:
        hr_awake = hr_df.copy()

    # 1時間ごとの平均を計算
    hourly_means = []
    for hour in range(24):
        hour_data = hr_awake[hr_awake.index.hour == hour]
        if len(hour_data) > 0:
            hourly_means.append(hour_data['heart_rate'].mean())
        else:
            hourly_means.append(np.nan)

    return np.array(hourly_means)


def fit_circadian_rhythm(hourly_hr: np.ndarray) -> Dict[str, float]:
    """
    2調和フーリエモデルをフィッティングしてサーカディアンパラメータを抽出

    Parameters
    ----------
    hourly_hr : np.ndarray
        24個の1時間平均心拍数（0時〜23時）

    Returns
    -------
    dict
        サーカディアンパラメータ:
        - mu: 24時間平均心拍数 (bpm)
        - A1: 第1調和の振幅 (bpm)
        - phi1: 第1調和の位相 (rad)
        - A2: 第2調和の振幅 (bpm)
        - phi2: 第2調和の位相 (rad)
        - A_CR: サーカディアン振幅 (bpm)
        - bathyphase: 心拍数最低時刻 (hour)
        - acrophase: 心拍数最高時刻 (hour)
        - r_squared: 決定係数
        - A2_A1_ratio: A₂/A₁比率
        - variance_1st_pct: 第1調和の分散説明率 (%)
    """
    t = np.arange(24)
    valid_mask = ~np.isnan(hourly_hr)
    t_valid = t[valid_mask]
    y_valid = hourly_hr[valid_mask]

    # 初期値推定
    mu_init = np.nanmean(hourly_hr)
    A1_init = (np.nanmax(hourly_hr) - np.nanmin(hourly_hr)) / 2
    phi1_init = 0.0
    A2_init = A1_init / 4  # 第2調和は第1調和より小さい
    phi2_init = 0.0
    p0 = [mu_init, A1_init, phi1_init, A2_init, phi2_init]

    # フィッティング
    popt, pcov = curve_fit(two_harmonic_model, t_valid, y_valid, p0=p0)
    mu, A1, phi1, A2, phi2 = popt

    # サーカディアン振幅（Equation 4）
    A_CR = np.sqrt(A1**2 + A2**2)

    # Bathyphase & Acrophase（数値的に計算）
    t_fine = np.linspace(0, 24, 1000)
    hr_curve = two_harmonic_model(t_fine, *popt)
    bathyphase = t_fine[np.argmin(hr_curve)]
    acrophase = t_fine[np.argmax(hr_curve)]

    # 統計量（R²）
    fitted = two_harmonic_model(t_valid, *popt)
    ss_total = np.sum((y_valid - np.mean(y_valid))**2)
    ss_residual = np.sum((y_valid - fitted)**2)
    r_squared = 1 - (ss_residual / ss_total)

    # 第1調和のみの分散説明率
    fitted_1st_only = mu + A1 * np.sin(2 * np.pi * t_valid / 24 + phi1)
    ss_1st = np.sum((fitted_1st_only - mu)**2)
    variance_1st_pct = (ss_1st / ss_total) * 100

    return {
        'mu': mu,
        'A1': A1,
        'phi1': phi1,
        'A2': A2,
        'phi2': phi2,
        'A_CR': A_CR,
        'bathyphase': bathyphase,
        'acrophase': acrophase,
        'r_squared': r_squared,
        'A2_A1_ratio': A2 / A1 if A1 != 0 else np.nan,
        'variance_1st_pct': variance_1st_pct,
    }


def analyze_circadian_rhythm(
    hr_intraday_file: str,
    sleep_file: str,
    output_dir: Optional[str] = None
) -> Tuple[Dict[str, float], np.ndarray, np.ndarray]:
    """
    Fitbit Intradayデータからサーカディアンリズムを分析

    Parameters
    ----------
    hr_intraday_file : str
        心拍数Intradayデータのパス（CSV）
    sleep_file : str
        睡眠データのパス（CSV）
    output_dir : str, optional
        出力ディレクトリ（可視化画像保存用）

    Returns
    -------
    tuple
        (パラメータ辞書, 1時間平均心拍数, フィッティング曲線)
    """
    # データ読み込み
    hr_df = pd.read_csv(hr_intraday_file, index_col='datetime', parse_dates=True)
    sleep_df = pd.read_csv(sleep_file, parse_dates=['startTime', 'endTime'])

    # 1時間ごとの平均を計算
    hourly_hr = prepare_hourly_data(hr_df, sleep_df)

    # 2調和フーリエモデルでフィッティング
    params = fit_circadian_rhythm(hourly_hr)

    # フィッティング曲線を生成
    t_fine = np.linspace(0, 24, 1000)
    hr_fitted = two_harmonic_model(t_fine, params['mu'], params['A1'],
                                   params['phi1'], params['A2'], params['phi2'])

    return params, hourly_hr, (t_fine, hr_fitted)


def format_time(hour: float) -> str:
    """
    時刻を HH:MM 形式に変換

    Parameters
    ----------
    hour : float
        時刻（0-24の実数）

    Returns
    -------
    str
        HH:MM 形式の時刻
    """
    h = int(hour)
    m = int((hour - h) * 60)
    return f"{h:02d}:{m:02d}"


def load_activity_periods(activity_logs_file: str) -> list:
    """
    activity_logsから運動時間帯を抽出

    Parameters
    ----------
    activity_logs_file : str
        activity_logs.csvのパス

    Returns
    -------
    list of tuple
        [(start_time, end_time), ...] の運動時間帯リスト
    """
    activity_df = pd.read_csv(activity_logs_file)

    # startTimeをパース
    activity_df['startTime'] = pd.to_datetime(
        activity_df['startTime'], format='ISO8601'
    ).dt.tz_localize(None)

    activity_periods = []
    for _, row in activity_df.iterrows():
        start_time = row['startTime']
        duration_minutes = row['durationMinutes']
        end_time = start_time + pd.Timedelta(minutes=duration_minutes)

        activity_periods.append((start_time, end_time))

    return activity_periods


def exclude_activity_periods(hr_df: pd.DataFrame, activity_periods: list) -> pd.DataFrame:
    """
    心拍数データから運動時間帯を除外

    Parameters
    ----------
    hr_df : pd.DataFrame
        心拍数データ（datetimeインデックス、'heart_rate'列）
    activity_periods : list of tuple
        [(start_time, end_time), ...] の運動時間帯リスト

    Returns
    -------
    pd.DataFrame
        運動時間除外後の心拍数データ
    """
    hr_filtered = hr_df.copy()

    # 各運動時間帯を除外
    for start_time, end_time in activity_periods:
        mask = (hr_filtered.index >= start_time) & (hr_filtered.index <= end_time)
        hr_filtered = hr_filtered[~mask]

    return hr_filtered


def prepare_hourly_data_with_interval(
    hr_df: pd.DataFrame,
    interval_minutes: int = 60,
    sleep_df: Optional[pd.DataFrame] = None
) -> pd.DataFrame:
    """
    心拍数データを指定間隔で集約

    Parameters
    ----------
    hr_df : pd.DataFrame
        心拍数データ（datetimeインデックス、'heart_rate'列）
    interval_minutes : int
        集約する時間間隔（分）デフォルトは60分
    sleep_df : pd.DataFrame, optional
        睡眠データ（睡眠中のデータ除外用）

    Returns
    -------
    pd.DataFrame
        時刻と平均心拍数（columns: ['time_decimal', 'heart_rate']）
    """
    # 睡眠中のデータを除外
    if sleep_df is not None:
        hr_data = exclude_sleep_periods(hr_df, sleep_df)
    else:
        hr_data = hr_df.copy()

    # 時刻を抽出
    hr_data = hr_data.copy()
    hr_data['time_decimal'] = (
        hr_data.index.hour +
        hr_data.index.minute / 60.0
    )

    # 指定間隔に丸める
    hr_data['time_bin'] = (
        hr_data['time_decimal'] * (60 / interval_minutes)
    ).round() / (60 / interval_minutes)

    # 同じ時刻のデータを平均化（30日分の同じ時刻を平均）
    hr_aggregated = hr_data.groupby('time_bin')['heart_rate'].mean().reset_index()
    hr_aggregated.columns = ['time_decimal', 'heart_rate']

    # 時刻順にソート
    hr_aggregated = hr_aggregated.sort_values('time_decimal').reset_index(drop=True)

    return hr_aggregated


def interpret_results(params: Dict[str, float], sleep_df: pd.DataFrame) -> Dict[str, str]:
    """
    分析結果を解釈して文章で返す

    Parameters
    ----------
    params : dict
        サーカディアンパラメータ
    sleep_df : pd.DataFrame
        睡眠データ

    Returns
    -------
    dict
        解釈テキスト
    """
    # 平均起床時刻を計算
    sleep_df['endTime_dt'] = pd.to_datetime(sleep_df['endTime'])
    avg_wake_time = sleep_df['endTime_dt'].dt.hour.mean() + sleep_df['endTime_dt'].dt.minute.mean() / 60

    # 平均就寝時刻を計算
    sleep_df['startTime_dt'] = pd.to_datetime(sleep_df['startTime'])
    avg_bedtime = sleep_df['startTime_dt'].dt.hour.mean() + sleep_df['startTime_dt'].dt.minute.mean() / 60

    # Bathyphaseと起床時刻の差
    bathyphase_wake_diff = avg_wake_time - params['bathyphase']
    if bathyphase_wake_diff < 0:
        bathyphase_wake_diff += 24

    # Acrophaseと就寝時刻の差
    acrophase_bedtime_diff = avg_bedtime - params['acrophase']
    if acrophase_bedtime_diff < 0:
        acrophase_bedtime_diff += 24

    interpretations = {
        'amplitude': f"サーカディアン振幅は {params['A_CR']:.1f} bpm です。",
        'bathyphase': f"心拍数が最低になる時刻は {format_time(params['bathyphase'])} で、起床時刻の約 {bathyphase_wake_diff:.1f} 時間前です。",
        'acrophase': f"心拍数が最高になる時刻は {format_time(params['acrophase'])} で、就寝時刻の約 {acrophase_bedtime_diff:.1f} 時間前です。",
        'quality': f"モデルの決定係数（R²）は {params['r_squared']:.3f} で、{'非常に良好' if params['r_squared'] > 0.95 else '良好' if params['r_squared'] > 0.85 else '要検討'}です。",
        'ultradian': f"ウルトラディアンリズム指標（A₂/A₁）は {params['A2_A1_ratio']:.3f} で、{'ウルトラディアンリズムが支配的' if params['A2_A1_ratio'] > 1.0 else '正常範囲'}です。",
    }

    return interpretations
