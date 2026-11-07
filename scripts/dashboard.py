#!/usr/bin/env python3
"""
週の目標ダッシュボード（claude.ai の Artifact）に載せる数値を JSON に書き出す

ページ（scripts/dashboard/index.html）は数値を持たない。数値はこの JSON 1本で、
Artifact へは agent が添付ファイルとして上げ直す（スクリプトからは公開できない）。
目標値は config/targets.yaml（睡眠）と config/exercise_muscles.yaml の weekly_sets（筋トレ）
から読むので、目標を書き換えればダッシュボードも追随する。

Usage:
    uv run scripts/dashboard.py build [--weeks 8] [--out tmp/dashboard/goals.json]
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib import hevy_csv  # noqa: E402
from lib.analytics import sleep as sleep_lib  # noqa: E402
from lib.analytics import workout  # noqa: E402
from lib.analytics.sleep.rise import load_steps, minutes_late, rise_time  # noqa: E402
from lib.utils.private_data import require_private_path  # noqa: E402
from lib.utils.targets import get_target  # noqa: E402

SLEEP_CSV = project_root / 'data/wearable/sleep.csv'
STEPS_CSV = project_root / 'data/wearable/steps_intraday.csv'
WORKOUTS_CSV = project_root / 'data/hevy/workouts.csv'

# 週の睡眠時間の目安。bed_time の宣言（rise_time − 睡眠7時間 − 入眠15分）と同じ7時間
SLEEP_PER_NIGHT_H = 7


def _week_label(d: dt.date) -> str:
    iso = d.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def _hm(ts) -> str | None:
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime('%H:%M')


def _main_sleep(lo: dt.date, hi: dt.date) -> pd.DataFrame:
    df = pd.read_csv(require_private_path(SLEEP_CSV))
    df = df[df['isMainSleep'].astype(str).str.lower().isin(['true', '1'])].copy()
    df['date'] = pd.to_datetime(df['dateOfSleep']).dt.date
    df = df[(df['date'] >= lo) & (df['date'] <= hi)]
    # 同じ日に主睡眠が2本ある日は長い方（重なりセッションは取得側で除外済み）
    return df.sort_values('minutesAsleep').drop_duplicates('date', keep='last').sort_values('date')


def _debt_by_day(lo: dt.date, hi: dt.date) -> dict:
    """journal_skeleton と同じ build_debt_calculator。片方だけ条件を変えると負債が2つになる"""
    calc = sleep_lib.build_debt_calculator(pd.read_csv(require_private_path(SLEEP_CSV)))
    out = {}
    for day in pd.date_range(lo, hi, freq='D'):
        try:
            r = calc.calculate(end_date=day, weight_method=sleep_lib.DEBT_WEIGHT_METHOD)
        except ValueError:
            continue
        out[day.date()] = round(r.sleep_debt_hours, 1)
    return out


def build_sleep(lo: dt.date, hi: dt.date, bed_target: str | None, rise_target: str | None):
    df = _main_sleep(lo, hi)
    steps = load_steps(STEPS_CSV) if STEPS_CSV.exists() else pd.Series(dtype=float)
    debt = _debt_by_day(lo, hi)
    by_date = {r['date']: r for _, r in df.iterrows()}

    nights = []
    for day in pd.date_range(lo, hi, freq='D').date:
        r = by_date.get(day)
        row = {'date': day.isoformat(), 'week': _week_label(day), 'weekday': day.weekday() < 5,
               'sleep_h': None, 'bed': None, 'bed_late_min': None,
               'rise': None, 'rise_late_min': None, 'debt_h': debt.get(day)}
        if r is not None:
            start = pd.to_datetime(r['startTime'])
            wakeup = pd.to_datetime(r['endTime']) - pd.Timedelta(minutes=r['minutesAfterWakeup'] or 0)
            rise = rise_time(steps, wakeup)
            row.update({
                'sleep_h': round(r['minutesAsleep'] / 60, 1),
                'bed': _hm(start),
                'bed_late_min': minutes_late(start, bed_target, evening=True) if bed_target else None,
                'rise': _hm(rise),
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


def build_sets(week_labels: list[str]):
    targets = workout.load_weekly_set_targets()
    if not WORKOUTS_CSV.exists() or not targets:
        return [], None
    df = hevy_csv.parse_hevy_csv(WORKOUTS_CSV)
    table, _ = workout.weekly_muscle_sets(df, workout.load_muscle_mapping(), week_labels)
    rows = []
    for wk in week_labels:
        for p in workout.weekly_set_progress(table, wk, targets):
            rows.append({'week': wk, 'muscle': p['label'], 'sets': p['actual'],
                         'target': p['target'], 'remaining': p['remaining']})
    last = pd.to_datetime(df['start_dt']).max()
    return rows, (None if pd.isna(last) else last.date().isoformat())


def cmd_build(args) -> int:
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    lo = monday - dt.timedelta(weeks=args.weeks - 1)
    bed_target, rise_target = get_target('bed_time'), get_target('rise_time')

    nights, weeks = build_sleep(lo, today, bed_target, rise_target)
    week_labels = [w['week'] for w in weeks]
    sets, last_hevy = build_sets(week_labels)
    last_sleep = max((n['date'] for n in nights if n['sleep_h'] is not None), default=None)

    out = {
        'status': [{
            'generated_at': dt.datetime.now().astimezone().isoformat(timespec='minutes'),
            'today': today.isoformat(),
            'this_week': _week_label(today),
            'last_sleep_date': last_sleep,
            'last_hevy_date': last_hevy,
            'bed_target': bed_target,
            'rise_target': rise_target,
            'debt_target_h': get_target('sleep_debt_h'),
            'sleep_per_night_h': SLEEP_PER_NIGHT_H,
        }],
        'nights': nights,
        'weeks': weeks,
        'sets': sets,
    }
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f'{path}  nights={len(nights)} weeks={len(weeks)} sets={len(sets)}', file=sys.stderr)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='ダッシュボード用の JSON を書き出す')
    b.add_argument('--weeks', type=int, default=8)
    b.add_argument('--out', default=str(project_root / 'tmp/dashboard/goals.json'))
    b.set_defaults(func=cmd_build)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
