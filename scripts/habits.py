#!/usr/bin/env python
# coding: utf-8
"""習慣（Toggl Focus のクライアント「良い習慣」「悪い習慣」）の日次表と週次の集計

習慣1つ = Toggl Focus のプロジェクト1つ。何を習慣として見るかは config/habits.yaml の
クライアントに属するプロジェクトで決まる（アーカイブ済みは show の表から外す）。
良い習慣の週の目標は config/private/habits.yaml の target_per_week。

Usage:
    python scripts/habits.py build              # focus_entries.csv + focus_projects.csv → reports/habits_daily.csv（全上書き）
    python scripts/habits.py show               # 週ごとの実施日数（既定4週。進行中の週を含む）
    python scripts/habits.py show --weeks 13

入力の focus_projects.csv は `toggl.py fetch-focus` が書く。show は設定とのずれ
（target_per_week の無い良い習慣、Toggl に無い yaml の名前）があると、表を出したうえで
名前を stderr に出して非ゼロで終わる。設計は docs/habits.md。
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd
import yaml

from lib.habits.daily import HABITS_DAILY_COLUMNS, build_habits_daily
from lib.habits.show import drift, render_show
from lib.toggl import focus as toggl_focus
from lib.toggl import store
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
HABITS_DAILY_CSV = BASE_DIR / 'reports' / 'habits_daily.csv'
CLIENTS_YAML = BASE_DIR / 'config' / 'habits.yaml'
# 習慣名そのものが非公開なので private 側に置く（dailybuild は public）
ROSTER_YAML = BASE_DIR / 'config' / 'private' / 'habits.yaml'

DEFAULT_WEEKS = 4


def today() -> dt.date:
    return dt.date.today()


def load_clients() -> dict:
    """{'good': <クライアント名>, 'bad': <クライアント名>}"""
    clients = (yaml.safe_load(CLIENTS_YAML.read_text()) or {}).get('clients') or {}
    missing = [k for k in ('good', 'bad') if not clients.get(k)]
    if missing:
        raise ValueError(f'{CLIENTS_YAML} の clients に {"/".join(missing)} がありません')
    return clients


def load_roster() -> dict:
    """良い習慣のプロジェクト名 → {target_per_week}。**無ければ落とす**

    空で続けると全習慣が目標なしになり、ずれとしてしか気づけない。
    """
    path = require_private_path(ROSTER_YAML)
    if not path.exists():
        raise FileNotFoundError(f'習慣の設定がありません: {path}\n'
                                'dailybuild-private の config/habits.yaml を確認してください。')
    roster = (yaml.safe_load(path.read_text()) or {}).get('habits') or {}
    return {name: (spec or {}) for name, spec in roster.items()}


def load_entries() -> pd.DataFrame:
    path = store.FOCUS_CSV_FILE
    if not path.exists():
        return pd.DataFrame(columns=['project_id', 'start'])
    return pd.read_csv(path, dtype={'start': str})


def cmd_build(_args) -> int:
    csv_path = require_private_path(HABITS_DAILY_CSV)
    projects = toggl_focus.load_projects()
    if projects.empty:
        print(f'{toggl_focus.PROJECTS_CSV_FILE} がありません。先に `toggl.py fetch-focus` を実行してください',
              file=sys.stderr)
        return 1
    daily = build_habits_daily(load_entries(), projects, load_clients(), today())
    ensure_dir(csv_path.parent)
    daily.to_csv(csv_path, index=False)
    print(f'habits: {daily["habit"].nunique()}件 {len(daily)}行  {csv_path}', file=sys.stderr)
    return 0


def cmd_show(args) -> int:
    path = require_private_path(HABITS_DAILY_CSV)
    daily = (pd.read_csv(path, dtype={'date': str, 'habit': str}) if path.exists()
             else pd.DataFrame(columns=HABITS_DAILY_COLUMNS))
    projects = toggl_focus.load_projects()
    clients = load_clients()
    roster = load_roster()
    print(render_show(daily, projects, clients, roster, today(), args.weeks), end='')

    no_target, unknown = drift(projects, clients, roster)
    if no_target:
        print('target_per_week が無い良い習慣: ' + ' / '.join(no_target), file=sys.stderr)
    if unknown:
        print('良い習慣のアーカイブされていないプロジェクトに無い名前（config/private/habits.yaml）: '
              + ' / '.join(unknown), file=sys.stderr)
    return 1 if no_target or unknown else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='習慣（Toggl Focus）')
    sub = parser.add_subparsers(dest='command', required=True)
    p_build = sub.add_parser('build', help='reports/habits_daily.csv を全上書きで作る')
    p_build.set_defaults(func=cmd_build)
    p_show = sub.add_parser('show', help='週ごとの実施日数を出す')
    p_show.add_argument('--weeks', type=int, default=DEFAULT_WEEKS,
                        help=f'さかのぼる週数（進行中の週を含む。既定 {DEFAULT_WEEKS}）')
    p_show.set_defaults(func=cmd_show)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
