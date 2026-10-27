#!/usr/bin/env python
# coding: utf-8
"""
Google Forms のレジストリ（config/forms.yaml）を扱う

Usage:
    uv run scripts/forms.py list                         # レジストリの表示
    uv run scripts/forms.py show --review daily --days 7 # daily-review が読む active フォームの show
    uv run scripts/forms.py show daily_evening --days 7  # 1フォームの show
    uv run scripts/forms.py fetch-list                   # 日次で fetch するフォーム（key<TAB>表示名）
    uv run scripts/forms.py fetch daily_morning          # 1フォームの fetch（daily-fetch.sh が呼ぶ）
    uv run scripts/forms.py setup-form <key> [--update]  # 汎用フォームの生成・yaml への同期

レジストリで fetch / show を省略したフォームは、config/<key>_def.yaml だけで動く
汎用の処理（lib.forms.generic）を使う。fetch / show を書いたフォームはその
スクリプトへ委譲する。
"""

import argparse
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib import forms_registry  # noqa: E402
from lib.forms import cli, generic  # noqa: E402


def _run(argv) -> int:
    return subprocess.run([sys.executable, *argv], cwd=project_root).returncode


def _find(key):
    forms = {f.key: f for f in forms_registry.load_forms()}
    if key not in forms:
        print(f'未登録のフォーム: {key}', file=sys.stderr)
        return None
    return forms[key]


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
    form = _find(args.key)
    if form is None:
        return 2
    if not form.generic_fetch:
        return _run(form.fetch)
    paths = generic.paths_for(form.key, form.csv)
    # daily-fetch.sh はフラグを渡さずに呼ぶ。日次の無人実行で
    # ブラウザを開いて止まらないよう、汎用 fetch は常に非対話で認可する
    generic.fetch(generic.load(paths), paths, non_interactive=True)
    return 0


def cmd_setup_form(args):
    form = _find(args.key)
    if form is None:
        return 2
    if not form.generic_fetch:
        print(f'{form.key} は固有のスクリプトを持つ（{" ".join(form.fetch)}）。'
              'そちらの setup-form を使うこと', file=sys.stderr)
        return 2
    paths = generic.paths_for(form.key, form.csv)
    generic.setup_form(lambda: generic.load(paths), paths.def_file, args)
    return 0


def _show_one(form, days) -> int:
    if form.show is None:
        print(f'{form.key} は show を持たない', file=sys.stderr)
        return 1
    if not form.generic_show:
        return _run([*form.show, '--days', str(days)])
    paths = generic.paths_for(form.key, form.csv)
    generic.show(generic.load(paths), paths.csv_file, form.name, days)
    # --review では subprocess の show と並ぶので、出力順を崩さない
    sys.stdout.flush()
    return 0


def cmd_show(args):
    if (args.key is None) == (args.review is None):
        print('key か --review のどちらか一方を指定すること', file=sys.stderr)
        return 2
    if args.key is not None:
        form = _find(args.key)
        return 2 if form is None else _show_one(form, args.days)

    forms = forms_registry.review_forms(forms_registry.load_forms(), args.review)
    failed = []
    for i, f in enumerate(forms):
        if i:
            print(flush=True)
        if _show_one(f, args.days) != 0:
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

    p_setup = sub.add_parser('setup-form', help='汎用フォームを生成する・yaml に合わせる')
    p_setup.add_argument('key')
    cli.add_setup_arguments(p_setup)
    p_setup.set_defaults(func=cmd_setup_form)

    p_show = sub.add_parser('show', help='1フォーム、またはレビューが読む active フォームの show')
    p_show.add_argument('key', nargs='?')
    p_show.add_argument('--review', choices=forms_registry.REVIEWS)
    p_show.add_argument('--days', type=int, default=7, help='直近N日（既定 7）')
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
