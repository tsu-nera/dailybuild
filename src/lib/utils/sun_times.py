"""日出・日入時刻計算ユーティリティ"""

from astral import Observer
from astral.sun import sunrise, sunset
import datetime
import zoneinfo
import json
from pathlib import Path

DEFAULT_LOCATION = {
    "name": "Tokyo",
    "latitude": 35.6762,
    "longitude": 139.6503,
    "timezone": "Asia/Tokyo"
}

def load_location_config():
    """設定ファイルから位置情報を読み込み"""
    config_path = Path(__file__).resolve().parents[4] / 'config' / 'location.json'
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return DEFAULT_LOCATION

def get_sun_times(date, location=None):
    """
    指定日の日出・日入時刻を計算

    Parameters
    ----------
    date : datetime.date or str
        対象日
    location : dict, optional
        位置情報（latitude, longitude, timezone）

    Returns
    -------
    dict : {'sunrise': 'HH:MM', 'sunset': 'HH:MM'}
    """
    if location is None:
        location = load_location_config()

    if isinstance(date, str):
        date = datetime.datetime.strptime(date, '%Y-%m-%d').date()

    observer = Observer(
        latitude=location['latitude'],
        longitude=location['longitude'],
        elevation=0
    )
    tz = zoneinfo.ZoneInfo(location['timezone'])

    sunrise_time = sunrise(observer, date, tzinfo=tz)
    sunset_time = sunset(observer, date, tzinfo=tz)

    return {
        'sunrise': sunrise_time.strftime('%H:%M'),
        'sunset': sunset_time.strftime('%H:%M')
    }
