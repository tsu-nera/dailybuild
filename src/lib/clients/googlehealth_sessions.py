#!/usr/bin/env python
# coding: utf-8
"""
Google Health セッション型（1日に複数行が立つ型）
-> data/googlehealth/exercise.csv, data/googlehealth/caffeine.csv

googlehealth_api.py から分割（Issue #78。ファイルサイズ hook の 500行上限対応）。
`_get` 等の共通プリミティブはテストが `googlehealth_api.<name>` を直接
monkeypatch する前提なので、ここでは `from . import googlehealth_api as api` の
形で呼び出し、モジュール属性を経由させる（静的 import で束縛すると
monkeypatch が効かなくなる）。
"""

import datetime as dt
import re

from . import googlehealth_api as api
from .googlehealth_api import _num
from .googlehealth_sleep import _localize

# =============================================================================
# 運動セッション -> data/googlehealth/exercise.csv
# =============================================================================

EXERCISE_COLUMNS = [
    'id', 'start', 'end', 'duration_sec', 'exercise_type', 'display_name',
    'platform', 'recording_method', 'calories', 'distance_m',
    'average_heart_rate', 'active_zone_minutes', 'steps', 'has_gps',
]

# 秒未満が9桁で返ることがあり、fromisoformat は6桁までしか受け付けない
_FRACTION_RE = re.compile(r'\.(\d{6})\d*')


def _parse_instant(value: str) -> dt.datetime:
    """RFC3339（UTC, 末尾 Z）を tz-aware datetime にする"""
    return dt.datetime.fromisoformat(
        _FRACTION_RE.sub(r'.\1', value).replace('Z', '+00:00')
    )


def _offset_tz(value: str) -> dt.timezone:
    """"32400s" 形式の UTC オフセットを tzinfo にする"""
    return dt.timezone(dt.timedelta(seconds=int(str(value).rstrip('s') or 0)))


def _exercise_row(point: dict) -> dict | None:
    """dataPoint 1件を CSV 1行にする。時刻が欠けていれば None"""
    exercise = point.get('exercise') or {}
    interval = exercise.get('interval') or {}
    if not interval.get('startTime') or not interval.get('endTime'):
        return None

    start = _parse_instant(interval['startTime']).astimezone(
        _offset_tz(interval.get('startUtcOffset', '0s')))
    stop = _parse_instant(interval['endTime']).astimezone(
        _offset_tz(interval.get('endUtcOffset', interval.get('startUtcOffset', '0s'))))

    metrics = exercise.get('metricsSummary') or {}
    source = point.get('dataSource') or {}
    distance = _num(metrics.get('distanceMillimeters'))

    return {
        'id': point['name'].rsplit('/', 1)[-1],
        'start': start.isoformat(sep=' '),
        'end': stop.isoformat(sep=' '),
        'duration_sec': int((stop - start).total_seconds()),
        'exercise_type': exercise.get('exerciseType'),
        'display_name': exercise.get('displayName'),
        'platform': source.get('platform'),
        'recording_method': source.get('recordingMethod'),
        'calories': _num(metrics.get('caloriesKcal')),
        'distance_m': distance if distance is None else distance / 1000,
        'average_heart_rate': _num(metrics.get('averageHeartRateBeatsPerMinute')),
        'active_zone_minutes': _num(metrics.get('activeZoneMinutes')),
        'steps': _num(metrics.get('steps')),
        'has_gps': (exercise.get('exerciseMetadata') or {}).get('hasGps'),
    }


def fetch_exercise(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    運動セッションを期間で取得する（列は EXERCISE_COLUMNS）

    exercise 型は dailyRollUp に対応せず list のみ。全履歴は242ページあるため、
    ページ内の最新セッションが start_date より古くなった時点で打ち切る。

    同じ運動が複数プラットフォームから重複して届く（Fitbit の Charge 6 と
    Health Connect 経由の Google Fit / Hevy が、ほぼ同じ時間帯を別セッションと
    して返す）。ここでは落とさずそのまま行にし、重複解決は利用側で行う。
    """
    rows = []
    token = None
    while True:
        params = {'pageToken': token} if token else {}
        body = api._get(creds, f'{api.USER}/dataTypes/exercise/dataPoints', params)
        page = body.get('dataPoints', [])

        page_rows = [r for r in (_exercise_row(p) for p in page) if r is not None]
        rows.extend(r for r in page_rows
                    if start_date.isoformat() <= r['start'][:10] <= end_date.isoformat())

        token = body.get('nextPageToken')
        if not token:
            break
        # 新しい順に返るので、ページ内の最新が start_date より前なら以降も全て古い
        if page_rows and max(r['start'][:10] for r in page_rows) < start_date.isoformat():
            break

    rows.sort(key=lambda r: r['start'])
    return rows


# =============================================================================
# カフェイン摂取 -> data/googlehealth/caffeine.csv
# =============================================================================

CAFFEINE_COLUMNS = ['id', 'time', 'date', 'caffeine_mg', 'package_name', 'platform', 'recording_method']


def _caffeine_row(point: dict) -> dict | None:
    """dataPoint 1件を CSV 1行にする。CAFFEINE を含まない/時刻が欠ける場合は None

    nutrition-log には Cronometer / Fitbit 由来の食事ログ（macros）も同居しているため、
    nutrients に CAFFEINE を含む点だけを拾う。packageName ではフィルタしない
    （他アプリからカフェインが届いても拾えるように）。
    """
    nutrition = point.get('nutritionLog') or {}
    interval = nutrition.get('interval') or {}
    if not interval.get('startTime'):
        return None

    caffeine_grams = None
    for nutrient in nutrition.get('nutrients') or []:
        if nutrient.get('nutrient') == 'CAFFEINE':
            caffeine_grams = _num((nutrient.get('quantity') or {}).get('grams'))
            break
    if caffeine_grams is None:
        return None

    # civilStartTime は使わない: Cronometer 由来の行は time が 00:00 固定だが、
    # startTime + startUtcOffset でも同じ値になるため経路を統一する
    local = _localize(interval['startTime'], interval.get('startUtcOffset', '0s'))
    time_str = local.isoformat(sep=' ')
    source = point.get('dataSource') or {}
    application = source.get('application') or {}

    return {
        'id': point['name'].rsplit('/', 1)[-1],
        'time': time_str,
        'date': time_str[:10],
        'caffeine_mg': round(caffeine_grams * 1000, 3),
        'package_name': application.get('packageName'),
        'platform': source.get('platform'),
        'recording_method': source.get('recordingMethod'),
    }


def fetch_caffeine(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    カフェイン摂取記録を期間で取得する（列は CAFFEINE_COLUMNS）

    nutrition-log 型は dailyRollUp に非対応で list のみ。カフェイン記録は疎な
    ため、CAFFEINE を含む行だけで打ち切り判定をすると効かない（1ページに
    CAFFEINE 行が無くても、ページ全体としては start_date に届いていないことが
    ある）。判定はページ内の**全 dataPoint**（CAFFEINE 有無に関わらず）の
    interval の日付で行う。
    """
    rows = []
    token = None
    while True:
        params = {'pageToken': token} if token else {}
        body = api._get(creds, f'{api.USER}/dataTypes/nutrition-log/dataPoints', params)
        page = body.get('dataPoints', [])

        page_dates = []
        for point in page:
            interval = (point.get('nutritionLog') or {}).get('interval') or {}
            if not interval.get('startTime'):
                continue
            page_dates.append(
                _localize(interval['startTime'], interval.get('startUtcOffset', '0s')).date()
            )

        page_rows = [r for r in (_caffeine_row(p) for p in page) if r is not None]
        rows.extend(r for r in page_rows
                    if start_date.isoformat() <= r['date'] <= end_date.isoformat())

        token = body.get('nextPageToken')
        if not token:
            break
        # 新しい順に返るので、ページ内の最新（CAFFEINE 有無に関わらず全dataPoint）が
        # start_date より前なら以降も全て古い
        if page_dates and max(page_dates) < start_date:
            break

    rows.sort(key=lambda r: r['time'])
    return rows
