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


# =============================================================================
# 栄養（食事ログ） -> data/wearable/nutrition_logs.csv, data/wearable/nutrition.csv
# =============================================================================

NUTRITION_LOG_COLUMNS = [
    'logId', 'logDate', 'foodId', 'foodName', 'mealTypeId', 'amount',
    'unitId', 'unitName', 'calories', 'protein', 'fat', 'carbs', 'fiber', 'sodium',
]
NUTRITION_COLUMNS = ['date', 'calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium', 'water']

# Fitbit の mealTypeId 体系。実データで一致を確認したのは 3/4/5/6 の4つ
# （DINNER 241件・BEFORE_DINNER 64件・AFTER_DINNER 17件・LUNCH 1件）。
# 1/2/7 は Fitbit の体系からの推定で、実データでは未確認
_MEAL_TYPE_ID = {
    'BREAKFAST': 1, 'BEFORE_LUNCH': 2, 'LUNCH': 3, 'BEFORE_DINNER': 4,
    'DINNER': 5, 'AFTER_DINNER': 6, 'ANYTIME': 7,
}

# food-measurement-unit の displayName キャッシュ（unitId -> unitName）。
# 一覧はページングが要るうえ毎回全件引くのは無駄なので、未知の unitId のときだけ
# GET users/me/dataTypes/food-measurement-unit/dataPoints/<unitId> で単体照会する
_UNIT_NAME_CACHE: dict[str, str] = {}


def _unit_name(creds, unit_id: str, cache: dict) -> str:
    """food-measurement-unit の displayName を返す（cache に無い unitId のときだけ照会する）

    照会に失敗したら空文字にして処理を止めない。
    """
    if unit_id in cache:
        return cache[unit_id]
    try:
        body = api._get(creds, f'{api.USER}/dataTypes/food-measurement-unit/dataPoints/{unit_id}')
        name = (body.get('foodMeasurementUnit') or {}).get('displayName', '')
    except api.GoogleHealthError:
        name = ''
    cache[unit_id] = name
    return name


def _nutrition_log_row(point: dict, unit_cache: dict) -> dict | None:
    """dataPoint 1件を nutrition_logs.csv 1行にする

    nutrition-log には食事ログ以外にカフェイン（fetch_caffeine 参照）も
    同居している。判別は foodDisplayName の有無で行う（id の桁数では
    判別できない。同じ Fitbit 由来でも11桁と19桁が混在する）。

    unitName は unit_cache から引くだけで、ここでは API を呼ばない
    （呼び出し側 fetch_nutrition_logs が未知の unitId を事前に解決する）。
    """
    nutrition = point.get('nutritionLog') or {}
    interval = nutrition.get('interval') or {}
    civil_start = interval.get('civilStartTime') or {}
    food_name = nutrition.get('foodDisplayName')
    if not food_name or 'date' not in civil_start:
        return None

    log_date = api._to_date(civil_start['date'])
    food_id = (nutrition.get('food') or '').rsplit('/', 1)[-1] or None

    meal_type = nutrition.get('mealType')
    meal_type_id = _MEAL_TYPE_ID.get(meal_type)
    if meal_type and meal_type_id is None:
        print(f'  ⚠️ 未知の mealType: {meal_type!r}（mealTypeId を空にする）')

    serving = nutrition.get('serving') or {}
    amount = _num(serving.get('amount'))
    unit_id = (serving.get('foodMeasurementUnit') or '').rsplit('/', 1)[-1] or None
    unit_name = unit_cache.get(unit_id, '') if unit_id else ''

    nutrients = {n.get('nutrient'): _num((n.get('quantity') or {}).get('grams'))
                for n in nutrition.get('nutrients') or []}
    sodium_g = nutrients.get('SODIUM')

    energy = nutrition.get('energy') or {}
    total_fat = nutrition.get('totalFat') or {}
    total_carbs = nutrition.get('totalCarbohydrate') or {}

    return {
        'logId': point['name'].rsplit('/', 1)[-1],
        'logDate': log_date,
        'foodId': food_id,
        'foodName': food_name,
        'mealTypeId': meal_type_id,
        'amount': None if amount is None else round(amount, 4),
        'unitId': unit_id,
        'unitName': unit_name,
        'calories': _num(energy.get('kcal')),
        'protein': nutrients.get('PROTEIN'),
        'fat': _num(total_fat.get('grams')),
        'carbs': _num(total_carbs.get('grams')),
        'fiber': nutrients.get('DIETARY_FIBER'),
        'sodium': None if sodium_g is None else sodium_g * 1000,
    }


def _nutrition_log_unit_id(point: dict) -> str | None:
    serving = ((point.get('nutritionLog') or {}).get('serving')) or {}
    return (serving.get('foodMeasurementUnit') or '').rsplit('/', 1)[-1] or None


def fetch_nutrition_logs(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    個別食事ログを期間で取得する（列は NUTRITION_LOG_COLUMNS）

    nutrition-log 型は dailyRollUp に非対応で list のみ。食事ログは疎な
    ため、fetch_caffeine と同じ理由で、打ち切り判定はページ内の**全
    dataPoint**（foodDisplayName の有無に関わらず）の日付で行う。
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
            civil_start = interval.get('civilStartTime') or {}
            if 'date' not in civil_start:
                continue
            page_dates.append(api._to_date(civil_start['date']))

        for point in page:
            unit_id = _nutrition_log_unit_id(point)
            if unit_id and unit_id not in _UNIT_NAME_CACHE:
                _unit_name(creds, unit_id, _UNIT_NAME_CACHE)
            row = _nutrition_log_row(point, _UNIT_NAME_CACHE)
            if row is not None and start_date.isoformat() <= row['logDate'] <= end_date.isoformat():
                rows.append(row)

        token = body.get('nextPageToken')
        if not token:
            break
        # 新しい順に返るので、ページ内の最新（foodDisplayName 有無に関わらず
        # 全dataPoint）が start_date より前なら以降も全て古い
        if page_dates and max(page_dates) < start_date.isoformat():
            break

    rows.sort(key=lambda r: r['logDate'])
    return rows


def fetch_nutrition(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    栄養（日次サマリ）を期間で取得する（列は NUTRITION_COLUMNS）

    nutrition-log には日次サマリに相当するデータ型が存在しない
    （nutrition / nutrition-summary / daily-nutrition はいずれも400）ため、
    fetch_nutrition_logs の結果を logDate で合算して日次行にする。

    食事ログが1件も無い日の行は作らない。Fitbit は未記録日に全項目0の行を
    書いていたが、Google はデータ点を返さないため、行を作ると「摂取0」と
    「未記録」が区別できなくなる。

    water は必ず None（空欄）にする。hydration / water データ型が
    存在せず（400）Google からは取得できないため、0 を入れると
    「水を摂っていない」という嘘になる。
    """
    logs = fetch_nutrition_logs(creds, start_date, end_date)

    by_date: dict[str, list[dict]] = {}
    for log in logs:
        by_date.setdefault(log['logDate'], []).append(log)

    def _sum(day_logs, key):
        values = [v.get(key) for v in day_logs if v.get(key) is not None]
        return sum(values) if values else 0

    rows = []
    for date, day_logs in by_date.items():
        rows.append({
            'date': date,
            'calories': round(_sum(day_logs, 'calories')),
            'carbs': round(_sum(day_logs, 'carbs'), 2),
            'fat': round(_sum(day_logs, 'fat'), 2),
            'fiber': round(_sum(day_logs, 'fiber'), 2),
            'protein': round(_sum(day_logs, 'protein'), 2),
            'sodium': round(_sum(day_logs, 'sodium'), 2),
            'water': None,
        })

    rows.sort(key=lambda r: r['date'])
    return rows


# =============================================================================
# 体重・体脂肪率 -> data/googlehealth/weight.csv, data/googlehealth/body_fat.csv
# =============================================================================

WEIGHT_COLUMNS = ['id', 'time', 'date', 'weight_kg', 'package_name', 'platform', 'recording_method']
BODY_FAT_COLUMNS = ['id', 'time', 'date', 'body_fat_rate', 'package_name', 'platform', 'recording_method']


def _sample_time_local(sample_time: dict) -> dt.datetime | None:
    """sampleTime.physicalTime + utcOffset をローカル時刻にする。physicalTime が無ければ None

    civilTime は使わない（カフェインと同じ理由で経路を統一する）。
    """
    physical_time = sample_time.get('physicalTime')
    if not physical_time:
        return None
    return _localize(physical_time, sample_time.get('utcOffset', '0s'))


def _body_measure_row(point: dict, payload_key: str, value_column: str, extract) -> dict | None:
    """dataPoint 1件を CSV 1行にする。値または時刻が欠ける場合は None

    payload_key は 'weight' / 'bodyFat'。extract は payload から数値を取り出す関数。
    """
    payload = point.get(payload_key) or {}
    sample_time = payload.get('sampleTime') or {}
    local = _sample_time_local(sample_time)
    if local is None:
        return None

    value = extract(payload)
    if value is None:
        return None

    time_str = local.isoformat(sep=' ')
    source = point.get('dataSource') or {}
    application = source.get('application') or {}

    return {
        'id': point['name'].rsplit('/', 1)[-1],
        'time': time_str,
        'date': time_str[:10],
        value_column: value,
        'package_name': application.get('packageName'),
        'platform': source.get('platform'),
        'recording_method': source.get('recordingMethod'),
    }


def _fetch_body_measures(creds, data_type: str, payload_key: str, value_column: str, extract,
                          start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    体重/体脂肪率の dataPoints を期間で取得する（fetch_exercise / fetch_caffeine と同じ形）

    体組成の計測は数日〜週おきで疎なため、打ち切り判定はページ内の全 dataPoint
    （値の有無に関わらず）の sampleTime の日付で行う（caffeine と同じ理由）。
    """
    rows = []
    token = None
    while True:
        params = {'pageToken': token} if token else {}
        body = api._get(creds, f'{api.USER}/dataTypes/{data_type}/dataPoints', params)
        page = body.get('dataPoints', [])

        page_dates = []
        for point in page:
            sample_time = (point.get(payload_key) or {}).get('sampleTime') or {}
            local = _sample_time_local(sample_time)
            if local is not None:
                page_dates.append(local.date())

        page_rows = [r for r in (_body_measure_row(p, payload_key, value_column, extract) for p in page)
                     if r is not None]
        rows.extend(r for r in page_rows
                    if start_date.isoformat() <= r['date'] <= end_date.isoformat())

        token = body.get('nextPageToken')
        if not token:
            break
        # 新しい順に返るので、ページ内の最新（値の有無に関わらず全dataPoint）が
        # start_date より前なら以降も全て古い
        if page_dates and max(page_dates) < start_date:
            break

    rows.sort(key=lambda r: r['time'])
    return rows


def fetch_weight(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    体重を期間で取得する（列は WEIGHT_COLUMNS）

    Fitbit 由来ではない。dataSource は 2012-2021 が FITBIT/FITBIT_WEB_API、2025 以降は
    HealthPlanet アプリ（jp.healthplanet.healthplanetapp）が Health Connect に書いたもの。
    HealthPlanet 非公式APIが落ちたときの予備経路になる。

    既存の data/wearable/body_weight.csv とは同一スキーマにできない: bmi が返らない
    （Google は身長を持たない）のと、logId 空間が別物（Fitbit は epoch-ms、Google は
    19桁の dataPoint ID）のため、data/googlehealth/weight.csv に別ファイルとして持つ。
    """
    def _extract_weight_kg(payload):
        grams = _num(payload.get('weightGrams'))
        return None if grams is None else round(grams / 1000, 3)

    return _fetch_body_measures(
        creds, 'weight', 'weight', 'weight_kg', _extract_weight_kg,
        start_date, end_date,
    )


def fetch_body_fat(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    体脂肪率を期間で取得する（列は BODY_FAT_COLUMNS）

    Fitbit 由来ではない。weight と同じく 2025 以降は HealthPlanet アプリが Health
    Connect に書いたもので、HealthPlanet 非公式APIが落ちたときの予備経路になる。

    既存の data/wearable/body_fat.csv とは同一スキーマにできない（logId 空間が別物）ため、
    data/googlehealth/body_fat.csv に別ファイルとして持つ。
    """
    return _fetch_body_measures(
        creds, 'body-fat', 'bodyFat', 'body_fat_rate',
        lambda payload: _num(payload.get('percentage')),
        start_date, end_date,
    )
