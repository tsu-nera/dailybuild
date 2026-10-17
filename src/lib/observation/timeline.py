"""生活日1日ぶんの時系列と不明区間、markdown"""

import datetime as dt

from lib.observation.ha import NO_DATA, numeric
from lib.observation.landmarks import (
    DayData, Landmark, bursts, lights_changes, phone_alive_until,
)

SPEAKER_SKIP = ('idle', 'buffering')
# パッケージ名の末尾だけでは読めないもの
APP_LABELS = {
    'io.homeassistant.companion.android': 'homeassistant',
    'com.miui.home': 'launcher',
    'com.google.android.googlequicksearchbox': 'google',
    'com.google.android.apps.chromecast.app': 'googlehome',
    'jp.healthplanet.healthplanetapp': 'healthplanet',
    'com.mitchellh.ghostty': 'ghostty',
}


def app_label(name: str) -> str:
    return APP_LABELS.get(name, name.rsplit('.', 1)[-1])


def _in(d: DayData, t) -> bool:
    return d.lo <= t < d.hi


def phone_sessions(d: DayData) -> list[tuple]:
    alive = phone_alive_until(d)
    if alive is None:
        return []
    screen = d.hist.get(d.ent('phone', 'screen'), [])
    apps = d.hist.get(d.ent('phone', 'app'), [])
    out = []
    for i, (t, s, _) in enumerate(screen):
        if s != 'on':
            continue
        end = screen[i + 1][0] if i + 1 < len(screen) else alive
        a, b = max(t, d.lo), min(end, d.hi, alive)
        if b <= a:
            continue
        names = []
        for at, name, _ in apps:
            if a <= at <= b and name not in NO_DATA and app_label(name) != 'launcher':
                if not names or names[-1] != app_label(name):
                    names.append(app_label(name))
        out.append((a, b, 'スマホ画面' + (f"（{' → '.join(names)}）" if names else ''), 'phone'))
    return out


def pc_sessions(d: DayData) -> list[tuple]:
    gap = dt.timedelta(minutes=d.cfg['pc_session_gap_min'])
    changes = [(t, s) for t, s, initial in d.hist.get(d.ent('pc', 'app'), ())
               if not initial and s not in NO_DATA and s != 'none' and _in(d, t)]
    out = []
    for t, s in changes:
        if out and t - out[-1][1] <= gap:
            out[-1][1] = t
            out[-1][2].setdefault(app_label(s), 0)
            out[-1][2][app_label(s)] += 1
        else:
            out.append([t, t, {app_label(s): 1}])
    return [(a, b, 'PC（' + ', '.join(sorted(c, key=c.get, reverse=True)[:3]) + '）', 'pc')
            for a, b, c in out]


def items(d: DayData) -> list[tuple]:
    """(開始, 終了 or None, 何, ソース)"""
    rows = []
    act = d.cfg['noise']['activity_dbfs']
    for a, b, m in bursts(d):
        if _in(d, a):
            rows.append((a, b if b > a else None, f"{'生活音' if m >= act else '物音'}（max {m:.0f}dBFS）", 'noise'))
    for state in ('on', 'off'):
        rows += [(t, None, f'照明 {state}', 'lights') for t in lights_changes(d, state) if _in(d, t)]
    prev = None
    show = d.cfg['illuminance']['show_delta']
    for t, v in numeric(d.hist.get(d.ent('illuminance'), [])):
        if prev is not None and abs(v - prev) >= show and _in(d, t):
            rows.append((t, None, f'照度 {prev:.0f}→{v:.0f}', 'illuminance'))
        prev = v
    last = None
    for t, s, initial in d.hist.get(d.ent('speaker'), ()):
        if initial or s in SPEAKER_SKIP or s in NO_DATA or s == last:
            continue
        last = s
        if _in(d, t):
            rows.append((t, None, f'スピーカー {s}', 'speaker'))
    rows += phone_sessions(d) + pc_sessions(d)
    for e in d.events:
        # 前夜から続く睡眠は窓の前に始まる。入れないと睡眠中が不明区間に出る
        overlaps = e['end'] is not None and e['start'] < d.hi and e['end'] > d.lo
        if not (_in(d, e['start']) or overlaps):
            continue
        rows.append((e['start'], e['end'], _event_label(e), e['source']))
    return sorted(rows, key=lambda r: r[0])


def _event_label(e) -> str:
    if e['kind'] == 'sleep':
        return '睡眠（Fitbit）'
    if e['kind'] == 'exercise':
        return f"運動: {e['name']}"
    if e['kind'] in ('habit', 'daily'):
        return f"Habitica: {e['name']}"
    if e['kind'] == 'time_entry':
        return f"Toggl: {e['name']}"
    return f"{e['kind']}: {e['name']}"


def unknown_gaps(d: DayData, rows) -> list[tuple]:
    """起きている間に何の記録も無い区間。睡眠中は記録が無くて当然なので除く"""
    covered = []
    for a, b, what, src in rows:
        covered.append((a, b or a))
    covered.sort()
    limit = min(d.hi, dt.datetime.now(d.lo.tzinfo))
    gap = dt.timedelta(minutes=d.cfg['unknown_gap_min'])
    out, cur = [], d.lo
    for a, b in covered:
        if a - cur >= gap:
            out.append((cur, a))
        cur = max(cur, b)
    if limit - cur >= gap:
        out.append((cur, limit))
    return out


def _hm(t) -> str:
    return t.strftime('%H:%M') if t else '-'


def _dhm(d: DayData, t) -> str:
    """生活日と暦日がずれる時刻（翌0〜4時、前夜から続く睡眠）には日付を付ける"""
    if t is None:
        return '-'
    return f'{t:%H:%M}' if t.date() == d.day else f'{t:%m-%d %H:%M}'


def _span(a, b) -> str:
    m = int((b - a).total_seconds() // 60)
    return f'{m // 60}h{m % 60:02d}m'


def render(d: DayData, landmarks: list[Landmark], labels: dict, rows, gaps, status) -> str:
    wd = '月火水木金土日'[d.day.weekday()]
    partial = dt.datetime.now(d.lo.tzinfo) < d.hi
    lines = [
        f'# 観察日記 {d.day} ({wd})', '',
        '**生成物。手で編集しない**（`scripts/observation.py build` が全上書きする）。'
        '答え合わせは `labels.csv`、判定ルールは `config/observation.yaml`。', '',
        f'- 窓: {d.lo:%m-%d %H:%M} 〜 {d.hi:%m-%d %H:%M}' + ('（**未完了**）' if partial else ''), '',
        '## データ源', '', '| ソース | 状態 | 備考 |', '|---|---|---|',
    ]
    lines += [f'| {a} | {b} | {c} |' for a, b, c in status]
    lines += ['', '## 区切り', '', '| 区切り | 時刻 | 根拠 | 正解 | ズレ |', '|---|---|---|---|---|']
    for lm in landmarks:
        truth = labels.get(lm.name)
        diff = '-'
        if truth and lm.time:
            m = round((lm.time - truth).total_seconds() / 60)
            diff = f'{m:+d}分'
        tm = _dhm(d, lm.time)
        lines.append(f'| {lm.name} | {tm} | {lm.basis} | {_hm(truth)} | {diff} |')
    lines += ['', '## 時系列', '', '| 時刻 | 終了 | 何 | ソース |', '|---|---|---|---|']
    for a, b, what, src in rows:
        lines.append(f'| {_dhm(d, a)} | {_dhm(d, b)} | {what} | {src} |')
    lines += ['', '## 不明区間', '']
    lines += [f'- {_dhm(d, a)}〜{_dhm(d, b)}（{_span(a, b)}）' for a, b in gaps] or ['- なし']
    return '\n'.join(lines) + '\n'
