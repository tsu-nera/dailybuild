#!/usr/bin/env python
# coding: utf-8
"""
観察日記: 環境データから生活日1日ぶんの行動の時系列を作る（#209）

reports/observation/YYYY-MM-DD.md を全上書きで生成する。LLM は使わない。区切り（離床・出発・
帰宅・入眠…）には根拠を付け、材料が欠けた区切りは別の材料で埋めずに空けておく。
生活日は day_start_hour（既定4時）から翌日の同時刻まで。

答え合わせ（本人の申告など）は reports/observation/labels.csv に1行ずつ足す:
    date,landmark,time,source,note
    2026-10-17,離床,10:05,本人,カーテンを開けた
date は生活日、landmark は区切りの名前、time は HH:MM（翌日の 0〜4時はそのまま書く）。

Usage:
    uv run scripts/observation.py build                # 昨日と一昨日（遅れて届く同期を拾う）
    uv run scripts/observation.py build --days 3
    uv run scripts/observation.py build --date 2026-10-17
    uv run scripts/observation.py eval                 # labels.csv との答え合わせ
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import csv
import datetime as dt
import json

import yaml

from lib.clients.homeassistant_client import HomeAssistantError
from lib.observation.ha import JST, fetch_history
from lib.observation.landmarks import LANDMARKS, DayData, judge, source_status, window
from lib.observation.timeline import items, render, unknown_gaps
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
CONFIG = BASE_DIR / 'config' / 'observation.yaml'
EVENTS_JSONL = BASE_DIR / 'reports' / 'events.jsonl'
SLEEP_LEVELS = BASE_DIR / 'data' / 'wearable' / 'sleep_levels.csv'
OUT_DIR = BASE_DIR / 'reports' / 'observation'
LABELS = OUT_DIR / 'labels.csv'


def load_config() -> dict:
    with open(CONFIG, encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_events() -> list[dict]:
    with open(require_private_path(EVENTS_JSONL), encoding='utf-8') as f:
        events = [json.loads(line) for line in f if line.strip()]
    for e in events:
        e['start'] = dt.datetime.fromisoformat(e['start'])
        e['end'] = dt.datetime.fromisoformat(e['end']) if e['end'] else None
    return events


def load_levels(log_ids: set[str]) -> dict:
    """{log_id: [(開始, 終了, level)]}。isShort の覚醒は短い覚醒なので落とす"""
    out = {}
    with open(require_private_path(SLEEP_LEVELS), encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['logId'] not in log_ids or r['isShort'] == 'True':
                continue
            t = dt.datetime.fromisoformat(r['dateTime']).replace(tzinfo=JST)
            out.setdefault(r['logId'], []).append((t, t + dt.timedelta(seconds=int(r['seconds'])), r['level']))
    for v in out.values():
        v.sort()
    return out


def load_labels() -> dict:
    """{生活日: {区切り: 時刻}}"""
    path = require_private_path(LABELS)
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding='utf-8') as f:
        for r in csv.DictReader(f):
            day = dt.date.fromisoformat(r['date'])
            h, m = map(int, r['time'].split(':'))
            t = dt.datetime.combine(day, dt.time(h, m), JST)
            if h < load_config()['day_start_hour']:
                t += dt.timedelta(days=1)
            out.setdefault(day, {})[r['landmark']] = t
    return out


def entity_ids(cfg) -> list[str]:
    e = cfg['entities']
    return [*e['lights'], e['noise'], e['illuminance'], e['speaker'],
            *e['phone'].values(), *e['pc'].values()]


def day_data(day: dt.date, cfg, events) -> DayData:
    lo, hi = window(day, cfg['day_start_hour'], JST)
    hist = fetch_history(lo, min(hi, dt.datetime.now(JST)), entity_ids(cfg))
    near = [e for e in events if lo - dt.timedelta(days=1) <= e['start'] < hi + dt.timedelta(days=1)]
    ids = {str(e['attrs'].get('log_id')) for e in near if e['kind'] == 'sleep'}
    return DayData(day=day, lo=lo, hi=hi, cfg=cfg, hist=hist, events=near, levels=load_levels(ids))


def cmd_build(args) -> int:
    cfg = load_config()
    today = dt.datetime.now(JST).date()
    if args.date:
        days = [dt.date.fromisoformat(args.date)]
    else:
        days = [today - dt.timedelta(days=i) for i in range(args.days, 0, -1)]
    events = load_events()
    labels = load_labels()
    out_dir = ensure_dir(require_private_path(OUT_DIR))
    for day in days:
        try:
            d = day_data(day, cfg, events)
        except HomeAssistantError as exc:
            print(f'エラー: HA の履歴を読めない: {exc}', file=sys.stderr)
            return 1
        rows = items(d)
        text = render(d, judge(d), labels.get(day, {}), rows, unknown_gaps(d, rows), source_status(d))
        path = out_dir / f'{day}.md'
        path.write_text(text, encoding='utf-8')
        print(f'{day}: {path}')
    return 0


def cmd_eval(args) -> int:
    cfg = load_config()
    labels = load_labels()
    if not labels:
        print(f'答え合わせが無い: {LABELS}', file=sys.stderr)
        return 1
    events = load_events()
    errors = {}
    print('| 生活日 | 区切り | 推定 | 正解 | ズレ | 根拠 |')
    print('|---|---|---|---|---|---|')
    for day in sorted(labels):
        try:
            lms = {lm.name: lm for lm in judge(day_data(day, cfg, events))}
        except HomeAssistantError as exc:
            print(f'エラー: HA の履歴を読めない: {exc}', file=sys.stderr)
            return 1
        for name, truth in sorted(labels[day].items(), key=lambda kv: LANDMARKS.index(kv[0])
                                  if kv[0] in LANDMARKS else 99):
            lm = lms.get(name)
            if lm is None:
                print(f'| {day} | {name} | (未定義の区切り) | {truth:%H:%M} | - | - |')
                continue
            if lm.time is None:
                errors.setdefault(name, []).append(None)
                print(f'| {day} | {name} | 不明 | {truth:%H:%M} | - | {lm.basis} |')
                continue
            m = round((lm.time - truth).total_seconds() / 60)
            errors.setdefault(name, []).append(m)
            print(f'| {day} | {name} | {lm.time:%H:%M} | {truth:%H:%M} | {m:+d}分 | {lm.basis} |')
    print('\n| 区切り | 件数 | 不明 | 平均絶対誤差 |')
    print('|---|---|---|---|')
    for name in sorted(errors, key=lambda n: LANDMARKS.index(n)):
        ms = [m for m in errors[name] if m is not None]
        mae = f'{sum(abs(m) for m in ms) / len(ms):.0f}分' if ms else '-'
        print(f'| {name} | {len(errors[name])} | {len(errors[name]) - len(ms)} | {mae} |')
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='観察日記を全上書きで生成する')
    b.add_argument('--date', help='生活日（YYYY-MM-DD）。当日も指定できる（未完了と出る）')
    b.add_argument('--days', type=int, default=2, help='昨日から遡る日数（既定2）')
    b.set_defaults(func=cmd_build)
    e = sub.add_parser('eval', help='labels.csv との答え合わせ')
    e.set_defaults(func=cmd_eval)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
