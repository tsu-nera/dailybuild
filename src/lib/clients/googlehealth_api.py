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


FETCHERS = {
    'hrv': fetch_hrv,
    'breathing_rate': fetch_breathing_rate,
    'temperature_skin': fetch_temperature_skin,
    'exercise': fetch_exercise,
}
