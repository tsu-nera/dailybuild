"""早寝早起きのチェックポイント（区切りの時刻）

起床日ごとに、前夜（帰宅・画面off・入眠）と朝（アラーム・最終覚醒・離床）の時刻を出す。
材料は本人が持ち歩くもの（Fitbit・スマホ）だけ。照明・照度・生活音は家の設定で、出発・到着は
通勤の形で意味が変わるので使わない。材料が無い区切りは行を作らない（別の材料で埋めない）。

区切りを足す・消すときは CHECKPOINTS に1行。出力は毎日全上書きなので、過去の日も作り直される。
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd

JST = dt.timezone(dt.timedelta(hours=9))
NO_DATA = ('unavailable', 'unknown')

PHONE_SCREEN = 'binary_sensor.xiaomi_interactive'
PHONE_ZONE = 'device_tracker.xiaomi'
PHONE_ALARM = 'sensor.xiaomi_next_alarm'
# 生存確認用（数十分おきに変わる）。Companion App が止まると全 entity が最後の値のまま残る
PHONE_ALIVE = (PHONE_SCREEN, PHONE_ZONE, 'sensor.xiaomi_battery_level', 'sensor.xiaomi_last_used_app')

NIGHT_START_HOUR = 15          # 起床日 D の前夜の窓は D-1 の15時から
NIGHT_END_HOUR = 12
AFTER_SLEEP_GRACE = dt.timedelta(minutes=60)   # 入眠の直後に画面を消すことがある
FINAL_WAKE_MIN = dt.timedelta(minutes=10)      # 末尾の覚醒がこれ未満なら記録終了を最終覚醒とする
RISE_STEPS = 30                # 5分間の歩数がこれ以上で離床（単発の数歩は寝返り・トイレ）
RISE_WINDOW = dt.timedelta(minutes=5)
RISE_WITHIN = dt.timedelta(hours=4)
ALARM_HOURS = (3, 12)          # 朝のアラームとみなす時間帯


@dataclass
class Inputs:
    """1晩ぶんの材料。テストではフェイクを渡す"""
    wake_date: dt.date
    sleep: dict | None                 # events.jsonl のメイン睡眠（date_of_sleep == wake_date）
    stages: list[tuple]                # [(開始, 終了, level)]。isShort の短い覚醒は除いたもの
    steps: pd.Series                   # 1分値。index は tz-aware
    states: dict[str, list[tuple]]     # {entity_id: [(時刻, state)]}。時刻昇順


def night_window(wake_date: dt.date) -> tuple[dt.datetime, dt.datetime]:
    lo = dt.datetime.combine(wake_date - dt.timedelta(days=1), dt.time(NIGHT_START_HOUR), JST)
    return lo, dt.datetime.combine(wake_date, dt.time(NIGHT_END_HOUR), JST)


def state_at(series, t):
    """t の時点の state（t 以前の最後の値）"""
    prev = None
    for ts, s in series:
        if ts > t:
            break
        prev = s
    return prev


def changes_to(series, state, lo, hi) -> list[dt.datetime]:
    """lo〜hi に state へ変わった時刻。同じ state の連続行（attributes だけの更新）は変化に数えない"""
    out, prev = [], None
    for ts, s in series:
        if s == state and prev != state and lo <= ts <= hi:
            out.append(ts)
        prev = s
    return out


def _asleep(i: Inputs):
    return [s for s in i.stages if s[2] != 'wake']


def alarm_times(states) -> list[dt.datetime]:
    """next_alarm の値。カレンダーの通知も同じ sensor に来て 1970 年の値になるので落とす"""
    out = []
    for _, s in states.get(PHONE_ALARM, ()):
        try:
            t = dt.datetime.fromisoformat(s).astimezone(JST)
        except ValueError:
            continue
        if t.year >= 2000:
            out.append(t)
    return out


def alarm(i: Inputs):
    """その朝の最初のアラーム。next_alarm は次の1本しか持たないが、最初の1本は寝る前の値で必ず出る"""
    lo, hi = ALARM_HOURS
    times = [t for t in alarm_times(i.states) if t.date() == i.wake_date and lo <= t.hour < hi]
    return (min(times), 'next_alarm') if times else None


def sleep_onset(i: Inputs):
    if i.sleep is None:
        return None
    asleep = _asleep(i)
    return (asleep[0][0], 'fitbit_stage') if asleep else (i.sleep['start'], 'fitbit_record')


def final_wake(i: Inputs):
    if i.sleep is None:
        return None
    asleep = _asleep(i)
    if not asleep or i.sleep['end'] - asleep[-1][1] < FINAL_WAKE_MIN:
        return i.sleep['end'], 'fitbit_record'
    return asleep[-1][1], 'fitbit_stage'


def rise(i: Inputs):
    """最終覚醒の後、5分間の歩数が RISE_STEPS 以上になった窓の最初の歩数の分"""
    fw = final_wake(i)
    if fw is None:
        return None
    w = i.steps[fw[0]:fw[0] + RISE_WITHIN]
    w = w[w > 0]
    for t in w.index:
        if w[t:t + RISE_WINDOW - dt.timedelta(seconds=1)].sum() >= RISE_STEPS:
            return t.to_pydatetime(), 'steps'
    return None


def _phone_alive_after(i: Inputs, t: dt.datetime) -> bool:
    """Companion App が t より前に止まった夜は、画面・位置の最後の値が残っているだけ"""
    return any(ts > t for eid in PHONE_ALIVE for ts, _ in i.states.get(eid, ()))


def screen_off(i: Inputs):
    onset = sleep_onset(i)
    if onset is None or not _phone_alive_after(i, onset[0]):
        return None
    lo, _ = night_window(i.wake_date)
    offs = changes_to(i.states.get(PHONE_SCREEN, []), 'off', lo, onset[0] + AFTER_SLEEP_GRACE)
    return (offs[-1], 'phone') if offs else None


def home(i: Inputs):
    """入眠前の最後の帰宅。一日中在宅の夜は行を作らない"""
    onset = sleep_onset(i)
    if onset is None or not _phone_alive_after(i, onset[0]):
        return None
    lo, _ = night_window(i.wake_date)
    zone = i.states.get(PHONE_ZONE, [])
    if state_at(zone, lo) in (None, *NO_DATA):
        return None
    homes = changes_to(zone, 'home', lo, onset[0])
    return (homes[-1], 'phone_zone') if homes else None


# 出力の順（夜 → 朝）。足す・消すはここに1行
CHECKPOINTS = {
    'home': home,
    'screen_off': screen_off,
    'sleep_onset': sleep_onset,
    'alarm': alarm,
    'final_wake': final_wake,
    'rise': rise,
}


def judge(i: Inputs) -> list[tuple[str, dt.datetime, str]]:
    """[(checkpoint, 時刻, source)]。材料の無い区切りは含めない"""
    out = []
    for name, fn in CHECKPOINTS.items():
        r = fn(i)
        if r is not None:
            out.append((name, r[0], r[1]))
    return out


# --- data/ からの読み込み（全期間） ---

def load_states(base_dir, entity_ids) -> dict[str, list[tuple]]:
    """data/homeassistant/states/*.csv から {entity_id: [(時刻, state)]}。月をまたいで連結する"""
    files = sorted((base_dir / 'data' / 'homeassistant' / 'states').glob('*.csv'))
    if not files:
        return {}
    df = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False, usecols=['time', 'entity_id', 'state'])
                    for f in files])
    df = df[df['entity_id'].isin(entity_ids)]
    df['time'] = pd.to_datetime(df['time'], format='ISO8601').dt.tz_localize(JST)
    df = df.sort_values('time')
    return {eid: list(zip(g['time'].dt.to_pydatetime(), g['state'])) for eid, g in df.groupby('entity_id')}


def load_steps(base_dir) -> pd.Series:
    df = pd.read_csv(base_dir / 'data' / 'wearable' / 'steps_intraday.csv')
    s = pd.Series(df['steps'].to_numpy(), index=pd.to_datetime(df['datetime']).dt.tz_localize(JST))
    return s.sort_index()


def load_stages(base_dir) -> dict[str, list[tuple]]:
    """{log_id: [(開始, 終了, level)]}。isShort（短い覚醒の重ね書き）は除く"""
    df = pd.read_csv(base_dir / 'data' / 'wearable' / 'sleep_levels.csv', dtype={'logId': str})
    df = df[df['isShort'].astype(str) != 'True']
    df['start'] = pd.to_datetime(df['dateTime']).dt.tz_localize(JST)
    df['end'] = df['start'] + pd.to_timedelta(df['seconds'], unit='s')
    df = df.sort_values('start')
    return {lid: list(zip(g['start'].dt.to_pydatetime(), g['end'].dt.to_pydatetime(), g['level']))
            for lid, g in df.groupby('logId')}


def build(base_dir, events: list[dict]) -> pd.DataFrame:
    """全期間のチェックポイント。列: date（起床日）, checkpoint, time（tz 付き ISO）, source"""
    sleeps = {e['attrs']['date_of_sleep']: e for e in events if e['kind'] == 'sleep'}
    states = load_states(base_dir, (*PHONE_ALIVE, PHONE_ALARM))
    steps = load_steps(base_dir)
    stages = load_stages(base_dir)
    alarm_dates = {t.date().isoformat() for t in alarm_times(states)}
    rows = []
    for d in sorted(set(sleeps) | alarm_dates):
        wake = dt.date.fromisoformat(d)
        lo, hi = night_window(wake)
        sl = sleeps.get(d)
        i = Inputs(wake_date=wake, sleep=sl,
                   stages=stages.get(str(sl['attrs'].get('log_id')), []) if sl else [],
                   steps=steps[lo:hi], states=states)
        rows += [(d, name, t.isoformat(timespec='seconds'), src) for name, t, src in judge(i)]
    return pd.DataFrame(rows, columns=['date', 'checkpoint', 'time', 'source'])
