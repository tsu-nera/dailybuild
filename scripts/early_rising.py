#!/usr/bin/env python
# coding: utf-8
"""
早起きの lap 表とタイムライン（/early-rising が使う）

前夜を区切り（帰宅・最後の画面消灯・入眠）に、朝を区切り（起床・最初の画面・出発・到着）に
分け、区切りの間の lap を夜ごとに並べる。区切りはすべてセンサーから取り、本人の入力は要らない。
照明は lap に使わない。オートメーション化が進んでいて、点灯・消灯が本人の行動を表さなくなる
（timeline には生の変化として出す）。
食事のようにセンサーで取れない区切りは出さない。

入力は Home Assistant の state 履歴（スマホの画面・前面アプリ・在宅）と reports/events.jsonl
（メイン睡眠・重複解決済みの運動）。HA の履歴は 2026-10-01 夜より前には無いので、
それ以前の夜は HA 由来の列が `-` になる。

Usage:
    uv run scripts/early_rising.py laps                 # 直近7晩（起床日が今日まで）
    uv run scripts/early_rising.py laps --nights 14 --until 2026-10-10
    uv run scripts/early_rising.py timeline             # 今朝に終わった夜の時系列
    uv run scripts/early_rising.py timeline --date 2026-10-09
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import json

from lib.clients.homeassistant_client import (
    HomeAssistantClient,
    HomeAssistantError,
    load_settings,
)
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).parent.parent
EVENTS_JSONL = BASE_DIR / 'reports' / 'events.jsonl'
JST = dt.timezone(dt.timedelta(hours=9))

PHONE_SCREEN = 'binary_sensor.xiaomi_interactive'
PHONE_APP = 'sensor.xiaomi_last_used_app'
PHONE_HOME = 'device_tracker.xiaomi'
LIGHTS = ('light.denkyu_chuo', 'light.denkyu_hidari', 'light.denkyu_migi', 'light.kansetsu_shoumei')
# タイムラインにだけ出す（lap には使わない）。PC の前面アプリは15秒粒度で多すぎるので入れない
TIMELINE_ONLY = ('switch.kyoshitsu_monitor', 'binary_sensor.cachyos_idle', 'counter.bedtime_interrupt_fired')

# 前夜の窓。起床日 D に対して D-1 の15時から
NIGHT_START_HOUR = 15
# 入眠の直後に画面や照明を消すことがある（10-09夜は入眠3分後に消灯）
AFTER_SLEEP_GRACE = dt.timedelta(minutes=60)
MORNING_LEAD = dt.timedelta(minutes=30)
CYCLING_TYPES = ('OUTDOOR_BIKE', 'BIKING', 'SPINNING')
# 朝の最初の自転車の終了＝勉強カフェ到着（本人確認 2026-10-09）
ARRIVAL_WINDOW = (4, 12)
NO_DATA = ('unavailable', 'unknown')
# パッケージ名の末尾だけでは読めないもの（io.homeassistant.companion.android → android など）
APP_LABELS = {
    'io.homeassistant.companion.android': 'homeassistant',
    'com.miui.home': 'launcher',
    'com.google.android.googlequicksearchbox': 'google',
    'com.google.android.apps.chromecast.app': 'googlehome',
    'jp.healthplanet.healthplanetapp': 'healthplanet',
}


def load_events() -> list[dict]:
    path = require_private_path(EVENTS_JSONL)
    with open(path, encoding='utf-8') as f:
        events = [json.loads(line) for line in f if line.strip()]
    for e in events:
        e['start'] = dt.datetime.fromisoformat(e['start'])
        e['end'] = dt.datetime.fromisoformat(e['end']) if e['end'] else None
    return events


def main_sleep(events: list[dict], wake_date: dt.date) -> dict | None:
    for e in events:
        if e['kind'] == 'sleep' and e['attrs'].get('date_of_sleep') == wake_date.isoformat():
            return e
    return None


def commute(events: list[dict], wake_date: dt.date) -> dict | None:
    """朝の最初の自転車。start＝出発、end＝到着（どちらも本人確認 2026-10-09 / 10-10）

    出発は device_tracker の not_home を使わない（10-10 は自転車の開始 08:24 に対し
    not_home が 08:39 で、ジオフェンスの判定が15分遅れた）
    """
    lo, hi = ARRIVAL_WINDOW
    for e in events:
        if (e['kind'] == 'exercise' and e['attrs'].get('exercise_type') in CYCLING_TYPES
                and e['start'].date() == wake_date and lo <= e['start'].hour < hi):
            return e
    return None


def fetch_history(start: dt.datetime, end: dt.datetime, entity_ids) -> dict[str, list[tuple]]:
    """{entity_id: [(時刻, state, 窓の開始時点の値か)]}。変化時刻は last_changed"""
    url, token = load_settings()
    raw = HomeAssistantClient(url, token).history_during_period(start, end, list(entity_ids))
    out = {}
    for eid, rows in raw.items():
        series = []
        for i, r in enumerate(rows):
            ts = r.get('lc', r['lu'])
            t = dt.datetime.fromtimestamp(ts, JST)
            series.append((t, r['s'], i == 0 and t <= start))
        out[eid] = series
    return out


def transitions(series, state, lo, hi):
    """lo〜hi の間に state へ変わった時刻（窓の開始時点の値は変化に数えない）"""
    return [t for t, s, initial in series if s == state and not initial and lo <= t <= hi]


def on_minutes(series, lo, hi) -> float:
    total = dt.timedelta()
    for i, (t, s, _) in enumerate(series):
        if s != 'on':
            continue
        t_end = series[i + 1][0] if i + 1 < len(series) else hi
        a, b = max(t, lo), min(t_end, hi)
        if b > a:
            total += b - a
    return total.total_seconds() / 60


def apps_in(series, lo, hi) -> list[str]:
    names = []
    for t, s, _ in series:
        if lo <= t <= hi and s not in NO_DATA:
            short = APP_LABELS.get(s, s.rsplit('.', 1)[-1])
            if not names or names[-1] != short:
                names.append(short)
    return names


def covered(series) -> bool:
    """窓の開始時点で値を持っていたか。entity を有効化する前の夜を「0分」と捏造しない"""
    return any(initial and s not in NO_DATA for t, s, initial in series)


def night_window(wake_date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    lo = dt.datetime.combine(wake_date - dt.timedelta(days=1), dt.time(NIGHT_START_HOUR), JST)
    return lo, dt.datetime.combine(wake_date, dt.time(12), JST)


def night_row(events, hist, wake_date: dt.date) -> dict:
    row = {'date': wake_date}
    sleep = main_sleep(events, wake_date)
    ride = commute(events, wake_date)
    if ride:
        row['depart'], row['arrival'] = ride['start'], ride['end']
    if sleep is None:
        return row
    row['sleep_start'], row['sleep_end'] = sleep['start'], sleep['end']
    lo, _ = night_window(wake_date)
    hi = sleep['start'] + AFTER_SLEEP_GRACE

    home = hist.get(PHONE_HOME, [])
    if covered(home):
        arrived = transitions(home, 'home', lo, sleep['start'])
        if arrived:
            row['home'] = arrived[-1]
        elif any(s == 'home' and initial for t, s, initial in home):
            row['home'] = 'stayed'
    screen = hist.get(PHONE_SCREEN, [])
    if covered(screen):
        offs = transitions(screen, 'off', lo, hi)
        if offs:
            row['screen_off'] = offs[-1]
            ons = [t for t in transitions(screen, 'on', lo, offs[-1])]
            if ons:
                row['last_session_start'] = ons[-1]
        start_count = row['home'] if isinstance(row.get('home'), dt.datetime) else lo
        row['phone_min'] = on_minutes(screen, start_count, sleep['start'])
        row['apps'] = apps_in(hist.get(PHONE_APP, []), start_count, row.get('screen_off', hi))

    # 朝。起床の記録より先に画面を点けることがあるので少しさかのぼる
    m_lo = sleep['end'] - MORNING_LEAD
    m_hi = row.get('depart') or dt.datetime.combine(wake_date, dt.time(ARRIVAL_WINDOW[1]), JST)
    if covered(screen):
        ons = transitions(screen, 'on', m_lo, m_hi)
        if ons:
            row['first_screen'] = ons[0]
        row['morning_phone_min'] = on_minutes(screen, sleep['end'], m_hi)
        row['morning_apps'] = apps_in(hist.get(PHONE_APP, []), m_lo, m_hi)
    return row


def _hm(t) -> str:
    if t == 'stayed':
        return '在宅'
    return t.strftime('%H:%M') if isinstance(t, dt.datetime) else '-'


def _day(d: dt.date) -> str:
    return f"{d:%m-%d} {'月火水木金土日'[d.weekday()]}"


def _min(m) -> str:
    return '-' if m is None else f'{m:.0f}分'


def _lap(a, b) -> str:
    if not (isinstance(a, dt.datetime) and isinstance(b, dt.datetime)):
        return '-'
    m = int((b - a).total_seconds() // 60)
    return f'{m // 60}:{m % 60:02d}' if m >= 0 else f'-{(-m) // 60}:{(-m) % 60:02d}'


def cmd_laps(args) -> int:
    until = dt.date.fromisoformat(args.until) if args.until else dt.date.today()
    dates = [until - dt.timedelta(days=i) for i in range(args.nights - 1, -1, -1)]
    events = load_events()
    # 夜ごとに取る。窓の開始時点の値で「その夜に entity があったか」を判定するため
    nights = {}
    try:
        for d in dates:
            nights[d] = fetch_history(*night_window(d), (PHONE_SCREEN, PHONE_APP, PHONE_HOME))
    except HomeAssistantError as exc:
        print(f'エラー: HA の履歴を読めない: {exc}', file=sys.stderr)
        return 1

    rows = [(d, night_row(events, nights[d], d)) for d in dates]

    print('## 夜\n')
    print('| 起床日 | 帰宅 | 最後の画面開始 | 画面off | 入眠 | 起床 '
          '| 帰宅→画面off | 画面off→入眠 | 睡眠 | 画面on計 | アプリ |')
    print('|' + '---|' * 11)
    for d, r in rows:
        print(f"| {_day(d)} | {_hm(r.get('home'))} "
              f"| {_hm(r.get('last_session_start'))} | {_hm(r.get('screen_off'))} "
              f"| {_hm(r.get('sleep_start'))} | {_hm(r.get('sleep_end'))} "
              f"| {_lap(r.get('home'), r.get('screen_off'))} "
              f"| {_lap(r.get('screen_off'), r.get('sleep_start'))} "
              f"| {_lap(r.get('sleep_start'), r.get('sleep_end'))} "
              f"| {_min(r.get('phone_min'))} | {' → '.join(r.get('apps', [])) or '-'} |")

    print('\n## 朝\n')
    print('| 起床日 | 起床 | 最初の画面 | 出発 | 到着 '
          '| 起床→出発 | 移動 | 起床→到着 | 画面on計 | アプリ |')
    print('|' + '---|' * 10)
    for d, r in rows:
        print(f"| {_day(d)} | {_hm(r.get('sleep_end'))} | {_hm(r.get('first_screen'))} "
              f"| {_hm(r.get('depart'))} | {_hm(r.get('arrival'))} "
              f"| {_lap(r.get('sleep_end'), r.get('depart'))} "
              f"| {_lap(r.get('depart'), r.get('arrival'))} "
              f"| {_lap(r.get('sleep_end'), r.get('arrival'))} "
              f"| {_min(r.get('morning_phone_min'))} | {' → '.join(r.get('morning_apps', [])) or '-'} |")
    return 0


def cmd_timeline(args) -> int:
    wake = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    lo, hi = night_window(wake)
    try:
        hist = fetch_history(lo, hi, (PHONE_SCREEN, PHONE_APP, PHONE_HOME, *LIGHTS, *TIMELINE_ONLY))
    except HomeAssistantError as exc:
        print(f'エラー: HA の履歴を読めない: {exc}', file=sys.stderr)
        return 1
    rows = []
    for eid, series in hist.items():
        for t, s, initial in series:
            rows.append((t, eid.split('.', 1)[1], s + (' (窓の開始時点)' if initial else '')))
    for e in load_events():
        if lo <= e['start'] <= hi:
            end = f"〜{e['end']:%H:%M}" if e['end'] else ''
            rows.append((e['start'], e['kind'], f"{e['name']}{end}"))
    for t, what, s in sorted(rows, key=lambda r: r[0]):
        print(f'{t:%m-%d %H:%M:%S}  {what}  {s}')
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    p_laps = sub.add_parser('laps', help='夜ごとの区切りと lap の表（markdown）')
    p_laps.add_argument('--nights', type=int, default=7)
    p_laps.add_argument('--until', help='最後の起床日（既定は今日）')
    p_laps.set_defaults(func=cmd_laps)
    p_tl = sub.add_parser('timeline', help='1晩の時系列（HA の state 変化 + events.jsonl）')
    p_tl.add_argument('--date', help='起床日（既定は今日）')
    p_tl.set_defaults(func=cmd_timeline)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
