"""
Google Health の期間フィルタ（ネットワーク不要）

API は dataPoints を**新しい順・期間指定なし**で返すので、期間で絞るのは
こちら側のコード。ここを間違えると範囲外の日付が CSV に混ざる。sleep と
temperature_core は保存が期間置換（replace_csv_period）なので、範囲が
ずれた瞬間に**取り替えるつもりのなかった日を消す**。欠測の捏造そのもの。

境界の判定が `_daily_rows` と各 fetcher に**同じ形で4箇所に複製**されている
（exercise / sleep / temperature_core / caffeine）ので、1箇所直して他を
忘れる壊れ方をする。

以前は test_googlehealth_parity.py::test_fetchers_respect_date_range が実 API で
これを見ていたが、19.9秒（スイート全体の47%）かかるうえ、Google が実際に返す
データ次第で境界を1度も踏まないことがある。フェイクなら範囲外の点が必ず
含まれることを保証できるので、速いだけでなく検査としても強い。
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.clients import googlehealth_api as gh

START = dt.date(2026, 8, 30)
END = dt.date(2026, 9, 3)
CREDS = object()   # フェイクした _get は creds を見ない


def fake_get(*pages):
    """_get を差し替える。ページを順に返し、最後だけ nextPageToken を落とす"""
    calls = []

    def _fake(creds, path, params=None):
        index = len(calls)
        calls.append(params)
        body = {'dataPoints': list(pages[index])}
        if index + 1 < len(pages):
            body['nextPageToken'] = f'page{index + 1}'
        return body

    _fake.calls = calls
    return _fake


def civil(day: str) -> dict:
    y, m, d = (int(x) for x in day.split('-'))
    return {'year': y, 'month': m, 'day': d}


# --- _daily_rows（hrv / breathing_rate / temperature_skin が共有）----------

def daily_point(day: str, value: float) -> dict:
    return {'payload': {'date': civil(day), 'value': value}}


def call_daily_rows():
    return gh._daily_rows(CREDS, 'dummy-type', 'payload', START, END,
                          lambda v: {'value': v['value']})


def test_daily_rows_drops_dates_outside_the_window(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        daily_point('2026-08-28', 1),   # start より前
        daily_point('2026-08-30', 2),   # start ちょうど
        daily_point('2026-09-01', 3),
        daily_point('2026-09-03', 4),   # end ちょうど
        daily_point('2026-09-05', 5),   # end より後
    ]))
    assert [r['date'] for r in call_daily_rows()] == [
        '2026-08-30', '2026-09-01', '2026-09-03']


def test_daily_rows_stops_paging_once_a_page_is_entirely_older(monkeypatch):
    """全履歴を毎回引くと数分かかる。打ち切りが効かないと日次実行が破綻する"""
    fake = fake_get(
        [daily_point('2026-08-20', 1)],   # 全部 start より古い
        [daily_point('2026-09-01', 2)],   # ここまで来てはいけない
    )
    monkeypatch.setattr(gh, '_get', fake)

    assert call_daily_rows() == []
    assert len(fake.calls) == 1


def test_daily_rows_keeps_paging_when_a_page_touches_the_boundary(monkeypatch):
    """start ちょうどの日は「より古い」ではない。ここを < にすると1日落ちる"""
    fake = fake_get(
        [daily_point('2026-08-30', 1)],
        [daily_point('2026-09-01', 2)],
    )
    monkeypatch.setattr(gh, '_get', fake)

    assert [r['date'] for r in call_daily_rows()] == ['2026-08-30', '2026-09-01']
    assert len(fake.calls) == 2


def test_daily_rows_ignores_points_without_a_date(monkeypatch):
    """日付を持たない点で例外にせず、かつ日付ありとして数えない"""
    monkeypatch.setattr(gh, '_get', fake_get([
        {'payload': {'value': 1}},
        daily_point('2026-09-01', 2),
    ]))
    assert [r['date'] for r in call_daily_rows()] == ['2026-09-01']


# --- fetch_temperature_core（期間置換で保存されるので範囲ずれが致命的）-----

def core_point(day: str, hour: int = 5) -> dict:
    return {'coreBodyTemperature': {
        'sampleTime': {'civilTime': {'date': civil(day),
                                     'time': {'hours': hour, 'minutes': 49}}},
        'temperatureCelsius': 36.1,
    }}


def test_temperature_core_drops_dates_outside_the_window(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        core_point('2026-08-29'),
        core_point('2026-08-30'),
        core_point('2026-09-03'),
        core_point('2026-09-04'),
    ]))
    rows = gh.fetch_temperature_core(CREDS, START, END)
    assert [r['date_time'][:10] for r in rows] == ['2026-08-30', '2026-09-03']


def test_temperature_core_stops_paging_once_a_page_is_entirely_older(monkeypatch):
    fake = fake_get([core_point('2026-08-01')], [core_point('2026-09-01')])
    monkeypatch.setattr(gh, '_get', fake)

    assert gh.fetch_temperature_core(CREDS, START, END) == []
    assert len(fake.calls) == 1


# --- fetch_exercise ------------------------------------------------------

def exercise_point(day: str, name: str = 'a') -> dict:
    return {
        'name': f'users/me/dataPoints/{name}',
        'exercise': {
            'interval': {'startTime': f'{day}T10:00:00Z',
                         'endTime': f'{day}T11:00:00Z',
                         'startUtcOffset': '0s'},
        },
        'dataSource': {'platform': 'FITBIT'},
    }


def test_exercise_drops_dates_outside_the_window(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        exercise_point('2026-08-29', 'old'),
        exercise_point('2026-08-30', 'a'),
        exercise_point('2026-09-03', 'b'),
        exercise_point('2026-09-04', 'new'),
    ]))
    rows = gh.fetch_exercise(CREDS, START, END)
    assert [r['start'][:10] for r in rows] == ['2026-08-30', '2026-09-03']


def test_exercise_stops_paging_once_a_page_is_entirely_older(monkeypatch):
    fake = fake_get([exercise_point('2026-08-01')], [exercise_point('2026-09-01')])
    monkeypatch.setattr(gh, '_get', fake)

    assert gh.fetch_exercise(CREDS, START, END) == []
    assert len(fake.calls) == 1


# --- fetch_caffeine ------------------------------------------------------
#
# 打ち切り判定だけが他と違う。CAFFEINE 行だけで判定すると、記録が疎なので
# 「CAFFEINE 行が1件も無いページ」で打ち切れず全履歴を引き切ってしまう。
# 判定は CAFFEINE の有無に関わらずページ内の全 dataPoint の日付で行う。

def nutrition_point(day: str, caffeine: bool = True) -> dict:
    nutrients = [{'nutrient': 'CAFFEINE', 'quantity': {'grams': 0.08}}] if caffeine \
        else [{'nutrient': 'PROTEIN', 'quantity': {'grams': 20}}]
    return {
        'name': f'users/me/dataPoints/{day}',
        'nutritionLog': {
            'interval': {'startTime': f'{day}T08:00:00Z', 'startUtcOffset': '0s'},
            'nutrients': nutrients,
        },
        'dataSource': {'application': {}},
    }


def test_caffeine_drops_dates_outside_the_window(monkeypatch):
    monkeypatch.setattr(gh, '_get', fake_get([
        nutrition_point('2026-08-29'),
        nutrition_point('2026-08-30'),
        nutrition_point('2026-09-03'),
        nutrition_point('2026-09-04'),
    ]))
    rows = gh.fetch_caffeine(CREDS, START, END)
    assert [r['date'] for r in rows] == ['2026-08-30', '2026-09-03']


def test_caffeine_stops_paging_on_pages_without_any_caffeine_row(monkeypatch):
    """CAFFEINE 行が無いページでも打ち切れること。効かないと全履歴を引く"""
    fake = fake_get(
        [nutrition_point('2026-08-01', caffeine=False)],
        [nutrition_point('2026-09-01')],
    )
    monkeypatch.setattr(gh, '_get', fake)

    assert gh.fetch_caffeine(CREDS, START, END) == []
    assert len(fake.calls) == 1
