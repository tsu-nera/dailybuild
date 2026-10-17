"""生活日1日ぶんの材料から区切り（離床・出発・帰宅・入眠…）を判定する

材料が欠けた区切りは None にする。別の材料で埋めない（Fitbit の睡眠記録の終了を離床の代わりに
使うと、10-17 のように37分ずれた値が離床として残る）。
"""

import datetime as dt
from dataclasses import dataclass, field

from lib.observation.ha import NO_DATA, collapse, last_seen, noise_bursts, numeric

MORNING = ('最終覚醒', '睡眠記録終了', '離床', '出発', '到着')
EVENING = ('帰宅', '画面off', '消灯', '入眠')
LANDMARKS = MORNING + EVENING
COMMUTE_TYPES = ('OUTDOOR_BIKE', 'BIKING', 'SPINNING', 'WALKING')


@dataclass
class DayData:
    day: dt.date
    lo: dt.datetime
    hi: dt.datetime
    cfg: dict
    hist: dict                       # {entity_id: [(時刻, state, 窓の開始時点か)]}
    events: list[dict]               # events.jsonl（start/end は datetime）
    levels: dict = field(default_factory=dict)   # {log_id: [(開始, 終了, level)]}

    def ent(self, *keys):
        v = self.cfg['entities']
        for k in keys:
            v = v[k]
        return v

    def minutes(self, key, section='landmarks') -> dt.timedelta:
        return dt.timedelta(minutes=self.cfg[section][key])


@dataclass
class Landmark:
    name: str
    time: dt.datetime | None
    basis: str


def window(day: dt.date, day_start_hour: int, tz) -> tuple[dt.datetime, dt.datetime]:
    lo = dt.datetime.combine(day, dt.time(day_start_hour), tz)
    return lo, lo + dt.timedelta(days=1)


def main_sleep(events, date_of_sleep: dt.date) -> dict | None:
    for e in events:
        if e['kind'] == 'sleep' and e['attrs'].get('date_of_sleep') == date_of_sleep.isoformat():
            return e
    return None


def phone_entities(d: DayData) -> tuple[str, ...]:
    return tuple(d.ent('phone').values())


def phone_alive_until(d: DayData) -> dt.datetime | None:
    return last_seen(d.hist, phone_entities(d))


def bursts(d: DayData) -> list[tuple]:
    n = d.cfg['noise']
    return noise_bursts(d.hist.get(d.ent('noise'), []), n['loud_dbfs'], dt.timedelta(minutes=n['gap_min']))


def activity_bursts(d: DayData) -> list[tuple]:
    return [b for b in bursts(d) if b[2] >= d.cfg['noise']['activity_dbfs']]


def lights_changes(d: DayData, state: str) -> list[dt.datetime]:
    times = [t for eid in d.ent('lights') for t, s, initial in d.hist.get(eid, ())
             if s == state and not initial]
    return collapse(times, dt.timedelta(seconds=30))


def illuminance_jumps(d: DayData) -> list[dt.datetime]:
    """window_min 以内に jump 以上上がった最初の時刻（1回の上昇は1件）"""
    c = d.cfg['illuminance']
    w = dt.timedelta(minutes=c['window_min'])
    series = numeric(d.hist.get(d.ent('illuminance'), []))
    out = []
    for i, (t, v) in enumerate(series):
        base = min((pv for pt, pv in series[:i] if t - pt <= w), default=None)
        if base is not None and v - base >= c['jump'] and (not out or t - out[-1] > w):
            out.append(t)
    return out


def _levels(d: DayData, sleep) -> list[tuple]:
    return d.levels.get(str(sleep['attrs'].get('log_id')), [])


def final_awakening(d: DayData, sleep) -> Landmark:
    levels = _levels(d, sleep)
    asleep = [lv for lv in levels if lv[2] != 'wake']
    if not asleep:
        return Landmark('最終覚醒', None, 'ステージ記録なし')
    t = asleep[-1][1]
    if sleep['end'] - t < d.minutes('final_wake_min'):
        return Landmark('最終覚醒', sleep['end'], 'Fitbit 記録終了（末尾の覚醒が短い）')
    return Landmark('最終覚醒', t, 'Fitbit 最後の睡眠ステージの終わり')


def sleep_onset(d: DayData, sleep) -> Landmark:
    asleep = [lv for lv in _levels(d, sleep) if lv[2] != 'wake']
    if asleep:
        return Landmark('入眠', asleep[0][0], 'Fitbit 最初の睡眠ステージ')
    return Landmark('入眠', sleep['start'], 'Fitbit 記録開始（ステージなし）')


def rise(d: DayData, ref: dt.datetime) -> tuple[Landmark, tuple | None]:
    """照度の急上昇（カーテン）と生活音が重なる最初の時刻。重ならなければ生活音だけで取る"""
    within = d.minutes('rise_match_within_min')
    # 外泊の朝に帰宅後の夜の生活音を離床と取らない（10-15 は 23:02 が離床と出た）
    until = ref + dt.timedelta(hours=d.cfg['landmarks']['rise_within_hours'])
    acts = [b for b in activity_bursts(d) if ref <= b[0] <= until]
    jumps = [t for t in illuminance_jumps(d) if ref <= t <= until]
    for b in acts:
        near = [j for j in jumps if abs(j - b[0]) <= within or b[0] <= j <= b[1]]
        if near:
            return Landmark('離床', min(b[0], near[0]), '照度の急上昇＋生活音'), b
    if acts:
        return Landmark('離床', acts[0][0], '生活音のみ（照度の上昇なし）'), acts[0]
    return Landmark('離床', None, '起床後の生活音なし（外泊・不在の可能性）'), None


def _exercises_between(d: DayData, lo, hi):
    return [e for e in d.events
            if e['kind'] == 'exercise' and lo <= e['start'] <= hi
            and e['attrs'].get('exercise_type') in COMMUTE_TYPES]


def depart_and_arrive(d: DayData, rise_lm: Landmark, rise_burst) -> tuple[Landmark, Landmark]:
    if rise_lm.time is None:
        return Landmark('出発', None, '離床が不明'), Landmark('到着', None, '離床が不明')
    by = dt.datetime.combine(d.day, dt.time(d.cfg['landmarks']['depart_by_hour']), rise_lm.time.tzinfo)
    ex = _exercises_between(d, rise_lm.time, by)
    if ex:
        e = ex[0]
        return (Landmark('出発', e['start'], f"運動の開始（{e['name']}）"),
                Landmark('到着', e['end'], f"運動の終了（{e['name']}）"))
    gap = d.minutes('depart_chain_gap_min')
    quiet = d.minutes('depart_quiet_after_min')
    all_b = bursts(d)
    end = rise_burst[1]
    for b in all_b:
        if b[0] > end and b[0] - end <= gap:
            end = max(end, b[1])
    later = [b for b in activity_bursts(d) if end < b[0] <= end + quiet]
    if later or end > by:
        return Landmark('出発', None, '離床後の生活音が途切れない（在宅の可能性）'), Landmark('到着', None, '出発が不明')
    return Landmark('出発', end, '離床後の生活音の終わり'), Landmark('到着', None, '運動の記録なし')


def home(d: DayData, until: dt.datetime) -> Landmark:
    lo = dt.datetime.combine(d.day, dt.time(d.cfg['landmarks']['evening_from_hour']), until.tzinfo)
    within = d.minutes('home_noise_within_min')
    quiet = d.minutes('home_quiet_before_min')
    acts = activity_bursts(d)
    for t in lights_changes(d, 'on'):
        if not lo <= t <= until:
            continue
        near = any(abs(b[0] - t) <= within or b[0] <= t <= b[1] for b in acts)
        before = any(t - quiet <= b[1] < t - within for b in acts)
        if near and not before:
            return Landmark('帰宅', t, '照明点灯＋生活音（直前は無音）')
    return Landmark('帰宅', None, '照明点灯と生活音の一致なし')


def screen_off(d: DayData, sleep) -> Landmark:
    alive = phone_alive_until(d)
    if alive is None or alive < sleep['start']:
        return Landmark('画面off', None, 'スマホの記録が途中で止まっている')
    hi = sleep['start'] + d.minutes('lights_off_after_sleep_min')
    offs = [t for t, s, initial in d.hist.get(d.ent('phone', 'screen'), ())
            if s == 'off' and not initial and sleep['start'] - dt.timedelta(hours=6) <= t <= hi]
    if not offs:
        return Landmark('画面off', None, '入眠前後に画面offなし')
    return Landmark('画面off', offs[-1], 'スマホ画面の最後のoff')


def lights_off(d: DayData, sleep) -> Landmark:
    hi = sleep['start'] + d.minutes('lights_off_after_sleep_min')
    offs = [t for t in lights_changes(d, 'off') if sleep['start'] - dt.timedelta(hours=6) <= t <= hi]
    if not offs:
        return Landmark('消灯', None, '入眠前後に消灯なし')
    return Landmark('消灯', offs[-1], '照明の最後のoff')


def judge(d: DayData) -> list[Landmark]:
    out = []
    morning = main_sleep(d.events, d.day)
    if morning is None or not d.lo <= morning['end'] < d.hi:
        out += [Landmark(n, None, 'この日の朝の睡眠記録なし') for n in MORNING]
    else:
        fa = final_awakening(d, morning)
        out += [fa, Landmark('睡眠記録終了', morning['end'], 'Fitbit 記録終了（離床ではない）')]
        r, rb = rise(d, fa.time or morning['end'])
        out += [r, *depart_and_arrive(d, r, rb)]
    night = main_sleep(d.events, d.day + dt.timedelta(days=1))
    if night is None or not d.lo <= night['start'] < d.hi:
        until = d.hi
        out += [home(d, until)] + [Landmark(n, None, 'この夜の睡眠記録なし') for n in EVENING[1:]]
    else:
        out += [home(d, night['start']), screen_off(d, night), lights_off(d, night), sleep_onset(d, night)]
    return out


def source_status(d: DayData) -> list[tuple[str, str, str]]:
    """(ソース, 状態, 備考)。止まっているソースを日記の先頭に出す"""
    stale = dt.timedelta(hours=d.cfg['phone_stale_hours'])
    rows = []
    alive = phone_alive_until(d)
    if alive is None:
        rows.append(('スマホ', '停止', '窓の間に何も届いていない（Companion App / Tailscale）'))
    elif alive < min(d.hi, _now(d)) - stale:
        rows.append(('スマホ', '停止', f'{alive:%m-%d %H:%M} 以降届いていない（Companion App / Tailscale）'))
    else:
        rows.append(('スマホ', 'OK', f'最終 {alive:%m-%d %H:%M}'))
    for label, eid in (('生活音', d.ent('noise')), ('照度', d.ent('illuminance'))):
        n = sum(1 for _, s, initial in d.hist.get(eid, ()) if not initial and s not in NO_DATA)
        rows.append((label, 'OK' if n else '記録なし', f'{n}件'))
    n_lights = len(lights_changes(d, 'on')) + len(lights_changes(d, 'off'))
    rows.append(('照明', 'OK', f'変化 {n_lights}回'))
    pc = last_seen(d.hist, tuple(d.ent('pc').values()))
    rows.append(('PC', '記録あり' if pc and pc >= d.lo else '記録なし', f'最終 {pc:%m-%d %H:%M}' if pc else '-'))
    srcs = {}
    for e in d.events:
        if d.lo <= e['start'] < d.hi:
            srcs[e['source']] = srcs.get(e['source'], 0) + 1
    for s, n in sorted(srcs.items()):
        rows.append((s, 'OK', f'{n}件'))
    return rows


def _now(d: DayData) -> dt.datetime:
    return dt.datetime.now(d.lo.tzinfo)
