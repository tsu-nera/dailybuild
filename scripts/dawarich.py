#!/usr/bin/env python
# coding: utf-8
"""
Dawarich（位置のライフログ、#290）の後始末 CLI（name-places）

Dawarich の DB は取り込み直すたびに作り直されるので、手で直さずにこれを流し直す。
Dawarich が動いているホスト（mouse）の dailybuild で実行する（docker compose で app コンテナに入る）。

Usage:
    python scripts/dawarich.py name-places --dry-run   # 何件に名前が付き、何件 Places API を引くかだけ出す
    python scripts/dawarich.py name-places             # Unknown の Place を改名して名前を固定する

名前の決め方は src/lib/dawarich/place_names.py。手で決める名前は config/private/dawarich_place_names.yaml
（`<place ID>: {name: ..., note: ...}`）。Places API のキーは .env の GOOGLE_MAPS_API_KEY。
"""

import argparse
import datetime as dt
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd

from lib import timeline
from lib.clients import places_client
from lib.dawarich import place_names
from lib.utils.env import require_env

BASE_DIR = Path(__file__).parent.parent
COMPOSE_DIR = BASE_DIR / 'scripts' / 'ops' / 'dawarich'
RAILS_DIR = COMPOSE_DIR / 'rails'
OVERRIDES_YAML = BASE_DIR / 'config' / 'private' / 'dawarich_place_names.yaml'
PLACES_CSV = BASE_DIR / 'data' / 'timeline' / 'places.csv'
VISITS_CSV = BASE_DIR / 'data' / 'timeline' / 'visits.csv'
RESULT_PREFIX = 'RESULT_JSON:'

log = logging.getLogger('dawarich')


def _compose(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ['docker', 'compose', '--project-directory', str(COMPOSE_DIR), *args],
        check=True, text=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL)
    return result.stdout or ''


def rails_runner(script: Path, *files: Path):
    """script を app コンテナで流し、RESULT_JSON の行を読んで返す。files はコンテナの /tmp へ置いて引数で渡す"""
    container_args = []
    for path in (script, *files):
        dest = f'/tmp/dailybuild_{path.name}'
        _compose('cp', str(path), f'app:{dest}')
        container_args.append(dest)
    out = _compose('exec', '-T', 'app', 'bin/rails', 'runner', *container_args, capture=True)
    lines = [line for line in out.splitlines() if line.startswith(RESULT_PREFIX)]
    if not lines:
        raise RuntimeError(f'{script.name} が結果を出さなかった:\n{out}')
    return json.loads(lines[-1].removeprefix(RESULT_PREFIX))


def _home_ids() -> set[str]:
    visits = pd.read_csv(VISITS_CSV, dtype=str, keep_default_na=False)
    return set(visits.loc[visits['semantic_type'].isin(timeline.HOME_TYPES), 'place_id'])


def lookup(place_ids: list[str]) -> int:
    """Places API で引いてキャッシュに足す。失敗したら引けた分を残して止め、引けなかった件数を返す"""
    api_key = require_env('GOOGLE_MAPS_API_KEY')
    rows = []
    try:
        for n, pid in enumerate(place_ids, 1):
            now = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec='seconds')
            try:
                place = places_client.get_place(pid, api_key)
                rows.append({'place_id': pid, **place, 'status': 'ok', 'resolved_at': now})
            except places_client.PlaceNotFound:
                rows.append({'place_id': pid, 'display_name': '', 'primary_type': '',
                             'status': 'not_found', 'resolved_at': now})
            if n % 100 == 0:
                log.info('Places API %d/%d', n, len(place_ids))
    except Exception as exc:  # 認証・クォータ・5xx。引けた分は残す
        log.error('Places API が %d 件目で失敗した: %r', len(rows) + 1, exc)
    finally:
        place_names.append_cache(rows)
    return len(place_ids) - len(rows)


def cmd_name_places(args) -> int:
    ids = rails_runner(RAILS_DIR / 'unknown_places.rb')
    overrides = place_names.read_overrides(OVERRIDES_YAML)
    places = timeline.read_places(PLACES_CSV)
    home_ids = _home_ids()

    resolved, misses = place_names.resolve(ids, overrides, home_ids, places, place_names.read_cache())
    log.info('Unknown の Place（Google の place ID）%d 件: 手元で名前が付く %d 件 / Places API で引く %d 件',
             len(ids), len(resolved), len(misses))
    if args.dry_run:
        return 0

    failed = lookup(misses) if misses else 0
    resolved, _ = place_names.resolve(ids, overrides, home_ids, places, place_names.read_cache())

    with tempfile.TemporaryDirectory() as tmp:
        names_json = Path(tmp) / 'place_names.json'
        names_json.write_text(json.dumps(resolved, ensure_ascii=False), encoding='utf-8')
        result = rails_runner(RAILS_DIR / 'apply_place_names.rb', names_json)
    log.info('改名 %(renamed)d 件 / Visit の name=Unknown を空に %(visit_names_cleared)d 件 / '
             '残る Unknown: Place %(places_unknown)d 件・Visit %(visits_unknown)d / %(visits_total)d 件', result)
    return 1 if failed else 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    parser = argparse.ArgumentParser(description='Dawarich CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_names = subparsers.add_parser('name-places', help='Unknown の Place に名前を付ける')
    p_names.add_argument('--dry-run', action='store_true', help='件数だけ出して DB も API も触らない')
    p_names.set_defaults(func=cmd_name_places)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
