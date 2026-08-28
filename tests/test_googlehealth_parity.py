"""
Google Health API と既存 Fitbit CSV の一致テスト（Issue #49）

両 API が並行稼働している 2026年9月までしか実行できない検証。
Fitbit Web API 廃止後は、既存 CSV が「過去に Fitbit から取得した値」の
スナップショットとして残るため、このテストは回帰防止として機能し続ける。

認証情報が無い環境（CI 等）では skip する。
"""

import csv
import datetime as dt
import statistics
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


def _load_csv(name: str, key: str = 'date') -> dict[str, dict]:
    path = DATA_DIR / f'{name}.csv'
    if not path.exists():
        pytest.skip(f'{path} が無い')
    with path.open() as f:
        return {r[key]: r for r in csv.DictReader(f)}


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


# =============================================================================
# active_zone_minutes: ゾーン別3列は完全一致するため厳しい許容誤差で検証する
# （Issue #75）。activity は #70 の壊れた行があるため parity には含めない
# （PR 本文に理由あり）。
# =============================================================================

def test_active_zone_minutes_matches_existing_csv(creds):
    compared, mismatches = _compare(
        creds, 'active_zone_minutes',
        ['activeZoneMinutes', 'fatBurnActiveZoneMinutes', 'cardioActiveZoneMinutes',
         'peakActiveZoneMinutes'],
    )
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_fetchers_respect_date_range(creds):
    """期間指定が効いていること（範囲外の日付を返さないこと）"""
    start = dt.date.today() - dt.timedelta(days=10)
    end = dt.date.today() - dt.timedelta(days=5)
    for endpoint, fetcher in gh.FETCHERS.items():
        if endpoint == 'sleep':
            continue  # 専用テストで別途検証（戻り値の形が違う）
        # temperature_core は date_time（日時、実測時刻を含む）、exercise は
        # start（開始時刻）と、型ごとに date_column が違うので先頭10文字で見る
        column = googlehealth_fetcher.ENDPOINTS[endpoint]['date_column']
        rows = fetcher(creds, start, end)
        for row in rows:
            assert start.isoformat() <= row[column][:10] <= end.isoformat(), (
                f'{endpoint}: 範囲外の日付 {row[column]}'
            )


# =============================================================================
# sleep: 完全一致ではなく許容差付きの比較（Issue #74）
#
# Google は Fitbit が「覚醒」と判定する時間の一部を「浅い睡眠」に分類するため
# 完全一致しない（直近の窓で light +11分 / awake -10.5分 / deep ±0 程度、#49）。
# isMainSleep=True の行のみ dateOfSleep で対応づけて、中央値の差で判定する。
# =============================================================================

def _median_diff(rows: list[dict], old: dict[str, dict], column: str) -> float | None:
    diffs = []
    for row in rows:
        if not row.get('isMainSleep'):
            continue
        ref = old.get(row['dateOfSleep'])
        if ref is None or ref.get(column) in (None, ''):
            continue
        got = row.get(column)
        if got is None:
            continue
        diffs.append(float(got) - float(ref[column]))
    return statistics.median(diffs) if diffs else None


def _load_main_sleep_csv() -> dict[str, dict]:
    """既存 sleep.csv を dateOfSleep -> 行 の辞書にする（isMainSleep=True のみ）

    1日に複数行（昼寝含む）ありうるため、素の dateOfSleep キーでは
    衝突する。比較対象は isMainSleep=True の行だけに絞る。
    """
    path = DATA_DIR / 'sleep.csv'
    if not path.exists():
        pytest.skip(f'{path} が無い')
    with path.open() as f:
        return {r['dateOfSleep']: r for r in csv.DictReader(f) if r.get('isMainSleep') == 'True'}


def test_sleep_matches_existing_csv_within_tolerance(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    sleep_rows, _ = gh.fetch_sleep_all(creds, COMPARE_FROM, end)
    assert sleep_rows, 'sleep: Google から1件も取得できていない'

    old = _load_main_sleep_csv()

    tight = {'timeInBed': 5, 'deepMinutes': 5, 'remMinutes': 5}
    loose = {'lightMinutes': 30, 'minutesAwake': 30, 'minutesAsleep': 30}

    for column, tolerance in {**tight, **loose}.items():
        diff = _median_diff(sleep_rows, old, column)
        assert diff is not None, f'{column}: 比較対象が1件も無い'
        assert abs(diff) <= tolerance, (
            f'{column}: 中央値の差が許容範囲外 ({diff:+.1f}分、許容 ±{tolerance}分)'
        )


# =============================================================================
# weight / body_fat: HealthPlanet 実測との突き合わせ（Issue #94）
#
# #77 本文の「2026-06-01 以降で検証する」はこの系統では成立しない。比較対象の
# 既存 data/fitbit/body_weight.csv は 2024-04-23 で終わっており、2026-06 以降に
# 比較対象が無いため、HealthPlanet 実測（data/healthplanet_innerscan.csv）と
# 突き合わせる。
# =============================================================================

INNERSCAN_PATH = BASE_DIR / 'data' / 'healthplanet_innerscan.csv'


def _load_innerscan() -> dict[str, dict]:
    if not INNERSCAN_PATH.exists():
        pytest.skip(f'{INNERSCAN_PATH} が無い')
    with INNERSCAN_PATH.open() as f:
        return {r['date']: r for r in csv.DictReader(f)}


def test_weight_matches_healthplanet_innerscan(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    rows = gh.fetch_weight(creds, COMPARE_FROM, end)
    assert rows, 'weight: Google から1件も取得できていない'

    old = _load_innerscan()
    compared = 0
    mismatches = []
    for row in rows:
        ref = old.get(row['date'])
        if ref is None or ref.get('weight') in (None, ''):
            continue
        compared += 1
        got, want = row['weight_kg'], float(ref['weight'])
        if abs(got - want) > 0.05:
            mismatches.append(f"{row['date']}: Google={got} innerscan={want}")

    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_body_fat_matches_healthplanet_innerscan(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    rows = gh.fetch_body_fat(creds, COMPARE_FROM, end)
    assert rows, 'body_fat: Google から1件も取得できていない'

    old = _load_innerscan()
    compared = 0
    mismatches = []
    for row in rows:
        ref = old.get(row['date'])
        if ref is None or ref.get('body_fat_rate') in (None, ''):
            continue
        compared += 1
        got, want = row['body_fat_rate'], float(ref['body_fat_rate'])
        if abs(got - want) > 0.05:
            mismatches.append(f"{row['date']}: Google={got} innerscan={want}")

    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


# =============================================================================
# nutrition / nutrition_logs（Issue #95）
#
# nutrition-log には日次サマリのデータ型が存在しないため、nutrition.csv は
# 食事ログの合算で作っている。既存 data/fitbit/nutrition.csv は2026-03以降
# ほぼ全行が Fitbit 経路の未記録日ダミー行（全項目0）で、Google 側に実データが
# ある日と衝突する（実例: 2026-02-26 は Google 1542 kcal に対し CSV は 0）。
# そのため既存 CSV 側が全項目0の行は比較対象から外す。
#
# nutrition_logs.csv は既存 CSV が2026-02-01で終わっているため、実データの
# ある 2025-12-12〜2026-02-01 で logId をキーに突き合わせる。
# protein/fat/carbs/fiber/sodium は既存 CSV では空だが Google 側では埋まる
# （情報が増える方向で不一致ではない）ため比較しない。
# =============================================================================

def _is_all_zero_nutrition_row(ref: dict) -> bool:
    """Fitbit 経路が未記録日に書いた「全項目0の行」か

    calories/carbs/fat/fiber/protein/sodium がすべて0（水は対象外）。
    実データではない可能性が高いため parity の比較対象から外す。
    """
    cols = ('calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium')
    try:
        return all(float(ref.get(c) or 0) == 0 for c in cols)
    except (TypeError, ValueError):
        return False


def test_nutrition_matches_existing_csv(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    rows = gh.fetch_nutrition(creds, COMPARE_FROM, end)
    assert rows, 'nutrition: Google から1件も取得できていない'

    old = _load_csv('nutrition')
    columns = ['calories', 'carbs', 'fat', 'fiber', 'protein', 'sodium']
    compared = 0
    mismatches = []
    for row in rows:
        ref = old.get(row['date'])
        if ref is None or _is_all_zero_nutrition_row(ref):
            continue
        for col in columns:
            got, want = row.get(col), ref.get(col)
            if want in (None, '') or got is None:
                continue
            compared += 1
            if abs(float(got) - float(want)) > 0.01:
                mismatches.append(f"{row['date']} {col}: Google={got} CSV={want}")

    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


NUTRITION_LOGS_COMPARE_FROM = dt.date(2025, 12, 12)
NUTRITION_LOGS_COMPARE_TO = dt.date(2026, 2, 1)


def test_nutrition_logs_matches_existing_csv(creds):
    """既存 nutrition_logs.csv は2026-02-01が最終行のため、実データのある
    2025-12-12〜2026-02-01 の期間に限って logId で突き合わせる"""
    rows = gh.fetch_nutrition_logs(creds, NUTRITION_LOGS_COMPARE_FROM, NUTRITION_LOGS_COMPARE_TO)
    assert rows, 'nutrition_logs: Google から1件も取得できていない'

    old = _load_csv('nutrition_logs', key='logId')
    # protein/fat/carbs/fiber/sodium は既存CSVでは空だがGoogle側では埋まる
    # （情報が増える方向なので不一致ではない）。比較しない
    columns = ['logDate', 'foodId', 'foodName', 'mealTypeId', 'amount', 'unitId',
              'unitName', 'calories']
    compared = 0
    mismatches = []
    for row in rows:
        ref = old.get(row['logId'])
        if ref is None:
            continue
        for col in columns:
            got, want = row.get(col), ref.get(col)
            if want in (None, '') or got is None:
                continue
            compared += 1
            try:
                if abs(float(got) - float(want)) > 0.01:
                    mismatches.append(f"{row['logId']} {col}: Google={got} CSV={want}")
            except (TypeError, ValueError):
                if str(got) != str(want):
                    mismatches.append(f"{row['logId']} {col}: Google={got} CSV={want}")

    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'
