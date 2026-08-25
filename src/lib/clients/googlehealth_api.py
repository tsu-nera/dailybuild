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


# sleep は 1回の取得で sleep.csv / sleep_levels.csv の2つの行リストを作るため、
# 他のエンドポイントと違って (sleep_rows, level_rows) のタプルを返す。
# googlehealth_fetcher 側で戻り値の形を見て分岐する。
FETCHERS = {
    'hrv': fetch_hrv,
    'breathing_rate': fetch_breathing_rate,
    'temperature_skin': fetch_temperature_skin,
    'sleep': fetch_sleep_all,
}
