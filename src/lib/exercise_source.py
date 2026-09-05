#!/usr/bin/env python
# coding: utf-8
"""
data/googlehealth/exercise.csv の共通ローダー

Toggl push（lib/toggl/sources.py）とレポート（lib/analytics/activity.py,
lib/analytics/circadian.py 等）の両方がここを経由する。exercise.csv は
Fitbit（Charge 6）と Health Connect（Google Fit / Hevy）の両方から
セッションが届き、同じ運動がほぼ同じ時間帯で二重に記録されることがある
（2026年実測で74組）。

platform の優先度と重なり判定の閾値は「2つのプラットフォームがどう重なるか」
というデータの性質であって、consumer（push / レポート）ごとに変えてよい
チューニングではない。yaml で consumer 別にキーを持たせると、片方だけ
ずれても誰も気づけないため、モジュール定数として一箇所に固定する。
"""

from pathlib import Path

import pandas as pd

from lib.utils.private_data import require_private_path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXERCISE_CSV_FILE = require_private_path(REPO_ROOT / 'data' / 'googlehealth' / 'exercise.csv')

# 重なりの解決にのみ使う優先度。重なっていないセッションは platform に
# 関係なく残す（Fitbit を外したときに Health Connect 側で穴が埋まる）
PLATFORM_PRIORITY = ('FITBIT', 'HEALTH_CONNECT')
# この秒数を超えて重なったら同一セッションとみなす
OVERLAP_THRESHOLD_SEC = 60

CYCLING_TYPES = ('OUTDOOR_BIKE', 'BIKING', 'SPINNING')
STRENGTH_TYPES = (
    'WEIGHTS', 'STRENGTH_TRAINING', 'WORKOUT', 'INTERVAL_WORKOUT',
    'CIRCUIT_TRAINING', 'HIIT',
)


def dedup_by_platform(rows: list[dict], priority=PLATFORM_PRIORITY,
                       threshold_sec: int = OVERLAP_THRESHOLD_SEC) -> list[dict]:
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


def load_sessions(start_date=None, end_date=None, csv_path=None):
    """exercise.csv を読み、重複解決済みの正規化 DataFrame を返す

    Parameters
    ----------
    start_date, end_date : datetime.date, optional
        期間フィルタ（両端含む）。未指定なら絞らない。
    csv_path : Path, optional
        テスト用の差し替え先。未指定なら EXERCISE_CSV_FILE。

    Returns
    -------
    pandas.DataFrame or None
        正規化列: id, start, end, exercise_type, display_name, platform,
        duration_min, calories, distance_km, average_heart_rate
        ファイルが無い、または該当0件なら None。

    Notes
    -----
    platform の重複解決は期間フィルタの後・カテゴリ絞り込みの前に、
    全セッションへ適用する（push とレポートが同じ集合を見るようにするため）。
    """
    path = csv_path if csv_path is not None else EXERCISE_CSV_FILE
    if not path.exists():
        return None

    df = pd.read_csv(path, dtype={'id': str})
    if df.empty:
        return None

    df['start'] = pd.to_datetime(
        df['start'], format='ISO8601', utc=True
    ).dt.tz_convert('Asia/Tokyo').dt.tz_localize(None)
    df['end'] = pd.to_datetime(
        df['end'], format='ISO8601', utc=True
    ).dt.tz_convert('Asia/Tokyo').dt.tz_localize(None)

    if start_date is not None:
        df = df[df['start'].dt.date >= start_date]
    if end_date is not None:
        df = df[df['start'].dt.date <= end_date]

    if df.empty:
        return None

    # dedup_by_platform は start/stop キーを見るので end -> stop に合わせる
    rows = df.to_dict('records')
    for row in rows:
        row['stop'] = row.pop('end')
    rows = dedup_by_platform(rows)
    if not rows:
        return None
    for row in rows:
        row['end'] = row.pop('stop')

    df = pd.DataFrame(rows)
    df['duration_min'] = df['duration_sec'] / 60
    df['distance_km'] = df['distance_m'] / 1000

    return df[[
        'id', 'start', 'end', 'exercise_type', 'display_name', 'platform',
        'duration_min', 'calories', 'distance_km', 'average_heart_rate',
    ]].reset_index(drop=True)
