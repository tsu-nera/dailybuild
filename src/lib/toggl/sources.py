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

from lib.toggl.push import Interval

BASE_DIR = Path(__file__).resolve().parents[3]
SLEEP_CSV_FILE = BASE_DIR / 'data' / 'fitbit' / 'sleep.csv'
EXERCISE_CSV_FILE = BASE_DIR / 'data' / 'googlehealth' / 'exercise.csv'


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


def _dedup_by_platform(rows: list[dict], priority: list[str],
                       threshold_sec: int) -> list[dict]:
    """時間が重なるセッションを platform の優先順で1本に畳む

    同じ運動が Fitbit（Charge 6）と Health Connect（Google Fit / Hevy）の
    両方から別セッションとして届く。素通しすると Toggl に同じ運動が
    2本入るため、重なったら優先度の高い platform 側だけを残す。
    優先度は「重なりの解決」にのみ使う。重なっていないものは platform に
    関係なく残す（Fitbit を外したときに Health Connect 側で穴が埋まる）。
    """
    def rank(row):
        platform = row.get('platform')
        return priority.index(platform) if platform in priority else len(priority)

    # 優先度が高い順に採用し、既に採ったものと重なるセッションを落とす
    kept: list[dict] = []
    for row in sorted(rows, key=lambda r: (rank(r), r['start'])):
        overlaps = any(
            (min(row['stop'], k['stop']) - max(row['start'], k['start'])).total_seconds()
            > threshold_sec
            for k in kept
        )
        if not overlaps:
            kept.append(row)
    return sorted(kept, key=lambda r: r['start'])


def googlehealth_exercise_intervals(
    since: dt.date, until: dt.date, config: dict, tz: ZoneInfo,
) -> list[Interval]:
    """data/googlehealth/exercise.csv から [since, until] のInterval列を作る

    yaml の categories に載っている exerciseType だけを投入する
    （WALKING / RUNNING 等は対象外）。start/end は取得時に
    +09:00 付きで書いてあるので tz の付与は不要。
    """
    source_config = config.get('sources', {}).get('googlehealth_exercise', {})
    if not source_config.get('enabled', False):
        return []

    if not EXERCISE_CSV_FILE.exists():
        raise FileNotFoundError(
            f"{EXERCISE_CSV_FILE} が存在しない。"
            "uv run scripts/fetch_googlehealth.py --endpoint exercise を先に実行すること"
        )

    df = pd.read_csv(EXERCISE_CSV_FILE, dtype={'id': str})
    if df.empty:
        return []

    categories = _resolve_categories(source_config)
    df = df[df['exercise_type'].isin(categories)]

    rows = []
    for _, row in df.iterrows():
        start = dt.datetime.fromisoformat(row['start'])
        if not (since <= start.date() <= until):
            continue
        rows.append({
            'id': str(row['id']),
            'start': start,
            'stop': dt.datetime.fromisoformat(row['end']),
            'platform': row.get('platform'),
            'category': categories[row['exercise_type']],
        })

    rows = _dedup_by_platform(
        rows,
        list(source_config.get('platform_priority') or []),
        int(source_config.get('overlap_threshold_sec', 60)),
    )

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
