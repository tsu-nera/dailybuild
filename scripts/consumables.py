#!/usr/bin/env python3
"""
消耗品の台帳（data/inventory/consumables.csv）に品目を1行足し、Grafana 用の2本を作り直して push する

台帳の書き手を vaio に寄せるための入口。agent は ssh で1回叩くだけでよい:
dailybuild-private を pull → 末尾に追記 → reports/dashboard の consumables*.csv を再生成
→ consumables.csv だけを commit → push（弾かれたら pull --rebase して1回だけやり直す）。
列は台帳のヘッダから取り、引数で渡さなかった列は空。key が既にあれば何もせず exit 1。
ログは stderr。

Usage:
    uv run scripts/consumables.py add <key> --name <品目名> --category <カテゴリ> --unit <kg|個 など>
                                      [--location <場所>] [--note <メモ>]
"""

import argparse
import csv
import datetime as dt
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.utils.private_data import require_private_path  # noqa: E402

CONSUMABLES_CSV = project_root / 'data/inventory/consumables.csv'


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    log(f'$ git -C {repo} {" ".join(args)}')
    return subprocess.run(['git', '-C', str(repo), *args], text=True)


def append_row(path: Path, values: dict[str, str]) -> bool:
    """ヘッダに沿って1行足す。key が既にあれば False。ヘッダに無い列名は ValueError"""
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    rows = list(csv.reader(text.splitlines()))
    header = rows[0]
    unknown = [k for k in values if k not in header]
    if unknown:
        raise ValueError(f'{path} のヘッダに無い列: {unknown}（ヘッダ: {header}）')
    key_idx = header.index('key')
    if any(r and r[key_idx] == values['key'] for r in rows[1:]):
        return False
    newline = '\r\n' if b'\r\n' in raw else '\n'
    with path.open('a', newline='', encoding='utf-8') as f:
        if text and not text.endswith(('\n', '\r')):
            f.write(newline)
        csv.writer(f, lineterminator=newline).writerow([values.get(c, '') for c in header])
    return True


def regenerate_dashboard() -> None:
    # dashboard.py は scripts/ 直下。このスクリプトと同じディレクトリなので sys.path[0] から import できる
    from dashboard import CSV_DIR, consumable_tables, write_csvs
    for p in write_csvs(consumable_tables(dt.date.today()), CSV_DIR):
        log(f'  {p}')


def commit_and_push(repo: Path, path: Path, message: str) -> int:
    """path だけを commit する（他の未コミット・stage 済み変更は巻き込まない）"""
    rel = str(path.relative_to(repo))
    if git(repo, 'add', '--', rel).returncode != 0:
        return 1
    if git(repo, 'commit', '-m', message, '--', rel).returncode != 0:
        return 1
    if git(repo, 'push').returncode == 0:
        return 0
    log('push が弾かれたので pull --rebase してやり直す')
    if git(repo, 'pull', '--rebase', '--autostash').returncode != 0:
        return 1
    return 0 if git(repo, 'push').returncode == 0 else 1


def add(csv_path: Path, values: dict[str, str], regenerate=regenerate_dashboard) -> int:
    real = csv_path.resolve()
    repo = real.parent
    top = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--show-toplevel'],
                         capture_output=True, text=True, check=True).stdout.strip()
    repo = Path(top)

    if git(repo, 'pull', '--rebase', '--autostash').returncode != 0:
        log('pull に失敗したので止める')
        return 1
    if not append_row(real, values):
        log(f'key={values["key"]} は既にある。何もしない')
        return 1
    log(f'追記: {real}  key={values["key"]}')

    status = 0
    try:
        regenerate()
    except Exception as e:  # 台帳の commit を優先し、再生成の失敗は終了コードで知らせる
        log(f'Grafana 用 CSV の再生成に失敗: {e!r}')
        status = 1

    if commit_and_push(repo, real, f'consumables: add {values["key"]}') != 0:
        log('commit / push に失敗')
        return 1
    return status


def cmd_add(args) -> int:
    values = {'key': args.key, 'name': args.name, 'category': args.category, 'unit': args.unit}
    if args.location is not None:
        values['location'] = args.location
    if args.note is not None:
        values['note'] = args.note
    try:
        return add(require_private_path(CONSUMABLES_CSV), values)
    except ValueError as e:
        log(str(e))
        return 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add', help='品目を1行足し、Grafana 用の2本を作り直して commit・push する')
    a.add_argument('key')
    a.add_argument('--name', required=True)
    a.add_argument('--category', required=True)
    a.add_argument('--unit', required=True)
    a.add_argument('--location')
    a.add_argument('--note')
    a.set_defaults(func=cmd_add)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
