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

from lib.clients import googlehealth_api as gh

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data' / 'wearable'

# 2026-06 より前は Google 側が値を再計算しており一致しない（Issue #49 / #50）
COMPARE_FROM = dt.date(2026, 6, 1)


# net: Google の API を実際に叩くので既定のスイートからは外れる（pyproject の
# addopts）。`uv run pytest tests -q -m net` で回す。
pytestmark = [
    pytest.mark.net,
    pytest.mark.skipif(
        not gh.TOKEN_FILE.exists(),
        reason='config/googlehealth_token.json が無い',
    ),
]


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


def test_heart_rate_matches_existing_csv(creds):
    compared, mismatches = _compare(creds, 'heart_rate', ['resting_heart_rate'])
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_spo2_matches_existing_csv(creds):
    compared, mismatches = _compare(
        creds, 'spo2', ['avg_spo2', 'min_spo2', 'max_spo2'], tolerance=0.051,
    )
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


# =============================================================================
# lag(-1/0/+1) の恒久検証（Issue #78 AC 5）。
#
# 2026-06-01以降で daily 型を突き合わせ、最も一致件数の多い lag が 0 で
# あることを確認する。spo2 は Google の日付ラベルが1日ずれる型だが、
# fetch_spo2 が睡眠セッションの引き当てで解決済みの日付を返すため、ここでは
# lag 0 になるはずである（解決前の生の Google 日付ではなく、fetcher の
# 出力を検証している点に注意）。
#
# activity は対象外: #70 の部分日破損により値そのものが一致しないため、
# 日付ズレの有無を検出する目的のこのテストには使えない（PR 本文に記載）。
# =============================================================================

def _lag_match_counts(rows: list[dict], old: dict[str, dict], columns: list[str],
                      tolerance: float = 0.001) -> dict[int, int]:
    """各 lag（rowの日付をずらした先）で CSV と一致する件数を数える"""
    counts = {-1: 0, 0: 0, 1: 0}
    for row in rows:
        row_date = dt.date.fromisoformat(row['date'])
        for lag in counts:
            shifted = (row_date + dt.timedelta(days=lag)).isoformat()
            ref = old.get(shifted)
            if ref is None:
                continue
            ok = True
            for col in columns:
                got, want = row.get(col), ref.get(col)
                if want in (None, '') or got is None or abs(float(got) - float(want)) > tolerance:
                    ok = False
                    break
            if ok:
                counts[lag] += 1
    return counts


def test_no_date_lag_in_daily_types(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    specs = [
        ('hrv', ['daily_rmssd', 'deep_rmssd'], 0.001),
        ('breathing_rate', ['breathing_rate'], 0.001),
        ('temperature_skin', ['nightly_relative'], 0.051),
        ('active_zone_minutes',
         ['activeZoneMinutes', 'fatBurnActiveZoneMinutes',
          'cardioActiveZoneMinutes', 'peakActiveZoneMinutes'], 0.001),
        ('heart_rate', ['resting_heart_rate'], 0.001),
        ('spo2', ['avg_spo2', 'min_spo2', 'max_spo2'], 0.051),
    ]
    failures = []
    for endpoint, columns, tolerance in specs:
        rows = gh.FETCHERS[endpoint](creds, COMPARE_FROM, end)
        old = _load_csv(endpoint)
        counts = _lag_match_counts(rows, old, columns, tolerance)
        best_lag = max(counts, key=lambda lag: counts[lag])
        if best_lag != 0:
            failures.append(f'{endpoint}: 最多一致 lag={best_lag:+d} ({counts})')
    assert not failures, '日付ズレを検出: ' + '; '.join(failures)


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
# 既存 data/wearable/body_weight.csv は 2024-04-23 で終わっており、2026-06 以降に
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
# 食事ログの合算で作っている。既存 data/wearable/nutrition.csv は2026-03以降
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


# =============================================================================
# intraday 5種（Issue #76）
#
# 既存の _compare は日付キー前提（1日1行）だが intraday は1分ごとに複数行
# あるため、datetime キーで突き合わせる専用ヘルパーを使う。共通するキーだけを
# 比較し、片側にしか無いキーは比較対象外にする（Google と既存CSVの点集合が
# 完全に一致するとは限らないため。特に spo2/hrv は intraday の元となる
# データ自体がどちらかにしか無い点を持ちうる）。
# =============================================================================

def _compare_intraday(rows: list[dict], old: dict[str, dict], key: str,
                      columns: list[str], tolerance: float = 0.001):
    """intraday の行リストと既存CSVを datetime（または date）キーで突き合わせる"""
    mismatches = []
    compared = 0
    for row in rows:
        ref = old.get(row[key])
        if ref is None:
            continue
        for col in columns:
            got, want = row.get(col), ref.get(col)
            if want in (None, '') or got is None:
                continue
            compared += 1
            if abs(float(got) - float(want)) > tolerance:
                mismatches.append(f"{row[key]} {col}: Google={got} CSV={want}")
    return compared, mismatches


def test_steps_intraday_never_exceeds_existing_csv(creds):
    """取得元を絞り損ねた二重計上（3.6倍）を検出する

    完全一致では見ない。Fitbit の既存 CSV は Charge 6 に記録が無い分だけ
    MobileTrack（スマホ）の歩数で埋めており、Google の点からは「トラッカーが
    0を記録した」と「記録が無い」を区別できないため再現できない。実測
    （2026-09-03〜04の2,880分）で不一致は2分・計9歩、すべて Google < CSV。

    危険なのは逆向き（Google > CSV = 二重計上）なので、そちらを0件で縛り、
    取り逃し側は総歩数の1%以内に収まることだけを見る。
    """
    end = dt.date.today() - dt.timedelta(days=1)
    start = max(end - dt.timedelta(days=1), COMPARE_FROM)
    rows = gh.FETCHERS['steps_intraday'](creds, start, end)
    assert rows, 'steps_intraday: Google から1件も取得できていない'

    old = _load_csv('steps_intraday', key='datetime')
    compared = 0
    over = []
    google_total = csv_total = 0
    for row in rows:
        ref = old.get(row['datetime'])
        if ref is None or ref.get('steps') in (None, ''):
            continue
        compared += 1
        got, want = int(row['steps']), int(ref['steps'])
        google_total += got
        csv_total += want
        if got > want:
            over.append(f"{row['datetime']}: Google={got} CSV={want}")

    assert compared > 0, '比較対象が1件も無い'
    assert not over, f'既存CSVを超える分がある（二重計上）: {len(over)}件 {over[:5]}'
    assert csv_total > 0, '既存CSV側の歩数が0で、比較が成立していない'
    shortfall = (csv_total - google_total) / csv_total
    assert shortfall < 0.01, \
        f'取り逃しが総歩数の1%を超える: Google={google_total} CSV={csv_total}'


def test_spo2_intraday_matches_existing_csv(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    start = max(end - dt.timedelta(days=1), COMPARE_FROM)
    rows = gh.FETCHERS['spo2_intraday'](creds, start, end)
    assert rows, 'spo2_intraday: Google から1件も取得できていない'

    old = _load_csv('spo2_intraday', key='datetime')
    compared, mismatches = _compare_intraday(rows, old, 'datetime', ['spo2'], tolerance=0.051)
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_hrv_intraday_matches_existing_csv(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    start = max(end - dt.timedelta(days=1), COMPARE_FROM)
    rows = gh.FETCHERS['hrv_intraday'](creds, start, end)
    assert rows, 'hrv_intraday: Google から1件も取得できていない'

    old = _load_csv('hrv_intraday', key='datetime')
    compared, mismatches = _compare_intraday(rows, old, 'datetime', ['rmssd'])
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_br_intraday_matches_existing_csv(creds):
    end = dt.date.today() - dt.timedelta(days=1)
    start = max(end - dt.timedelta(days=1), COMPARE_FROM)
    rows = gh.FETCHERS['br_intraday'](creds, start, end)
    assert rows, 'br_intraday: Google から1件も取得できていない'

    old = _load_csv('br_intraday', key='date')
    columns = ['br_full_sleep', 'br_deep', 'br_light', 'br_rem']
    compared, mismatches = _compare_intraday(rows, old, 'date', columns, tolerance=0.051)
    assert compared > 0, '比較対象が1件も無い'
    assert not mismatches, f'{len(mismatches)}件の不一致: {mismatches[:5]}'


def test_heart_rate_intraday_matches_existing_csv(creds):
    """比較の窓は「現在時刻の直近1時間」ではなく既存CSVの最終行から取る

    CSV は最後に取得を回した時点までしか無いので、現在時刻から窓を切ると
    重なりが0件になり `compared == 0` で落ちる（実際に落ちた）。CSV の
    最終 datetime で終わる1時間を窓にすれば必ず重なる。

    Google 側は日付単位でしか引けず1日分は約8分かかるため、CSV 最終行の
    日付1日だけを取得して、そのうち最後の1時間を突き合わせる。
    """
    old = _load_csv('heart_rate_intraday', key='datetime')
    csv_max = max(old)
    target_date = dt.date.fromisoformat(csv_max[:10])
    if target_date < COMPARE_FROM:
        pytest.skip(f'既存CSVの最終行 {csv_max} が COMPARE_FROM より前')

    rows = gh.FETCHERS['heart_rate_intraday'](creds, target_date, target_date)
    assert rows, 'heart_rate_intraday: Google から1件も取得できていない'

    window_start = (dt.datetime.fromisoformat(csv_max)
                    - dt.timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
    rows = [r for r in rows if window_start <= r['datetime'] <= csv_max]

    compared, mismatches = _compare_intraday(rows, old, 'datetime', ['heart_rate'])
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
