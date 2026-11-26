#!/usr/bin/env python
# coding: utf-8
"""習慣（Toggl Focus のクライアント「良い習慣」「悪い習慣」）の日次表

習慣1つ = Toggl Focus のプロジェクト1つ。何を習慣として見るかは config/habits.yaml の
クライアントに属するプロジェクトで決まる。手入力の記録も `toggl push` の自動の記録
（auto タグ）も同じ規則で数える。良い習慣の週の目標は config/private/habits.yaml の target_per_week。

Usage:
    python scripts/habits.py build   # focus_entries.csv + focus_projects.csv → reports/habits_daily.csv（全上書き）

入力の focus_projects.csv は `toggl.py fetch-focus` が書く。build は設定とのずれ
（target_per_week の無い良い習慣、良い習慣のアーカイブされていないプロジェクトに無い yaml の名前）
があっても habits_daily.csv を書いたうえで、名前を stderr に出して非ゼロで終わる
（日次では daily-fetch.sh の失敗ステップとして出る）。

週ごとの日数は lib/habits/weekly.py（Grafana の「目標」画面と habits-review が読む）。設計は docs/habits.md。
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd

from lib.habits.config import HABITS_DAILY_CSV, load_clients, load_roster
from lib.habits.daily import build_habits_daily
from lib.habits.weekly import drift
from lib.toggl import focus as toggl_focus
from lib.toggl import store
from lib.utils.private_data import ensure_dir, require_private_path


def today() -> dt.date:
    return dt.date.today()


def load_entries() -> pd.DataFrame:
    path = store.FOCUS_CSV_FILE
    if not path.exists():
        return pd.DataFrame(columns=['project_id', 'start'])
    return pd.read_csv(path, dtype={'start': str})


def report_drift(projects: pd.DataFrame, clients: dict, roster: dict) -> bool:
    """ずれを stderr に出す。ずれがあれば True"""
    no_target, unknown = drift(projects, clients, roster)
    if no_target:
        print('target_per_week が無い良い習慣: ' + ' / '.join(no_target), file=sys.stderr)
    if unknown:
        print('良い習慣のアーカイブされていないプロジェクトに無い名前（config/private/habits.yaml）: '
              + ' / '.join(unknown), file=sys.stderr)
    return bool(no_target or unknown)


def cmd_build(_args) -> int:
    csv_path = require_private_path(HABITS_DAILY_CSV)
    projects = toggl_focus.load_projects()
    if projects.empty:
        print(f'{toggl_focus.PROJECTS_CSV_FILE} がありません。先に `toggl.py fetch-focus` を実行してください',
              file=sys.stderr)
        return 1
    clients = load_clients()
    daily = build_habits_daily(load_entries(), projects, clients, today())
    ensure_dir(csv_path.parent)
    daily.to_csv(csv_path, index=False)
    print(f'habits: {daily["habit"].nunique()}件 {len(daily)}行  {csv_path}', file=sys.stderr)
    # ずれは書いた後に見る（設定の不備で日次表を止めない）
    return 1 if report_drift(projects, clients, load_roster()) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='習慣（Toggl Focus）')
    sub = parser.add_subparsers(dest='command', required=True)
    p_build = sub.add_parser('build', help='reports/habits_daily.csv を全上書きで作り、設定とのずれを検出する')
    p_build.set_defaults(func=cmd_build)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
