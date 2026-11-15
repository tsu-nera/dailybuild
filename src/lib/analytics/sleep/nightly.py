"""夜ごと・週ごとの睡眠の集計（早起きの判定・週の目安・負債）

画面（scripts/dashboard.py が Grafana 用の CSV に並べる）と計算を分けるため、判定の定義はここに置く。
"""
import datetime as dt
from pathlib import Path

import pandas as pd

from .rise import load_steps, minutes_late, rise_time
from .sleep_debt_clean import DEBT_WEIGHT_METHOD, build_debt_calculator

# 週の睡眠時間の目安。bed_time の宣言（rise_time − 睡眠7時間 − 入眠15分）と同じ7時間
SLEEP_PER_NIGHT_H = 7


def week_label(d: dt.date) -> str:
    iso = d.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def hm(ts) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime('%H:%M')


def main_sleep(raw: pd.DataFrame, lo: dt.date, hi: dt.date) -> pd.DataFrame:
    df = raw[raw['isMainSleep'].astype(str).str.lower().isin(['true', '1'])].copy()
    df['date'] = pd.to_datetime(df['dateOfSleep']).dt.date
    df = df[(df['date'] >= lo) & (df['date'] <= hi)]
    # 同じ日に主睡眠が2本ある日は長い方（重なりセッションは取得側で除外済み）
    return df.sort_values('minutesAsleep').drop_duplicates('date', keep='last').sort_values('date')


def debt_by_day(raw: pd.DataFrame, lo: dt.date, hi: dt.date) -> dict:
    """journal_skeleton と同じ build_debt_calculator。片方だけ条件を変えると負債が2つになる"""
    calc = build_debt_calculator(raw)
    out = {}
    for day in pd.date_range(lo, hi, freq='D'):
        try:
            r = calc.calculate(end_date=day, weight_method=DEBT_WEIGHT_METHOD)
        except ValueError:
            continue
        out[day.date()] = round(r.sleep_debt_hours, 1)
    return out


def build_nights(lo: dt.date, hi: dt.date, bed_target: str | None, rise_target: str | None,
                sleep_csv: Path, steps_csv: Path):
    raw = pd.read_csv(sleep_csv)
    df = main_sleep(raw, lo, hi)
    steps = load_steps(steps_csv) if steps_csv.exists() else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    debt = debt_by_day(raw, lo, hi)
    by_date = {r['date']: r for _, r in df.iterrows()}

    nights = []
    for day in pd.date_range(lo, hi, freq='D').date:
        r = by_date.get(day)
        row = {'date': day.isoformat(), 'week': week_label(day), 'weekday': day.weekday() < 5,
               'sleep_h': None, 'bed': None, 'bed_late_min': None,
               'rise': None, 'rise_late_min': None, 'debt_h': debt.get(day)}
        if r is not None:
            start = pd.to_datetime(r['startTime'])
            wakeup = pd.to_datetime(r['endTime']) - pd.Timedelta(minutes=r['minutesAfterWakeup'] or 0)
            rise = rise_time(steps, wakeup)
            row.update({
                'sleep_h': round(r['minutesAsleep'] / 60, 1),
                'bed': hm(start),
                'bed_late_min': minutes_late(start, bed_target, evening=True) if bed_target else None,
                'rise': hm(rise),
                'rise_late_min': minutes_late(rise, rise_target) if rise_target and rise is not None else None,
            })
        nights.append(row)

    weeks = []
    for wk in dict.fromkeys(n['week'] for n in nights):
        ns = [n for n in nights if n['week'] == wk]
        rec = [n for n in ns if n['sleep_h'] is not None]
        bed = [n for n in ns if n['weekday'] and n['bed_late_min'] is not None]
        rise = [n for n in ns if n['weekday'] and n['rise_late_min'] is not None]
        debts = [n['debt_h'] for n in ns if n['debt_h'] is not None]
        weeks.append({
            'week': wk,
            'days': len(ns),
            'nights': len(rec),
            'total_h': round(sum(n['sleep_h'] for n in rec), 1),
            # 欠測の夜は0として足さない。目安は記録のある夜の数 × 7h
            'goal_h': len(rec) * SLEEP_PER_NIGHT_H,
            'avg_h': round(sum(n['sleep_h'] for n in rec) / len(rec), 1) if rec else None,
            'bed_hit': sum(n['bed_late_min'] <= 0 for n in bed), 'bed_n': len(bed),
            'rise_hit': sum(n['rise_late_min'] <= 0 for n in rise), 'rise_n': len(rise),
            'debt_end_h': debts[-1] if debts else None,
        })
    return nights, weeks
