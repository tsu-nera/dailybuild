#!/usr/bin/env python
# coding: utf-8
"""
Google Health API クライアント

Fitbit Web API は 2026年9月に廃止されるため、その後継として使う。
各 fetch 関数は既存 CSV と同一スキーマの行リストを返し、fitbit_api の
parse_* に相当する処理まで内包する（Google 側はレスポンス形式が
データ型ごとに揃っているため、fetch と parse を分ける利点が薄い）。

認証情報:
  config/googlehealth_creds.json  OAuth クライアント（Cloud Console から取得）
  config/googlehealth_token.json  認可済みトークン（authorize() が生成）
"""

import datetime as dt
import re
import time
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR = Path(__file__).parent.parent.parent.parent
CREDS_FILE = BASE_DIR / 'config/googlehealth_creds.json'
TOKEN_FILE = BASE_DIR / 'config/googlehealth_token.json'

API_BASE = 'https://health.googleapis.com/v4'
# パスに使えるのは users/me のみ。users/{数値ID} は 400 になる
USER = 'users/me'

_SCOPE_PREFIX = 'https://www.googleapis.com/auth/googlehealth'
SCOPES = [
    f'{_SCOPE_PREFIX}.sleep.readonly',
    f'{_SCOPE_PREFIX}.health_metrics_and_measurements.readonly',
    f'{_SCOPE_PREFIX}.activity_and_fitness.readonly',
    f'{_SCOPE_PREFIX}.nutrition.readonly',
    f'{_SCOPE_PREFIX}.profile.readonly',
]


class GoogleHealthError(RuntimeError):
    """Google Health API 呼び出しの失敗"""


def authorize(interactive: bool = True) -> Credentials:
    """
    認証済み Credentials を返す

    Args:
        interactive: トークンが無い/失効している場合にブラウザを開くか。
                     False なら GoogleHealthError を投げる（CI・cron 用）
    """
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        return creds

    if not interactive:
        raise GoogleHealthError(
            f'有効なトークンがない: {TOKEN_FILE}。'
            'authorize(interactive=True) を対話環境で実行すること'
        )

    if not CREDS_FILE.exists():
        raise GoogleHealthError(f'OAuth クライアントがない: {CREDS_FILE}')

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    # 同意画面が本番環境なら refresh token は無期限（テストモードだと7日で失効する）
    creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
    TOKEN_FILE.write_text(creds.to_json())
    return creds


# 長いページングの途中で 500 が返ることがある（exercise の全履歴242ページで実測）。
# 1ページ落ちるだけで取得全体が捨たるので、5xx に限って短く粘る
RETRY_STATUSES = (500, 502, 503, 504)
MAX_RETRIES = 3
RETRY_WAIT_SEC = 2


def _get(creds: Credentials, path: str, params: dict = None) -> dict:
    for attempt in range(MAX_RETRIES + 1):
        r = requests.get(
            f'{API_BASE}/{path}',
            headers={'Authorization': f'Bearer {creds.token}'},
            params=params or {},
            timeout=60,
        )
        if r.status_code == 200:
            return r.json()
        if r.status_code not in RETRY_STATUSES or attempt == MAX_RETRIES:
            raise GoogleHealthError(f'GET {path} -> HTTP {r.status_code}: {r.text[:300]}')
        time.sleep(RETRY_WAIT_SEC * (attempt + 1))


def _post(creds: Credentials, path: str, json_body: dict) -> dict:
    r = requests.post(
        f'{API_BASE}/{path}',
        headers={'Authorization': f'Bearer {creds.token}'},
        json=json_body,
        timeout=60,
    )
    if r.status_code != 200:
        raise GoogleHealthError(f'POST {path} -> HTTP {r.status_code}: {r.text[:500]}')
    return r.json()


def list_data_points(creds: Credentials, data_type: str, max_points: int = 10000,
                     stop_before: dt.date = None, payload_key: str = None) -> list[dict]:
    """
    データ型の dataPoints を新しい順に取得する

    pageSize は指定しない。小さい値を渡すと 0件が返ることがある（実測）。

    Args:
        stop_before: このページの全件がこの日付より古くなった時点でページングを打ち切る。
                     全履歴を毎回引くと数分かかるため、期間取得では必ず指定する。
        payload_key: stop_before 判定に使う payload のキー
    """
    out = []
    token = None
    while len(out) < max_points:
        params = {'pageToken': token} if token else {}
        body = _get(creds, f'{USER}/dataTypes/{data_type}/dataPoints', params)
        page = body.get('dataPoints', [])
        out.extend(page)
        token = body.get('nextPageToken')
        if not token:
            break
        if stop_before and payload_key and _page_is_older_than(page, payload_key, stop_before):
            break
    return out


def _page_is_older_than(page: list[dict], payload_key: str, boundary: dt.date) -> bool:
    """ページ内の日付がすべて boundary より古いか（1件も日付を持たない場合は False）"""
    dates = [
        _to_date(p[payload_key]['date'])
        for p in page
        if p.get(payload_key, {}).get('date')
    ]
    return bool(dates) and max(dates) < boundary.isoformat()


def _to_date(civil_date: dict) -> str:
    return f"{civil_date['year']}-{civil_date['month']:02d}-{civil_date['day']:02d}"


def _num(value):
    """
    数値に正規化する

    Google は同じフィールドを数値で返したり文字列で返したりする
    （protobuf の int64 / double のシリアライズ差）。
    """
    if value is None or value == '':
        return None
    return float(value)


def _daily_rows(creds, data_type: str, payload_key: str, start_date: dt.date,
                end_date: dt.date, build) -> list[dict]:
    """
    daily-* 型（既に日次集計済み）を期間で絞って行リストにする

    daily-* 型は dailyRollUp が 400 になるため list を使う。API 側に期間指定の
    filter はあるが構文が型ごとに異なるので、取得後にクライアント側で絞る。
    """
    rows = []
    points = list_data_points(
        creds, data_type, stop_before=start_date, payload_key=payload_key
    )
    for point in points:
        value = point.get(payload_key)
        if not value or 'date' not in value:
            continue
        date = _to_date(value['date'])
        if not (start_date.isoformat() <= date <= end_date.isoformat()):
            continue
        row = build(value)
        if row is not None:
            rows.append({'date': date, **row})
    rows.sort(key=lambda r: r['date'])
    return rows


# =============================================================================
# dailyRollUp 共通呼び出し（activity / active_zone_minutes が使う）
# =============================================================================

# 型ごとの最大取得期間（日数）。超えると INVALID_ROLLUP_QUERY_DURATION になるが、
# メッセージは "Invalid argument in request." としか言わない
# （実際の上限は error.details[0].metadata.maxDurationDays に入る）。
# 実測値をハードコードし、この範囲で自動分割する。
#
# core-body-temperature はここに含めない: dailyRollUp は日次平均になるが、
# 既存 CSV の date_time は「日次固定00:00:00の行」と「実測時刻の行」が
# 混在しており（sampleTime.civilTime が実測時刻を持つ）、平均で埋めると
# 既存の実測時刻行と二重に入る。list + civilTime を使う（fetch_temperature_core）。
ROLLUP_MAX_DURATION_DAYS = {
    'steps': 90,
    'distance': 90,
    'sedentary-period': 90,
    'active-zone-minutes': 90,
    'total-calories': 14,
    'active-minutes': 14,
}


def _civil_date(d: dt.date) -> dict:
    return {'year': d.year, 'month': d.month, 'day': d.day}


def _daily_rollup(creds: Credentials, data_type: str, start_date: dt.date,
                  end_date: dt.date) -> list[dict]:
    """
    dataPoints:dailyRollUp を型ごとの maxDurationDays で自動分割して呼び、
    rollupDataPoints をまとめて返す

    型を知らないまま分割単位を誤ると INVALID_ROLLUP_QUERY_DURATION で
    黙って0件になりかねないため、ROLLUP_MAX_DURATION_DAYS に無い型は
    KeyError で明示的に落とす（握り潰さない）。

    range.end は排他的（実測: start==end は400、end 当日は結果に含まれない。
    例えば total-calories で start=2026-08-01, end=2026-08-15 を渡すと
    2026-08-01〜08-14 の14件が返り、08-15 は含まれない）。Issue #75 の
    実測メモにはこの挙動の記載が無かったため、含めたい最終日 chunk_end に
    +1 日して渡す。maxDurationDays の判定は (end - start) の日数で行われる
    ため、この +1 を反映してもチャンクサイズは max_days のままでよい
    （08-01〜08-15 の raw span は14日で total-calories の上限と一致し成功、
    15日にすると INVALID_ROLLUP_QUERY_DURATION で失敗することを実測済み）。
    """
    max_days = ROLLUP_MAX_DURATION_DAYS[data_type]

    points = []
    chunk_start = start_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + dt.timedelta(days=max_days - 1), end_date)
        body = {
            'range': {
                'start': {'date': _civil_date(chunk_start)},
                'end': {'date': _civil_date(chunk_end + dt.timedelta(days=1))},
            }
        }
        resp = _post(creds, f'{USER}/dataTypes/{data_type}/dataPoints:dailyRollUp', body)
        points.extend(resp.get('rollupDataPoints', []))
        chunk_start = chunk_end + dt.timedelta(days=1)
    return points


def _rollup_by_date(creds: Credentials, data_type: str, payload_key: str,
                    start_date: dt.date, end_date: dt.date) -> dict[str, dict]:
    """dailyRollUp を取得し、日付(YYYY-MM-DD) -> payload の辞書にする"""
    points = _daily_rollup(creds, data_type, start_date, end_date)
    out = {}
    for point in points:
        payload = point.get(payload_key)
        civil_start = point.get('civilStartTime', {}).get('date')
        if payload is None or civil_start is None:
            continue
        out[_to_date(civil_start)] = payload
    return out


# =============================================================================
# HRV -> data/fitbit/hrv.csv
# =============================================================================

def fetch_hrv(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """列: date, daily_rmssd, deep_rmssd"""
    return _daily_rows(
        creds, 'daily-heart-rate-variability', 'dailyHeartRateVariability',
        start_date, end_date,
        lambda v: {
            'daily_rmssd': _num(v.get('averageHeartRateVariabilityMilliseconds')),
            'deep_rmssd': _num(v.get(
                'deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds'
            )),
        },
    )


# =============================================================================
# 呼吸数 -> data/fitbit/breathing_rate.csv
# =============================================================================

def fetch_breathing_rate(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """列: date, breathing_rate"""
    return _daily_rows(
        creds, 'daily-respiratory-rate', 'dailyRespiratoryRate',
        start_date, end_date,
        lambda v: {'breathing_rate': _num(v.get('breathsPerMinute'))},
    )


# =============================================================================
# 皮膚温 -> data/fitbit/temperature_skin.csv
# =============================================================================

def fetch_temperature_skin(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date, nightly_relative, log_type

    Fitbit の nightly_relative は「基礎体温からの差分」で、Google はその材料
    （実測値とベースライン）を別々に返すため差を取って再現する。log_type に
    相当するフィールドは Google 側に無い。
    """
    def build(v):
        nightly = _num(v.get('nightlyTemperatureCelsius'))
        baseline = _num(v.get('baselineTemperatureCelsius'))
        if nightly is None or baseline is None:
            return None
        # +0.0 は負のゼロの正規化。round(-0.04, 1) は -0.0 を返し、
        # CSV に "-0.0" と書かれて既存の "0.0" と差分になる
        return {
            'nightly_relative': round(nightly - baseline, 1) + 0.0,
            'log_type': None,
        }

    return _daily_rows(
        creds, 'daily-sleep-temperature-derivations',
        'dailySleepTemperatureDerivations', start_date, end_date, build,
    )


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
        body = _get(creds, f'{USER}/dataTypes/exercise/dataPoints', params)
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
# 睡眠 -> data/fitbit/sleep.csv, data/fitbit/sleep_levels.csv
# =============================================================================

# Google の stages 型ステージ名 -> 既存 CSV の level 値
# 既存 sleep_levels.csv には Fitbit の classic 睡眠由来の asleep/restless/awake も
# 混在するが（cut -d, -f4 data/fitbit/sleep_levels.csv で確認）、stages 型の既存行は
# wake/light/deep/rem のみを使っている（asleep/restless は classic 型専用）。
# Google は stages 型しか返さないため、この対応で既存の値域に収まる。
_STAGE_LEVEL = {
    'AWAKE': 'wake',
    'LIGHT': 'light',
    'DEEP': 'deep',
    'REM': 'rem',
}


def _localize(utc_time: str, utc_offset: str) -> dt.datetime:
    """UTC の ISO8601 文字列 + オフセット文字列（例 "32400s"）をローカル時刻にする"""
    t = dt.datetime.fromisoformat(utc_time.replace('Z', '+00:00'))
    offset_seconds = int(utc_offset.rstrip('s'))
    return (t + dt.timedelta(seconds=offset_seconds)).replace(tzinfo=None)


def _list_sleep_points(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    sleep の dataPoints をページングで取得する

    sleep は list の filter が使えない（sleep.interval.start_time を渡すと
    INVALID_DATA_POINT_FILTER_DATA_TYPE_MEMBER で 400）ため、新しい順に
    ページングして、ページ内の全点の起床日が start_date より古くなった時点で
    打ち切る。取得後に呼び出し側で start_date <= dateOfSleep <= end_date に絞る。
    """
    out = []
    token = None
    while True:
        params = {'pageToken': token} if token else {}
        body = _get(creds, f'{USER}/dataTypes/sleep/dataPoints', params)
        page = body.get('dataPoints', [])
        out.extend(page)
        token = body.get('nextPageToken')
        if not token:
            break

        wake_dates = []
        for p in page:
            interval = p.get('sleep', {}).get('interval')
            if not interval:
                continue
            wake_dates.append(
                _localize(interval['endTime'], interval['endUtcOffset']).date()
            )
        if wake_dates and max(wake_dates) < start_date:
            break

    return out


def fetch_sleep_all(creds, start_date: dt.date, end_date: dt.date) -> tuple[list[dict], list[dict]]:
    """
    sleep の dataPoints を1回取得し、sleep.csv 用と sleep_levels.csv 用の
    行リストを両方作る（fetch_sleep / fetch_sleep_levels が別々に API を
    叩くと2倍のリクエストになるため、ここで共有する）

    Returns:
        (sleep_rows, level_rows)
    """
    points = _list_sleep_points(creds, start_date, end_date)

    sessions = []

    for point in points:
        sleep = point.get('sleep')
        if not sleep:
            continue
        interval = sleep.get('interval')
        if not interval:
            continue

        start_local = _localize(interval['startTime'], interval['startUtcOffset'])
        end_local = _localize(interval['endTime'], interval['endUtcOffset'])
        date_of_sleep = end_local.date()

        summary = sleep.get('summary', {})
        metadata = sleep.get('metadata', {})

        stages = {s['type']: s for s in summary.get('stagesSummary', [])}

        def stage_minutes(stage_type):
            v = stages.get(stage_type, {}).get('minutes')
            return _num(v)

        def stage_count(stage_type):
            v = stages.get(stage_type, {}).get('count')
            return _num(v)

        minutes_asleep = _num(summary.get('minutesAsleep'))
        minutes_in_sleep_period = _num(summary.get('minutesInSleepPeriod'))
        efficiency = None
        if minutes_asleep is not None and minutes_in_sleep_period:
            efficiency = round(minutes_asleep / minutes_in_sleep_period * 100)

        # name: "users/.../dataTypes/sleep/dataPoints/<ID>"
        log_id = point.get('name', '').rstrip('/').rsplit('/', 1)[-1]

        sleep_row = {
            'dateOfSleep': date_of_sleep.isoformat(),
            'startTime': start_local.strftime('%Y-%m-%dT%H:%M:%S.000'),
            'endTime': end_local.strftime('%Y-%m-%dT%H:%M:%S.000'),
            'duration': int((end_local - start_local).total_seconds() * 1000),
            'timeInBed': minutes_in_sleep_period,
            'efficiency': efficiency,
            'minutesAsleep': minutes_asleep,
            'minutesAwake': _num(summary.get('minutesAwake')),
            'minutesAfterWakeup': _num(summary.get('minutesAfterWakeUp')),
            'minutesToFallAsleep': _num(summary.get('minutesToFallAsleep')),
            'logId': log_id,
            'logType': None,
            'type': (sleep.get('type') or '').lower(),
            'infoCode': None,
            'isMainSleep': bool(metadata.get('mainSleep', False)),
            'deepMinutes': stage_minutes('DEEP'),
            'lightMinutes': stage_minutes('LIGHT'),
            'remMinutes': stage_minutes('REM'),
            'wakeMinutes': stage_minutes('AWAKE'),
            'deepCount': stage_count('DEEP'),
            'lightCount': stage_count('LIGHT'),
            'remCount': stage_count('REM'),
            'wakeCount': stage_count('AWAKE'),
            'deepAvg30': None,
            'lightAvg30': None,
            'remAvg30': None,
            'wakeAvg30': None,
        }

        sessions.append({
            'sleep_row': sleep_row,
            'start': start_local,
            'end': end_local,
            'length': minutes_in_sleep_period or 0,
            'log_id': log_id,
            'date_of_sleep': date_of_sleep,
            'stages': sleep.get('stages', []) or [],
            'short_awakenings': sleep.get('shortAwakenings', []) or [],
        })

    # 重なり判定は dateOfSleep でなく実時刻で行うため、期間フィルタより先に
    # 全セッション（期間外の前後日も含む）を対象に重なりを解消する。
    # 例: 08-21夜の45分セッションは08-21の本睡眠とは重ならないが、
    # 08-22（期間外）の本睡眠と重なる。期間フィルタを先にかけると
    # 08-22側のセッションが候補から消え、この重なりを検出できない
    kept = _drop_overlapping_sessions(sessions)

    sleep_rows = []
    level_rows = []
    for s in kept:
        # 重なり解消後にクライアント側で期間を絞る（sleep は list の filter が
        # 使えないため）
        if not (start_date <= s['date_of_sleep'] <= end_date):
            continue
        sleep_rows.append(s['sleep_row'])
        for entry in s['stages']:
            level_rows.append(_build_level_row(s['log_id'], s['date_of_sleep'], entry, is_short=False))
        for entry in s['short_awakenings']:
            level_rows.append(_build_level_row(s['log_id'], s['date_of_sleep'], entry, is_short=True))

    return sleep_rows, level_rows


def _drop_overlapping_sessions(sessions: list[dict]) -> list[dict]:
    """
    メイン睡眠の時間帯に重なる短いセッションを落とす

    Google の sleep は、メイン睡眠の内側に重なる短いセッションを別の
    dataPoint として独立に返すことがある（実測: 2022-04〜2026-08 の
    1,331セッション中105件 = 7.9% が他セッションと時間的に重なる。重なる
    側の長さは10〜480分）。ただし**重なりは 2026-05 以降に集中している**。
    2026-04 以前は0件で、2026-05 は35%、2026-06〜08 は48〜52%。通算の
    7.9% を見て「めったに発火しない」と誤解しないこと。
    Fitbit にはこの種のレコードが存在せず、
    そのまま保存すると1日のセッション数が Fitbit 時代より増え、
    mind/body レポートの「昼寝をメイン睡眠として拾う」既知の不具合を
    悪化させる方向に効く。そのため保存前に重なりを解消する。

    どちらを残すかは isMainSleep では決めない。mainSleep が無いセッション
    の方が長いケース（実測で重なる側の最大480分）が実在するため、
    isMainSleep をキーにすると短い方を残しかねない。長さ
    （minutesInSleepPeriod）の降順に見て、既に採用した区間と重ならない
    セッションだけを採用する貪欲法にする。

    重なり判定: start < 既存end かつ 既存start < end

    対照検証: このフィルタを通すと 2026-06-01〜08-24 の85日すべてで
    Fitbit の sleep.csv とセッション数が一致する（フィルタ前は 26/85）。
    """
    by_length_desc = sorted(sessions, key=lambda s: s['length'], reverse=True)

    kept = []
    dropped = 0
    for s in by_length_desc:
        overlaps = any(s['start'] < k['end'] and k['start'] < s['end'] for k in kept)
        if overlaps:
            dropped += 1
            continue
        kept.append(s)

    if dropped:
        print(f'  ⚠️ メイン睡眠に重なる短いセッションを{dropped}件除外')

    # 元の並び（新しい順）に戻す
    kept_ids = {id(s) for s in kept}
    return [s for s in sessions if id(s) in kept_ids]


def _build_level_row(log_id: str, date_of_sleep: dt.date, entry: dict, is_short: bool) -> dict:
    start_local = _localize(entry['startTime'], entry['startUtcOffset'])
    end_local = _localize(entry['endTime'], entry['endUtcOffset'])
    return {
        'logId': log_id,
        'dateOfSleep': date_of_sleep.isoformat(),
        'dateTime': start_local.strftime('%Y-%m-%d %H:%M:%S'),
        'level': _STAGE_LEVEL.get(entry['type'], entry['type'].lower()),
        'seconds': int((end_local - start_local).total_seconds()),
        'isShort': is_short,
    }


# =============================================================================
# 活動量 -> data/fitbit/activity.csv
# =============================================================================

def fetch_activity(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date, caloriesOut, activityCalories, steps, distance, sedentaryMinutes,
        lightlyActiveMinutes, fairlyActiveMinutes, veryActiveMinutes

    steps / distance / active-minutes / total-calories の4型を叩いて日付で
    マージする（型ごとに maxDurationDays が違うため、分割単位も型ごとに変わる。
    steps/distance は90日、active-minutes/total-calories は14日）。

    sedentary-period は叩かない: Google の定義が Fitbit の sedentaryMinutes と
    違う（Fitbit は起床中の非活動時間全体、Google は明示的な座位バウトのみを
    数える）。実測13日中0日が一致し、Google側が約350分少ない。

    activityCalories と sedentaryMinutes は Google に対応する型が無いため常に
    None にする。merge_csv はセル単位で df_new を優先しつつ NaN は df_old で
    埋めるため、この2列は過去の行の値を消さず、新しい日だけが空になる。
    """
    steps_by_date = _rollup_by_date(creds, 'steps', 'steps', start_date, end_date)
    distance_by_date = _rollup_by_date(creds, 'distance', 'distance', start_date, end_date)
    minutes_by_date = _rollup_by_date(creds, 'active-minutes', 'activeMinutes', start_date, end_date)
    calories_by_date = _rollup_by_date(creds, 'total-calories', 'totalCalories', start_date, end_date)

    all_dates = sorted(
        set(steps_by_date) | set(distance_by_date)
        | set(minutes_by_date) | set(calories_by_date)
    )
    if all_dates:
        print('  ⚠️ activity: activityCalories / sedentaryMinutes は Google に対応する型が無いため空にする')

    rows = []
    for date in all_dates:
        distance_mm = _num(distance_by_date.get(date, {}).get('millimetersSum'))
        distance_km = distance_mm / 1_000_000 if distance_mm is not None else None

        levels = {
            lvl.get('activityLevel'): _num(lvl.get('activeMinutesSum'))
            for lvl in minutes_by_date.get(date, {}).get('activeMinutesRollupByActivityLevel', [])
        }

        rows.append({
            'date': date,
            'caloriesOut': _num(calories_by_date.get(date, {}).get('kcalSum')),
            'activityCalories': None,
            'steps': _num(steps_by_date.get(date, {}).get('countSum')),
            'distance': distance_km,
            'sedentaryMinutes': None,
            'lightlyActiveMinutes': levels.get('LIGHT'),
            'fairlyActiveMinutes': levels.get('MODERATE'),
            'veryActiveMinutes': levels.get('VIGOROUS'),
        })
    return rows


# =============================================================================
# アクティブゾーン分 -> data/fitbit/active_zone_minutes.csv
# =============================================================================

def fetch_active_zone_minutes(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date, activeZoneMinutes, fatBurnActiveZoneMinutes, cardioActiveZoneMinutes,
        peakActiveZoneMinutes

    合計の activeZoneMinutes は Google に対応するフィールドが無いため算出する。
    fitbit_api.parse_active_zone_minutes の docstring は「cardio/peak 1分=2AZM」の
    重み付けと書いているが、実データ（2026-08-11〜23の13日）はそれに従わない:
    単純和 fatBurn+cardio+peak が Fitbit の activeZoneMinutes と13/13で一致し、
    重み付き fatBurn+2*cardio+2*peak は1/13しか一致しない。単純和を採用する。
    """
    by_date = _rollup_by_date(creds, 'active-zone-minutes', 'activeZoneMinutes', start_date, end_date)
    rows = []
    for date, payload in sorted(by_date.items()):
        fat = _num(payload.get('sumInFatBurnHeartZone'))
        cardio = _num(payload.get('sumInCardioHeartZone'))
        peak = _num(payload.get('sumInPeakHeartZone'))
        rows.append({
            'date': date,
            'activeZoneMinutes': (fat or 0.0) + (cardio or 0.0) + (peak or 0.0),
            'fatBurnActiveZoneMinutes': fat,
            'cardioActiveZoneMinutes': cardio,
            'peakActiveZoneMinutes': peak,
        })
    return rows


# =============================================================================
# 深部体温 -> data/fitbit/temperature_core.csv
# =============================================================================

def _civil_time_str(civil: dict) -> str:
    """civilTime（date + 省略されうる time）を "YYYY-MM-DD HH:MM:SS" にする"""
    date = civil['date']
    time = civil.get('time') or {}
    return (
        f"{date['year']:04d}-{date['month']:02d}-{date['day']:02d} "
        f"{time.get('hours', 0):02d}:{time.get('minutes', 0):02d}:{time.get('seconds', 0):02d}"
    )


def fetch_temperature_core(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date_time, temperature

    dailyRollUp ではなく list を使う（当初 dailyRollUp + 日次平均で実装したが、
    既存 CSV の date_time は「日次で00:00:00固定の行」と「実測時刻の行」が
    混在しており（実測: 2026-01-03〜08-16 は00:00:00固定、2026-02-02
    08:12:49 等は実測時刻）、日次平均で埋めると既にある実測時刻行と同じ日に
    2行できてしまう。実測で 08-17/18/19/22/23 の5日の二重化を確認したため
    list + sampleTime.civilTime に切り替えた。civilTime をそのまま使えば
    既存 CSV と一致する（2026-08-23: Google "2026-08-23 05:49:21, 36.1" ==
    既存CSV "2026-08-23 05:49:21,36.1"）。

    civilTime.time は hours/minutes/seconds が0のとき省略されるため
    .get(key, 0) で補う。

    保存は googlehealth_fetcher 側で sleep と同じ期間置換
    （csv_utils.replace_csv_period）を使う。キーマージにすると既存の
    00:00:00 行と実測時刻行が両方残ってしまうため。
    """
    rows = []
    token = None
    while True:
        params = {'pageToken': token} if token else {}
        body = _get(creds, f'{USER}/dataTypes/core-body-temperature/dataPoints', params)
        page = body.get('dataPoints', [])

        page_rows = []
        for point in page:
            payload = point.get('coreBodyTemperature')
            if not payload:
                continue
            civil = (payload.get('sampleTime') or {}).get('civilTime')
            temperature = _num(payload.get('temperatureCelsius'))
            if not civil or temperature is None:
                continue
            page_rows.append({
                'date_time': _civil_time_str(civil),
                'temperature': temperature,
            })

        rows.extend(
            r for r in page_rows
            if start_date.isoformat() <= r['date_time'][:10] <= end_date.isoformat()
        )

        token = body.get('nextPageToken')
        if not token:
            break
        # 新しい順に返るので、ページ内の最新が start_date より前なら以降も全て古い
        if page_rows and max(r['date_time'][:10] for r in page_rows) < start_date.isoformat():
            break

    rows.sort(key=lambda r: r['date_time'])
    return rows


# sleep は 1回の取得で sleep.csv / sleep_levels.csv の2つの行リストを作るため、
# 他のエンドポイントと違って (sleep_rows, level_rows) のタプルを返す。
# googlehealth_fetcher 側で戻り値の形を見て分岐する。
FETCHERS = {
    'hrv': fetch_hrv,
    'breathing_rate': fetch_breathing_rate,
    'temperature_skin': fetch_temperature_skin,
    'sleep': fetch_sleep_all,
    'activity': fetch_activity,
    'active_zone_minutes': fetch_active_zone_minutes,
    'temperature_core': fetch_temperature_core,
    'exercise': fetch_exercise,
}
