#!/usr/bin/env python
# coding: utf-8
"""
Google Health daily-* 型 -> data/fitbit/*.csv

googlehealth_client.py から分割（Issue #78。ファイルサイズ hook の 500行上限対応）。
`_get`/`_post` 等の共通プリミティブはテストが `googlehealth_client.<name>` を
直接 monkeypatch する前提だが、それらは core（googlehealth_client.py）に定義が
残っているため、ここで static import した `_daily_rows` 等の呼び出し経路
自体はテストの monkeypatch に影響されない（関数の定義場所が呼び出し先の
名前解決を決めるため、呼び出し元がどのモジュールかは関係ない）。
"""

import datetime as dt

from . import googlehealth_client as api
from . import googlehealth_sleep as sleep_mod
from .googlehealth_client import _daily_rows, _num, _rollup_by_date, _to_date

# 完全に安静に過ごした日でも基礎代謝（BMI）が丸1日分積み上がるため、
# 1日分の caloriesOut が生理的にこれを下回ることは無い（Issue #125）。
# 部分日（today）を除いて閾値を割った場合は、--days の窓が狭くて
# 取り直されていない部分日である可能性を警告する（データは書き換えない、
# 警告のみ）。
MIN_PLAUSIBLE_CALORIES_OUT = 1200


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
# 安静時心拍数 -> data/fitbit/heart_rate.csv（Issue #78）
# =============================================================================

def fetch_heart_rate(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date, resting_heart_rate

    daily-resting-heart-rate は同じ日付に2系統の dataPoint が届く:
    platform=FITBIT（Charge 6 本体算出、calculationMethod=WITH_SLEEP を
    ほぼ常に持つ）と platform=HEALTH_CONNECT（application.packageName=
    com.google.android.apps.fitness、calculationMethod 無し）。

    実測（2026-01〜08、264日）:
    - 264/264 日に FITBIT 点が存在し、その値は既存 data/fitbit/heart_rate.csv
      と完全一致する（lag 0）
    - HEALTH_CONNECT 点は系統的に約5bpm 低い
    - 従来の「月ごとの一致率が非単調」は算出方法の切り替えではなく、
      日付ごとにどちらの点が最後に来たかで決まっていただけ（Issue #78）

    そのため FITBIT 点（WITH_SLEEP があればそれを優先）だけを採用し、
    HEALTH_CONNECT へのフォールバックはしない。段差を作るくらいなら
    欠測のままにする（このリポジトリでは「欠測 > 誤った値」）。
    """
    skipped = 0

    def pick(points: list[dict]):
        nonlocal skipped
        fitbit_points = [
            p for p in points
            if (p.get('dataSource') or {}).get('platform') == 'FITBIT'
        ]
        if not fitbit_points:
            skipped += 1
            return None
        with_sleep = [
            p for p in fitbit_points
            if ((p.get('dailyRestingHeartRate') or {}).get('dailyRestingHeartRateMetadata')
                or {}).get('calculationMethod') == 'WITH_SLEEP'
        ]
        return (with_sleep or fitbit_points)[0]

    rows = _daily_rows(
        creds, 'daily-resting-heart-rate', 'dailyRestingHeartRate',
        start_date, end_date,
        lambda v: {'resting_heart_rate': _num(v.get('beatsPerMinute'))},
        pick=pick,
    )
    if skipped:
        print(f'  ⚠️ heart_rate: FITBIT 点が無い日を{skipped}件スキップ'
              '（HEALTH_CONNECT のみの日は約5bpm低く、混ぜると段差になるため採らない）')
    return rows


# =============================================================================
# SpO2（血中酸素飽和度） -> data/fitbit/spo2.csv（Issue #78）
# =============================================================================

def fetch_spo2(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date, avg_spo2, min_spo2, max_spo2

    daily-oxygen-saturation は platform=FITBIT の1点のみで重複が無く、値は
    既存 CSV と完全一致するが、**日付ラベルが1日ずれる**（実測: 2026-03以降
    175日中172日が lag+1 = Google の日付+1 が既存CSVの日付。lag0 は0日、
    残り3日はCSV側に対応行が無いだけ）。

    「Google の日付 = 睡眠開始日」という素朴な解釈は誤り（実測で10日破綻。
    例: Google "2026-08-18" は CSV "2026-08-19" と一致するが、その夜の
    睡眠は 08-19T00:05 開始 = 開始日は08-19で一致しない）。正しくは
    「Google は睡眠を『その夜が始まった暦日』でラベルする」で、正午〜正午の
    窓 [d 12:00, d+1 12:00) と重なる睡眠セッションの dateOfSleep を採用すると
    実測175日すべてで既存CSVと整合する。そのため一律 +1 日にはせず、
    睡眠セッションに引き当てて解決する。

    intraday（oxygen-saturation）は使わない: filter が無く list のみ・1分
    粒度のため、2026-06-01以降だけでも数百ページのページングになり日次
    運用に載らない（intraday の活用は Issue #76 の担当）。日次 payload には
    測定時刻が無いため、代わりに睡眠セッションの実時刻を突き合わせ先にする。

    Issue #78 は「最新1件だけズレない例外がある」とも報告していたが、
    2026-03以降175日の実測では再現しなかった（推測: 分析時点のCSVに
    最新行がまだ無かったための見かけ上の一致）。例外扱いはせず、常に
    セッション引き当てで解決する。

    重なるセッションが1つも無い Google の点は行を作らない（一律+1日の
    フォールバックはしない）。複数の Google 日付が同じ最終日に解決した
    場合は、新しい方の Google 日付を採用する。
    """
    points = api.list_data_points(
        creds, 'daily-oxygen-saturation',
        stop_before=start_date - dt.timedelta(days=1),
        payload_key='dailyOxygenSaturation',
    )

    # 睡眠は start_date の1日前から取る。stop_before により Google 側の最も古い
    # 対象点は start_date-1 日のラベルを持ち、その正午〜正午の窓には
    # 「start_date-1 日の朝に終わった睡眠」（dateOfSleep = start_date-1）が
    # 重なりうる。start_date から取ると、その日だけ候補セッションが欠け、
    # 短い窓（daily-routine.sh の --days 2）と長い窓で同じ点が別の日付に
    # 解決してしまう（実測: 09-02 の点が --days 3 では 09-03 に解決し、
    # 既存の正しい行を1日ずらして上書きしていた）。
    sleep_rows, _ = sleep_mod.fetch_sleep_all(
        creds, start_date - dt.timedelta(days=1), end_date)
    sessions = []
    for row in sleep_rows:
        sessions.append({
            'start': dt.datetime.strptime(row['startTime'], '%Y-%m-%dT%H:%M:%S.000'),
            'end': dt.datetime.strptime(row['endTime'], '%Y-%m-%dT%H:%M:%S.000'),
            'date_of_sleep': row['dateOfSleep'],
            'is_main': bool(row.get('isMainSleep')),
            'length': row.get('timeInBed') or 0,
        })

    resolved: dict[str, tuple[str, dict]] = {}  # final_date -> (google_date, payload)
    skipped = 0
    for point in points:
        value = point.get('dailyOxygenSaturation')
        if not value or 'date' not in value:
            continue
        google_date = _to_date(value['date'])
        window_start = dt.datetime.strptime(google_date, '%Y-%m-%d').replace(hour=12)
        window_end = window_start + dt.timedelta(days=1)

        overlapping = [
            s for s in sessions if s['start'] < window_end and window_start < s['end']
        ]
        if not overlapping:
            skipped += 1
            continue

        main_sessions = [s for s in overlapping if s['is_main']]
        candidates = main_sessions or overlapping
        chosen = max(candidates, key=lambda s: s['length'])
        final_date = chosen['date_of_sleep']

        prev = resolved.get(final_date)
        if prev is None:
            resolved[final_date] = (google_date, value)
        elif google_date > prev[0]:
            print(f'  ⚠️ spo2: {final_date} の日付解決が衝突。'
                  f'新しい Google 日付 {google_date} を採用（旧 {prev[0]} を破棄）')
            resolved[final_date] = (google_date, value)
        # google_date <= prev[0] なら既存の採用を維持（新しい方を残す）

    if skipped:
        print(f'  ⚠️ spo2: 重なる睡眠セッションが無い点を{skipped}件スキップ')

    rows = []
    for final_date, (_google_date, value) in resolved.items():
        if not (start_date.isoformat() <= final_date <= end_date.isoformat()):
            continue
        rows.append({
            'date': final_date,
            'avg_spo2': _num(value.get('averagePercentage')),
            'min_spo2': _num(value.get('lowerBoundPercentage')),
            'max_spo2': _num(value.get('upperBoundPercentage')),
        })
    rows.sort(key=lambda r: r['date'])
    return rows


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

    レポート側ではこの2列の代わりに lightlyActiveMinutes /
    fairlyActiveMinutes / veryActiveMinutes（active-minutes）から導く
    active_minutes 指標を使う（Issue #82）。CSV の列自体は履歴保持のため
    残している。
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

    today = dt.date.today().isoformat()
    for row in rows:
        if row['date'] == today:
            # 当日は部分日で、caloriesOut が低いのは正常（窓が広がれば
            # 後日ここが上書きされる）。警告しない
            continue
        calories_out = row['caloriesOut']
        if calories_out is not None and calories_out < MIN_PLAUSIBLE_CALORIES_OUT:
            print(f"  ⚠️ activity: {row['date']} の caloriesOut が {calories_out}kcal と"
                  '低すぎる（部分日が取り直されていない可能性）')

    return rows


# =============================================================================
# アクティブゾーン分 -> data/fitbit/active_zone_minutes.csv
# =============================================================================

def fetch_active_zone_minutes(creds, start_date: dt.date, end_date: dt.date) -> list[dict]:
    """
    列: date, activeZoneMinutes, fatBurnActiveZoneMinutes, cardioActiveZoneMinutes,
        peakActiveZoneMinutes

    合計の activeZoneMinutes は Google に対応するフィールドが無いため算出する。
    Fitbit の旧実装は cardio/peak を「1分=2AZM」の重み付けで扱うと docstring に
    記述していたが、実データ（2026-08-11〜23の13日）はそれに従わない:
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
        body = api._get(creds, f'{api.USER}/dataTypes/core-body-temperature/dataPoints', params)
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
