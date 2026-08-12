"""Open-Meteo 気象データ取得クライアント

認証不要・無料で過去データを遡って取得できる。
時別データを取得し、日次集計と夜間帯集計は呼び出し側で行う。

- Archive API: 確定値。ただし直近数日は未反映
- Forecast API: past_days で直近を補完
"""

import datetime as dt
import logging

import pandas as pd
import requests

logger = logging.getLogger(__name__)

ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'

# Archive API に反映されるまでの遅延日数。これより新しい日は Forecast API で補完する
ARCHIVE_DELAY_DAYS = 6

# Forecast API の past_days 上限
FORECAST_MAX_PAST_DAYS = 92

HOURLY_VARS = ['temperature_2m', 'relative_humidity_2m', 'pressure_msl', 'precipitation']

REQUEST_TIMEOUT = 60


def _request_hourly(url: str, params: dict) -> pd.DataFrame:
    """Open-Meteo に時別データをリクエストして DataFrame 化"""
    params = {**params, 'hourly': ','.join(HOURLY_VARS)}
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    hourly = response.json()['hourly']

    df = pd.DataFrame(hourly)
    df['time'] = pd.to_datetime(df['time'])
    return df.set_index('time').sort_index()


def fetch_hourly(start_date: dt.date, end_date: dt.date, location: dict) -> pd.DataFrame:
    """指定期間の時別気象データを取得

    Archive API と Forecast API を期間で使い分け、結合して返す。

    Parameters
    ----------
    start_date, end_date : datetime.date
        取得期間（両端を含む）
    location : dict
        latitude / longitude / timezone を持つ辞書

    Returns
    -------
    pd.DataFrame
        index=現地時刻の時別データ。列は HOURLY_VARS
    """
    base_params = {
        'latitude': location['latitude'],
        'longitude': location['longitude'],
        'timezone': location['timezone'],
    }

    archive_end = min(end_date, dt.date.today() - dt.timedelta(days=ARCHIVE_DELAY_DAYS))
    frames = []

    if start_date <= archive_end:
        logger.info("Archive API: %s ～ %s", start_date, archive_end)
        frames.append(_request_hourly(ARCHIVE_URL, {
            **base_params,
            'start_date': start_date.isoformat(),
            'end_date': archive_end.isoformat(),
        }))

    # Archive が届かない直近を Forecast API の past_days で補完
    recent_start = max(start_date, archive_end + dt.timedelta(days=1))
    if recent_start <= end_date:
        past_days = (dt.date.today() - recent_start).days + 1
        if past_days > FORECAST_MAX_PAST_DAYS:
            raise ValueError(
                f"Forecast API の past_days 上限({FORECAST_MAX_PAST_DAYS}日)を超過: {past_days}日"
            )
        logger.info("Forecast API: %s ～ %s (past_days=%d)", recent_start, end_date, past_days)
        df_recent = _request_hourly(FORECAST_URL, {
            **base_params,
            'past_days': max(past_days, 0),
            'forecast_days': 1,
        })
        frames.append(df_recent.loc[str(recent_start):str(end_date)])

    if not frames:
        raise ValueError(f"取得対象期間が空です: {start_date} ～ {end_date}")

    df = pd.concat(frames)
    return df[~df.index.duplicated(keep='first')].sort_index()
