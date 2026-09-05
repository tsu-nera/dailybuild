#!/usr/bin/env python
# coding: utf-8
"""
Google Health intraday 型 -> data/fitbit/*_intraday.csv（Issue #76）

googlehealth_client.py から分割（ファイルサイズ hook の 500行上限対応）。
daily-* 型と違い intraday は `list` の `filter` クエリで期間を絞る
（`googlehealth_client.list_filtered_points` 参照）。`_get` はそちら経由で
呼ばれるため、ここで直接 monkeypatch する必要はない。

civilTime の扱いは googlehealth_daily.py と共通（`_civil_time_str` を
再利用する）。
"""

import datetime as dt

from . import googlehealth_client as api
from . import googlehealth_daily as daily
from .googlehealth_client import _num


def _civil_minute_key(civil: dict) -> str:
    """civilTime（またはそれと同形の civilStartTime）を "YYYY-MM-DD HH:MM" にする

    分バケット用のキー。秒は捨てる。civilTime.time は hours/minutes/seconds
    が0のとき省略されるため .get(key, 0) で補う。
    """
    date = civil['date']
    time = civil.get('time') or {}
    return (
        f"{date['year']:04d}-{date['month']:02d}-{date['day']:02d} "
        f"{time.get('hours', 0):02d}:{time.get('minutes', 0):02d}"
    )


# =============================================================================
# 心拍数（分刻み） -> data/fitbit/heart_rate_intraday.csv
# =============================================================================

def fetch_heart_rate_intraday(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: datetime, heart_rate

    Google の生サンプルは1〜3秒粒度、既存 CSV は1分。civilTime の分で
    バケットし、**切り捨て平均（int(mean)）** で1分値にする。round ではない:
    実測（JST 2026-08-24 03:00-05:00、2,744点）で int(mean) は既存CSVの
    120分と120/120一致するが、round(mean) は74/120しか一致しない。

    **fetch_all から除外している（ENDPOINTS の exclude_from_all）。** 生サンプルは
    1日あたり約33,000点=約660ページ=約8分かかり、既存CSVの起点2024-12-01まで
    遡ると約84時間になるため、バックフィルはしない（既存CSVを保持するのみ）。
    `--endpoint heart_rate_intraday` で明示指定したときだけ取る。
    """
    points = api.list_filtered_points(
        creds, 'heart-rate', 'heart_rate.sample_time.physical_time', start_date, end_date,
    )

    buckets: dict[str, list[float]] = {}
    for point in points:
        payload = point.get('heartRate')
        if not payload:
            continue
        civil = (payload.get('sampleTime') or {}).get('civilTime')
        if not civil:
            continue
        date_part = api._to_date(civil['date'])
        if not (start_date.isoformat() <= date_part <= end_date.isoformat()):
            continue
        bpm = _num(payload.get('beatsPerMinute'))
        if bpm is None:
            continue
        buckets.setdefault(_civil_minute_key(civil), []).append(bpm)

    rows = [
        {'datetime': f'{minute_key}:00', 'heart_rate': int(sum(values) / len(values))}
        for minute_key, values in buckets.items()
    ]
    rows.sort(key=lambda r: r['datetime'])
    return rows


# =============================================================================
# 歩数（分刻み） -> data/fitbit/steps_intraday.csv
# =============================================================================

# 実測（JST 2026-09-01）: steps の dataPoints には同じ歩数が4系統から届く。
# platform=FITBIT かつ device.displayName != "MobileTrack" のみ採用すると
# 既存CSVと1440/1440完全一致。他3系統（FITBIT/MobileTrack、
# HEALTH_CONNECT×2アプリ）を混ぜると素の合算で3.6倍（11,855歩 vs 既存3,260歩）
# に膨れる。他4種（heart-rate/oxygen-saturation/heart-rate-variability/
# respiratory-rate-sleep-summary）は同日の実測で FITBIT/Charge 6 の単一系統
# しか返らないため、取得元の絞り込みは steps だけでよい。
_STEPS_EXCLUDED_DEVICE = 'MobileTrack'


def _is_authoritative_steps_source(data_source: dict) -> bool:
    if (data_source or {}).get('platform') != 'FITBIT':
        return False
    device_name = (data_source.get('device') or {}).get('displayName')
    return device_name != _STEPS_EXCLUDED_DEVICE


def fetch_steps_intraday(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: datetime, steps

    各点は interval（civilStartTime）と count を持つ。civilStartTime の
    分バケットに count を丸ごと加算する（比例配分ではない。この規則で
    既存CSVと1440/1440一致することを実測済み）。

    Google は非0区間しか返さないため、既存CSV（1440行中1359行が0）と
    同一スキーマにするにはゼロ埋めが要る。**過去日は00:00〜23:59の1440分
    すべて、当日はローカル現在時刻の分まで**（未来の分を0で埋めると
    欠測の捏造になる）。**1点も返らなかった日はゼロ埋めしない**（同上）。

    既存CSVと完全には一致しない残差がある: Fitbit は Charge 6 に記録が無い
    分だけ MobileTrack（スマホ）の歩数で埋めており、Google 側の点からは
    「トラッカーが0を記録した」と「記録が無い」を区別できないため再現できない。
    実測（2026-09-03〜04の2,880分）で不一致は2分・計9歩、いずれも
    Google=0 / CSV>0 の方向のみ（過大計上は0件）。
    """
    points = api.list_filtered_points(
        creds, 'steps', 'steps.interval.start_time', start_date, end_date,
    )

    minute_counts: dict[str, int] = {}
    for point in points:
        if not _is_authoritative_steps_source(point.get('dataSource')):
            continue
        payload = point.get('steps')
        if not payload:
            continue
        civil_start = (payload.get('interval') or {}).get('civilStartTime')
        if not civil_start:
            continue
        date_part = api._to_date(civil_start['date'])
        if not (start_date.isoformat() <= date_part <= end_date.isoformat()):
            continue
        count = _num(payload.get('count'))
        if count is None:
            continue
        key = _civil_minute_key(civil_start)
        minute_counts[key] = minute_counts.get(key, 0) + int(count)

    today = dt.date.today()
    now = dt.datetime.now()
    days_with_data = {key[:10] for key in minute_counts}

    rows = []
    day = start_date
    while day <= end_date:
        if day > today:
            break  # 未来日は作らない
        # Google が1点も返さなかった日はゼロ埋めしない。保存はキーマージなので
        # 0 は「値がある」として既存の実測値を上書きしてしまう。取得の沈黙故障
        # （filter の誤り・同期前）と「本当に1歩も歩いていない日」は区別できず、
        # 埋めた側に倒すと1日ぶんの歩数が黙って消える
        if day.isoformat() not in days_with_data:
            day += dt.timedelta(days=1)
            continue
        last_minute = 1439 if day < today else now.hour * 60 + now.minute
        for minute in range(last_minute + 1):
            hh, mm = divmod(minute, 60)
            key = f'{day.isoformat()} {hh:02d}:{mm:02d}'
            rows.append({'datetime': f'{key}:00', 'steps': minute_counts.get(key, 0)})
        day += dt.timedelta(days=1)
    return rows


# =============================================================================
# SpO2（分刻み） -> data/fitbit/spo2_intraday.csv
# =============================================================================

def fetch_spo2_intraday(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: datetime, spo2

    civilTime をそのまま datetime に、percentage を spo2 にする。保存は
    キーマージ（merge_csv）。Google 側に無く既存CSVにだけある点があっても
    キーマージなので既存行は消えない（期間置換にしないこと）。
    """
    points = api.list_filtered_points(
        creds, 'oxygen-saturation', 'oxygen_saturation.sample_time.physical_time',
        start_date, end_date,
    )

    rows = []
    for point in points:
        payload = point.get('oxygenSaturation')
        if not payload:
            continue
        civil = (payload.get('sampleTime') or {}).get('civilTime')
        if not civil:
            continue
        date_part = api._to_date(civil['date'])
        if not (start_date.isoformat() <= date_part <= end_date.isoformat()):
            continue
        percentage = _num(payload.get('percentage'))
        if percentage is None:
            continue
        rows.append({'datetime': daily._civil_time_str(civil), 'spo2': percentage})

    rows.sort(key=lambda r: r['datetime'])
    return rows


# =============================================================================
# HRV（分刻み） -> data/fitbit/hrv_intraday.csv
# =============================================================================

def fetch_hrv_intraday(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: datetime, rmssd

    既存 hrv_intraday.csv は coverage / hf / lf / lf_hf_ratio も持つが、
    Google には対応するフィールドが無いため rmssd だけを返す。
    **保存はキーマージ（merge_csv）にすること。** merge_csv はセル単位で
    df_new が NaN の列を df_old で補完するため、この4列の既存値は残る。
    期間置換（replace_csv_period）にすると行ごと置き換わり4列が消える。
    """
    points = api.list_filtered_points(
        creds, 'heart-rate-variability', 'heart_rate_variability.sample_time.physical_time',
        start_date, end_date,
    )

    rows = []
    for point in points:
        payload = point.get('heartRateVariability')
        if not payload:
            continue
        civil = (payload.get('sampleTime') or {}).get('civilTime')
        if not civil:
            continue
        date_part = api._to_date(civil['date'])
        if not (start_date.isoformat() <= date_part <= end_date.isoformat()):
            continue
        rmssd = _num(payload.get('rootMeanSquareOfSuccessiveDifferencesMilliseconds'))
        if rmssd is None:
            continue
        rows.append({'datetime': daily._civil_time_str(civil), 'rmssd': rmssd})

    rows.sort(key=lambda r: r['datetime'])
    return rows


# =============================================================================
# 呼吸数（睡眠、日次） -> data/fitbit/br_intraday.csv
# =============================================================================

def fetch_br_intraday(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date, br_full_sleep, br_deep, br_light, br_rem

    1つの civil date に複数の点が届くことがある（実測: 2026-08-21は5点）。
    deep/rem/full は同値だが light だけ揺れる。**civil date ごとに
    physicalTime が最も早い点を採る**（2026-06-01〜08-26の60日で実測:
    最早点60/60一致、最新点45/60）。
    """
    points = api.list_filtered_points(
        creds, 'respiratory-rate-sleep-summary',
        'respiratory_rate_sleep_summary.sample_time.physical_time', start_date, end_date,
    )

    earliest_by_date: dict[str, tuple[str, dict]] = {}  # date -> (physicalTime, payload)
    for point in points:
        payload = point.get('respiratoryRateSleepSummary')
        if not payload:
            continue
        sample_time = payload.get('sampleTime') or {}
        civil = sample_time.get('civilTime')
        physical_time = sample_time.get('physicalTime')
        if not civil or not physical_time:
            continue
        date_part = api._to_date(civil['date'])
        if not (start_date.isoformat() <= date_part <= end_date.isoformat()):
            continue
        existing = earliest_by_date.get(date_part)
        if existing is None or physical_time < existing[0]:
            earliest_by_date[date_part] = (physical_time, payload)

    rows = []
    for date_part, (_physical_time, payload) in sorted(earliest_by_date.items()):
        deep = payload.get('deepSleepStats') or {}
        light = payload.get('lightSleepStats') or {}
        rem = payload.get('remSleepStats') or {}
        full = payload.get('fullSleepStats') or {}
        rows.append({
            'date': date_part,
            'br_full_sleep': _num(full.get('breathsPerMinute')),
            'br_deep': _num(deep.get('breathsPerMinute')),
            'br_light': _num(light.get('breathsPerMinute')),
            'br_rem': _num(rem.get('breathsPerMinute')),
        })
    return rows
