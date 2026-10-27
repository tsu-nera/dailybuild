#!/usr/bin/env python
# coding: utf-8
"""
Google Forms のレジストリ（config/forms.yaml）を扱う

Usage:
    uv run scripts/forms.py list                         # レジストリの表示
    uv run scripts/forms.py show --review daily --days 7 # daily-review が読む active フォームの show
    uv run scripts/forms.py fetch-list                   # 日次で fetch するフォーム（key<TAB>表示名）
    uv run scripts/forms.py fetch daily_morning          # 1フォームの fetch（daily-fetch.sh が呼ぶ）
"""

import argparse
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib import forms_registry  # noqa: E402


def _run(argv) -> int:
    return subprocess.run([sys.executable, *argv], cwd=project_root).returncode


def cmd_list(args):
    forms = forms_registry.load_forms()
    print('| key | 表示名 | status | cadence | 許容遅れ | review | CSV |')
    print('|---|---|---|---|---|---|---|')
    for f in forms:
        stale = '-' if f.stale_after_days is None else f'{f.stale_after_days}日'
        print(f'| {f.key} | {f.name} | {f.status} | {f.cadence} | {stale} '
              f'| {f.review or "-"} | {f.csv} |')
    return 0


def cmd_fetch_list(args):
    for f in forms_registry.fetch_forms(forms_registry.load_forms()):
        print(f'{f.key}\t{f.name}')
    return 0


def cmd_fetch(args):
    forms = {f.key: f for f in forms_registry.load_forms()}
    if args.key not in forms:
        print(f'未登録のフォーム: {args.key}', file=sys.stderr)
        return 2
    return _run(forms[args.key].fetch)


def cmd_show(args):
    forms = forms_registry.review_forms(forms_registry.load_forms(), args.review)
    failed = []
    for i, f in enumerate(forms):
        if i:
            print(flush=True)
        if _run([*f.show, '--days', str(args.days)]) != 0:
            failed.append(f.name)
    if failed:
        print(f"show に失敗: {'、'.join(failed)}", file=sys.stderr)
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description='Google Forms のレジストリ')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('list', help='レジストリを表示する').set_defaults(func=cmd_list)

    sub.add_parser('fetch-list', help='日次で fetch するフォームを key<TAB>表示名 で出す'
                   ).set_defaults(func=cmd_fetch_list)

    p_fetch = sub.add_parser('fetch', help='1フォームの fetch を実行する')
    p_fetch.add_argument('key')
    p_fetch.set_defaults(func=cmd_fetch)

    p_show = sub.add_parser('show', help='レビューが読む active フォームの show を順に実行する')
    p_show.add_argument('--review', required=True, choices=forms_registry.REVIEWS)
    p_show.add_argument('--days', type=int, default=7, help='直近N日（既定 7）')
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
