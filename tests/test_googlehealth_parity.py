"""
Google Health API と既存 Fitbit CSV の一致テスト（Issue #49）

両 API が並行稼働している 2026年9月までしか実行できない検証。
Fitbit Web API 廃止後は、既存 CSV が「過去に Fitbit から取得した値」の
スナップショットとして残るため、このテストは回帰防止として機能し続ける。

認証情報が無い環境（CI 等）では skip する。
"""

import csv
import datetime as dt
from pathlib import Path

import pytest

from lib import googlehealth_fetcher
from lib.clients import googlehealth_api as gh

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data' / 'fitbit'

# 2026-06 より前は Google 側が値を再計算しており一致しない（Issue #49 / #50）
COMPARE_FROM = dt.date(2026, 6, 1)


pytestmark = pytest.mark.skipif(
    not gh.TOKEN_FILE.exists(),
    reason='config/googlehealth_token.json が無い',
)


@pytest.fixture(scope='module')
def creds():
    try:
        return gh.authorize(interactive=False)
    except gh.GoogleHealthError as e:
        pytest.skip(str(e))


def _load_csv(name: str) -> dict[str, dict]:
    path = DATA_DIR / f'{name}.csv'
    if not path.exists():
        pytest.skip(f'{path} が無い')
    with path.open() as f:
        return {r['date']: r for r in csv.DictReader(f)}


def _compare(creds, endpoint: str, columns: list[str], tolerance: float = 0.001):
    """Google の取得結果と既存 CSV を突き合わせ、不一致を返す"""
    end = dt.date.today() - dt.timedelta(days=1)  # 当日は未確定なので除く
    rows = gh.FETCHERS[endpoint](creds, COMPARE_FROM, end)
    assert rows, f'{endpoint}: Google から1件も取得できていない'

    old = _load_csv(endpoint)
    mismatches = []
    compared = 0
    for row in rows:
        ref = old.get(row['date'])
        if ref is None:
            continue
        for col in columns:
            got, want = row.get(col), ref.get(col)
            if want in (None, '') or got is None:
                continue
            compared += 1
            if abs(float(got) - float(want)) > tolerance:
                mismatches.append(f"{row['date']} {col}: Google={got} CSV={want}")
    return compared, mismatches


def test_hrv_matches_existing_csv(creds):
    compared, mismatches = _compare(creds, 'hrv', ['daily_rmssd', 'deep_rmssd'])
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_breathing_rate_matches_existing_csv(creds):
    compared, mismatches = _compare(creds, 'breathing_rate', ['breathing_rate'])
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_temperature_skin_matches_existing_csv(creds):
    # nightly_relative は小数第1位に丸めた値なので許容誤差を広げる
    compared, mismatches = _compare(
        creds, 'temperature_skin', ['nightly_relative'], tolerance=0.051
    )
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_fetchers_respect_date_range(creds):
    """期間指定が効いていること（範囲外の日付を返さないこと）"""
    start = dt.date.today() - dt.timedelta(days=10)
    end = dt.date.today() - dt.timedelta(days=5)
    for endpoint in gh.FETCHERS:
        # セッション型（exercise）は日次でなく開始時刻を持つので先頭10文字で見る
        column = googlehealth_fetcher.ENDPOINTS[endpoint]['date_column']
        rows = gh.FETCHERS[endpoint](creds, start, end)
        for row in rows:
            assert start.isoformat() <= row[column][:10] <= end.isoformat(), (
                f'{endpoint}: 範囲外の日付 {row[column]}'
            )
