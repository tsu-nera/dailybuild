"""
push 用のソース実装

各ソースは「(source, since, until, config, tz) -> list[Interval]」の形の
関数を提供するだけでよい。Toggl への書き込み・冪等性・レート制御は push.py に
集約している。このIssueで実装するのは睡眠のみ（運動は保留）。
"""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from lib.toggl.push import Interval

BASE_DIR = Path(__file__).resolve().parents[3]
SLEEP_CSV_FILE = BASE_DIR / 'data' / 'fitbit' / 'sleep.csv'


def fitbit_sleep_intervals(
    since: dt.date, until: dt.date, config: dict, tz: ZoneInfo,
) -> list[Interval]:
    """data/fitbit/sleep.csv から [since, until] のInterval列を作る

    昼寝（isMainSleep=False）も含める。startTime/endTimeはnaiveなJSTローカル時刻
    なので、UTC解釈にならないようtzを明示付与する。
    """
    source_config = config.get('sources', {}).get('fitbit_sleep', {})
    if not source_config.get('enabled', False):
        return []

    if not SLEEP_CSV_FILE.exists():
        raise FileNotFoundError(f"{SLEEP_CSV_FILE} が存在しない。睡眠データを取得してから実行すること")

    df = pd.read_csv(SLEEP_CSV_FILE, dtype={'logId': str})
    if df.empty:
        return []

    df['dateOfSleep'] = pd.to_datetime(df['dateOfSleep']).dt.date
    df = df[(df['dateOfSleep'] >= since) & (df['dateOfSleep'] <= until)]

    description = source_config.get('description', '')
    project = source_config.get('project', '')
    tags = tuple(source_config.get('tags', []))

    intervals = []
    for _, row in df.iterrows():
        start = dt.datetime.fromisoformat(row['startTime']).replace(tzinfo=tz)
        stop = dt.datetime.fromisoformat(row['endTime']).replace(tzinfo=tz)
        intervals.append(Interval(
            source='fitbit_sleep',
            source_id=str(row['logId']),
            start=start,
            stop=stop,
            description=description,
            project=project,
            tags=tags,
        ))
    return intervals


SOURCES = {
    'fitbit_sleep': fitbit_sleep_intervals,
}
