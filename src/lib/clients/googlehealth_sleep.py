#!/usr/bin/env python
# coding: utf-8
"""
Google Health 睡眠 -> data/wearable/sleep.csv, data/wearable/sleep_levels.csv

googlehealth_client.py から分割（Issue #78。ファイルサイズ hook の 500行上限対応）。
`_get` 等の共通プリミティブはテストが `googlehealth_client.<name>` を直接
monkeypatch する前提なので、ここでは `from . import googlehealth_client as api` の
形で呼び出し、モジュール属性を経由させる（静的 import で束縛すると
monkeypatch が効かなくなる）。
"""

import datetime as dt

from . import googlehealth_client as api
from .googlehealth_client import _num

# Google の stages 型ステージ名 -> 既存 CSV の level 値
# 既存 sleep_levels.csv には Fitbit の classic 睡眠由来の asleep/restless/awake も
# 混在するが（cut -d, -f4 data/wearable/sleep_levels.csv で確認）、stages 型の既存行は
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
        body = api._get(creds, f'{api.USER}/dataTypes/sleep/dataPoints', params)
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
    points = api._list_sleep_points(creds, start_date, end_date)

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
