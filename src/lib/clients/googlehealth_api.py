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


def _get(creds: Credentials, path: str, params: dict = None) -> dict:
    r = requests.get(
        f'{API_BASE}/{path}',
        headers={'Authorization': f'Bearer {creds.token}'},
        params=params or {},
        timeout=60,
    )
    if r.status_code != 200:
        raise GoogleHealthError(f'GET {path} -> HTTP {r.status_code}: {r.text[:300]}')
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
            'daily_rmssd': v.get('averageHeartRateVariabilityMilliseconds'),
            'deep_rmssd': v.get(
                'deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds'
            ),
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
        lambda v: {'breathing_rate': v.get('breathsPerMinute')},
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
        nightly = v.get('nightlyTemperatureCelsius')
        baseline = v.get('baselineTemperatureCelsius')
        if nightly is None or baseline is None:
            return None
        return {
            'nightly_relative': round(nightly - baseline, 1),
            'log_type': None,
        }

    return _daily_rows(
        creds, 'daily-sleep-temperature-derivations',
        'dailySleepTemperatureDerivations', start_date, end_date, build,
    )


FETCHERS = {
    'hrv': fetch_hrv,
    'breathing_rate': fetch_breathing_rate,
    'temperature_skin': fetch_temperature_skin,
}
