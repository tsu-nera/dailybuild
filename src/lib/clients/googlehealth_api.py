#!/usr/bin/env python
# coding: utf-8
"""
Google Health API クライアント（コア）

Fitbit Web API は 2026年9月に廃止されるため、その後継として使う。
各 fetch 関数は既存 CSV と同一スキーマの行リストを返し、fitbit_api の
parse_* に相当する処理まで内包する（Google 側はレスポンス形式が
データ型ごとに揃っているため、fetch と parse を分ける利点が薄い）。

認証・HTTP・ページング等の共通プリミティブはこのファイルに置き、型ごとの
fetch_* 関数は以下に分割している（Issue #78。ファイルサイズ hook の
500行上限対応）:
  - googlehealth_sleep.py     睡眠（sleep / sleep_levels）
  - googlehealth_sessions.py  セッション型（exercise / caffeine）
  - googlehealth_daily.py     daily-* 型（hrv / breathing_rate / temperature_skin /
                               heart_rate / spo2 / activity / active_zone_minutes /
                               temperature_core）
  - googlehealth_intraday.py  intraday 型（heart_rate_intraday / steps_intraday /
                               spo2_intraday / hrv_intraday / br_intraday。Issue #76）

テストは `googlehealth_api._get` / `_post` / `_list_sleep_points` を直接
monkeypatch する。分割先モジュールはこれらを `from . import googlehealth_api
as api` の形で呼ぶことで、モジュール属性の動的解決を保ち monkeypatch が
効くようにしている（`from .googlehealth_api import _get` のような静的
import は束縛が固定されるため使わない）。

認証情報:
  config/googlehealth_creds.json  OAuth クライアント（Cloud Console から取得）
  config/googlehealth_token.json  認可済みトークン（authorize() が生成）
"""

import datetime as dt
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
# 1ページ落ちるだけで取得全体が捨たるため、5xx に限って短く粘る
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


FILTER_WINDOW_MARGIN = dt.timedelta(hours=15)


def list_filtered_points(creds: Credentials, data_type: str, filter_field: str,
                         start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    `filter` クエリパラメータ付きで dataPoints を取得する（intraday 型向け、Issue #76）

    list_data_points と違い、新しい順に打ち切るのではなく filter で API 側に
    範囲を絞らせる。intraday は1日あたり数万点あり、打ち切りだけでは
    絞り切れない（heart-rate で約33,000点/日）。

    filter 構文は snake_case で完全修飾したフィールド名が必須（例:
    `heart_rate.sample_time.physical_time`）。camelCase は
    INVALID_DATA_POINT_FILTER_DATA_TYPE_RESTRICTION で 400 になる。
    **上限（`<`）を付けないと新しい順に返るだけで過去に届かない。**

    `physicalTime` は UTC・`civilTime` がローカル（JST, utcOffset=32400s）
    のため、UTC の暦日で filter を切るとローカル日付と1日ずれる。
    ここでは filter の窓を ±15時間広く取るだけにし（UTC オフセット -12〜+14
    のどれでもローカル暦日を必ず覆う）、最終的な期間の絞り込みは各 fetcher が
    civilTime の日付で行う。

    pageSize は指定しない（list_data_points と同じ理由: 小さい値だと0件が
    返ることがある）。件数上限を設けず nextPageToken を最後まで辿る
    （打ち切りは欠測の捏造になる）。
    """
    lo = dt.datetime.combine(start_date, dt.time()) - FILTER_WINDOW_MARGIN
    hi = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time()) + FILTER_WINDOW_MARGIN
    lo_str = lo.strftime('%Y-%m-%dT%H:%M:%SZ')
    hi_str = hi.strftime('%Y-%m-%dT%H:%M:%SZ')
    filter_str = f'{filter_field} >= "{lo_str}" AND {filter_field} < "{hi_str}"'

    out = []
    token = None
    while True:
        params = {'filter': filter_str}
        if token:
            params['pageToken'] = token
        body = _get(creds, f'{USER}/dataTypes/{data_type}/dataPoints', params)
        out.extend(body.get('dataPoints', []))
        token = body.get('nextPageToken')
        if not token:
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
                end_date: dt.date, build, pick=None) -> list[dict]:
    """
    daily-* 型（既に日次集計済み）を期間で絞って行リストにする

    daily-* 型は dailyRollUp が 400 になるため list を使う。API 側に期間指定の
    filter はあるが構文が型ごとに異なるので、取得後にクライアント側で絞る。

    Args:
        pick: 同じ日付に複数 dataPoint が届く型向けのフック（例:
              daily-resting-heart-rate が FITBIT/HEALTH_CONNECT の2系統を
              返すケース、Issue #78）。None ならこれまで通り点ごとに1行作る
              （既存の hrv 等の挙動は変えない）。指定した場合は日付ごとに
              dataPoint をまとめ、`pick(points_of_that_date)` が返した1点だけを
              使う。pick が None を返した日付は行を作らない（欠測のまま残す）。
    """
    points = list_data_points(
        creds, data_type, stop_before=start_date, payload_key=payload_key
    )

    filtered = []
    for point in points:
        value = point.get(payload_key)
        if not value or 'date' not in value:
            continue
        date = _to_date(value['date'])
        if not (start_date.isoformat() <= date <= end_date.isoformat()):
            continue
        filtered.append((date, point))

    rows = []
    if pick is None:
        for date, point in filtered:
            row = build(point[payload_key])
            if row is not None:
                rows.append({'date': date, **row})
    else:
        by_date: dict[str, list[dict]] = {}
        for date, point in filtered:
            by_date.setdefault(date, []).append(point)
        for date, points_of_date in by_date.items():
            chosen = pick(points_of_date)
            if chosen is None:
                continue
            row = build(chosen[payload_key])
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
# 型ごとの fetch_* は分割先モジュールに実装し、ここでまとめて取り込む
# （下の import はここまでで core のプリミティブが定義済みであることに
# 依存するため、ファイル末尾に置く。分割先は `from . import googlehealth_api
# as api` で本モジュールを参照するだけなので、この時点で本モジュールが
# sys.modules に（未完成でも）登録されていれば循環importにはならない）
# =============================================================================

from .googlehealth_sleep import _list_sleep_points, fetch_sleep_all  # noqa: E402
from .googlehealth_sessions import (  # noqa: E402
    EXERCISE_COLUMNS, CAFFEINE_COLUMNS, WEIGHT_COLUMNS, BODY_FAT_COLUMNS,
    NUTRITION_COLUMNS, NUTRITION_LOG_COLUMNS,
    fetch_exercise, fetch_caffeine, fetch_weight, fetch_body_fat,
    fetch_nutrition, fetch_nutrition_logs,
)
from .googlehealth_daily import (  # noqa: E402
    fetch_hrv, fetch_breathing_rate, fetch_temperature_skin, fetch_heart_rate,
    fetch_spo2, fetch_activity, fetch_active_zone_minutes, fetch_temperature_core,
)
from .googlehealth_intraday import (  # noqa: E402
    fetch_heart_rate_intraday, fetch_steps_intraday, fetch_spo2_intraday,
    fetch_hrv_intraday, fetch_br_intraday,
)

# sleep は他と違い、1回の取得で sleep.csv / sleep_levels.csv の2つの行リストを
# 作るため (sleep_rows, level_rows) のタプルを返す。
# googlehealth_fetcher 側で戻り値の形を見て分岐する。
FETCHERS = {
    'hrv': fetch_hrv,
    'breathing_rate': fetch_breathing_rate,
    'temperature_skin': fetch_temperature_skin,
    'heart_rate': fetch_heart_rate,
    'spo2': fetch_spo2,
    'sleep': fetch_sleep_all,
    'activity': fetch_activity,
    'active_zone_minutes': fetch_active_zone_minutes,
    'temperature_core': fetch_temperature_core,
    'exercise': fetch_exercise,
    'caffeine': fetch_caffeine,
    'nutrition': fetch_nutrition,
    'nutrition_logs': fetch_nutrition_logs,
    'weight': fetch_weight,
    'body_fat': fetch_body_fat,
    'heart_rate_intraday': fetch_heart_rate_intraday,
    'steps_intraday': fetch_steps_intraday,
    'spo2_intraday': fetch_spo2_intraday,
    'hrv_intraday': fetch_hrv_intraday,
    'br_intraday': fetch_br_intraday,
}
