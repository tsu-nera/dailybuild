"""
push 用のソース実装

各ソースは「(since, until, config, tz) -> list[Interval]」の形の
関数を提供するだけでよい。Toggl への書き込み・冪等性・レート制御は push.py に
集約している。
"""

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from lib import exercise_source
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


def _resolve_categories(config: dict) -> dict[str, dict]:
    """exerciseType -> カテゴリ設定 の対応表を作る"""
    mapping = {}
    for name, category in (config.get('categories') or {}).items():
        for exercise_type in category.get('exercise_types', []):
            mapping[exercise_type] = {'name': name, **category}
    return mapping


def googlehealth_exercise_intervals(
    since: dt.date, until: dt.date, config: dict, tz: ZoneInfo,
) -> list[Interval]:
    """data/googlehealth/exercise.csv から [since, until] のInterval列を作る

    yaml の categories に載っている exerciseType だけを投入する
    （WALKING / RUNNING 等は対象外）。platform の重複解決は
    exercise_source.load_sessions が行う（カテゴリ絞り込みより先。
    push とレポートが同じ集合を見るようにするため）。
    load_sessions はtz-naiveなJST壁時計時刻を返すので、Toggl投入用に
    tz を明示付与する。
    """
    source_config = config.get('sources', {}).get('googlehealth_exercise', {})
    if not source_config.get('enabled', False):
        return []

    if not exercise_source.EXERCISE_CSV_FILE.exists():
        raise FileNotFoundError(
            f"{exercise_source.EXERCISE_CSV_FILE} が存在しない。"
            "uv run scripts/fetch_googlehealth.py --endpoint exercise を先に実行すること"
        )

    df = exercise_source.load_sessions(since, until)
    if df is None:
        return []

    categories = _resolve_categories(source_config)
    df = df[df['exercise_type'].isin(categories)]

    rows = [
        {
            'id': str(row['id']),
            'start': row['start'].to_pydatetime().replace(tzinfo=tz),
            'stop': row['end'].to_pydatetime().replace(tzinfo=tz),
            'category': categories[row['exercise_type']],
        }
        for _, row in df.iterrows()
    ]

    return [
        Interval(
            source='googlehealth_exercise',
            source_id=row['id'],
            start=row['start'],
            stop=row['stop'],
            description=row['category'].get('description', ''),
            project=row['category'].get('project', ''),
            tags=tuple(row['category'].get('tags', [])),
        )
        for row in rows
    ]


SOURCES = {
    'fitbit_sleep': fitbit_sleep_intervals,
    'googlehealth_exercise': googlehealth_exercise_intervals,
}
