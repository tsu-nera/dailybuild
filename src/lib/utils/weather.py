"""気象データの日次・夜間帯集計

Open-Meteo の時別データを、睡眠指標と突合できる日次1行に畳む。

夜間帯の定義: date D の行が持つ夜間値は「D-1 の night_start 時 ～ D の night_end 時」。
Fitbit の dateOfSleep が起床日を指すため、同じ date で join できる。
"""

import pandas as pd

DEFAULT_NIGHT_START_HOUR = 22
DEFAULT_NIGHT_END_HOUR = 6


def _night_date(index: pd.DatetimeIndex, night_start_hour: int) -> pd.Series:
    """各時刻が属する夜間帯の「起床日」を返す

    night_start_hour 以降は翌日の夜間帯に属する。
    """
    dates = index.normalize()
    is_evening = index.hour >= night_start_hour
    return pd.Series(dates + pd.to_timedelta(is_evening.astype(int), unit='D'), index=index)


def aggregate_daily(df_hourly: pd.DataFrame,
                    night_start_hour: int = DEFAULT_NIGHT_START_HOUR,
                    night_end_hour: int = DEFAULT_NIGHT_END_HOUR) -> pd.DataFrame:
    """時別データを日次1行に集計

    Parameters
    ----------
    df_hourly : pd.DataFrame
        index=現地時刻、列は temperature_2m / relative_humidity_2m / pressure_msl / precipitation
    night_start_hour, night_end_hour : int
        夜間帯の開始・終了時刻（時）

    Returns
    -------
    pd.DataFrame
        index=date。日中含む終日集計と夜間帯集計を持つ
    """
    by_day = df_hourly.groupby(df_hourly.index.normalize())
    daily = pd.DataFrame({
        'temp_mean': by_day['temperature_2m'].mean(),
        'temp_max': by_day['temperature_2m'].max(),
        'temp_min': by_day['temperature_2m'].min(),
        'humidity_mean': by_day['relative_humidity_2m'].mean(),
        'pressure_mean': by_day['pressure_msl'].mean(),
        'pressure_min': by_day['pressure_msl'].min(),
        'precipitation_sum': by_day['precipitation'].sum(),
    })

    in_night = (df_hourly.index.hour >= night_start_hour) | (df_hourly.index.hour < night_end_hour)
    df_night = df_hourly[in_night]
    by_night = df_night.groupby(_night_date(df_night.index, night_start_hour))
    night = pd.DataFrame({
        'temp_night_mean': by_night['temperature_2m'].mean(),
        'temp_night_max': by_night['temperature_2m'].max(),
        'temp_night_min': by_night['temperature_2m'].min(),
        'humidity_night_mean': by_night['relative_humidity_2m'].mean(),
    })

    df = daily.join(night, how='outer')
    # 前日からの気圧変化。急変が体調に効くという仮説の検証用
    df['pressure_delta'] = df['pressure_mean'].diff()

    df.index.name = 'date'
    return df.round(2)
