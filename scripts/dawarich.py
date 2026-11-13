#!/usr/bin/env python
# coding: utf-8
"""
Dawarich（位置のライフログ、#290）の CLI（import-routes / export-app-points / name-places）

Dawarich の DB は派生物で、正本は private の data/ にある（TCX・GPSLogger の GPX・Swarm・Timeline の書き出し）。
Dawarich をやめても data/ だけで作り直せることを保つ。

import-routes: 位置のファイル（ROUTE_GLOBS）のうち Dawarich に未投入のものを HTTP API で上げる。
  どのホストからでも流せる（日次は vaio）。宛先は .env の DAWARICH_URL / DAWARICH_API_KEY で、
  未設定なら warning だけで 0 終了する。二重投入の判定は import 名（＝ファイル名）。
  GPSLogger の GPX は飛んだ network / fused の点を除いて（lib.gpslogger.drop_jumps）同じファイル名で上げる。
  data/ の GPX は生のまま残す。
  上げた後、精度の高い軌跡（PRECISE_SUFFIXES の import）の時間帯にある他の点（GPSLogger・スマホのアプリ・
  Timeline）を mouse の Dawarich から消す。Dawarich は出どころに優先順位を持たず、1秒間隔の軌跡に数km 飛ぶ点が
  混ざって線が崩れるため。消える点の正本は data/ と Drive にあるので、Dawarich を作り直せば戻る。
  GPX は1日分を覆うので基準にしない（基準にすると1日中の他の点が消える）。
export-app-points: スマホの Dawarich アプリが送った点は Dawarich の DB にしか無いので、APP_POINTS へ写す。
  既存の行は消さない。公式アプリは記録係にしない方針（GPSLogger に移行）なので日次には入れず、
  アプリを止めるときに手で流す。アプリが送っている先のホストで実行する（rails runner）。
name-places: Dawarich の DB は取り込み直すたびに作り直されるので、手で直さずにこれを流し直す。
  Dawarich が動いているホストの dailybuild で実行する（docker compose で app コンテナに入る）。

Usage:
    python scripts/dawarich.py import-routes --dry-run   # 上げるファイルだけ出す
    python scripts/dawarich.py import-routes             # 未投入の軌跡を上げる
    python scripts/dawarich.py export-app-points         # アプリの点を data/dawarich/app_points.csv へ写す
    python scripts/dawarich.py name-places --dry-run   # 何件に名前が付き、何件 Places API を引くかだけ出す
    python scripts/dawarich.py name-places             # Unknown の Place を改名して名前を固定する
    python scripts/dawarich.py name-places --max-api 50  # Places API を呼ぶ回数の上限（既定 MAX_API_CALLS）

名前の決め方は src/lib/dawarich/place_names.py。手で決める名前は config/private/dawarich_place_names.yaml
（`<place ID>: {name: ..., note: ...}`）。Places API のキーは .env の GOOGLE_MAPS_API_KEY。

GCP 側で Place Details に1日200回の上限を掛けてあり、vaio の `timeline.py names` と同じ枠を使う。
引くのは Visit の多い場所から順で、上限に当たったら引けた分だけ改名して非ゼロで終わる。
翌日また流せば続きから引く（引いた結果は ~/.cache/dailybuild/ に残る）。
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

from lib import gpslogger, timeline
from lib.clients import places_client
from lib.clients.dawarich_client import DawarichClient, not_imported, overlapping_others, precise_imports
from lib.dawarich import app_points, place_names
from lib.utils.env import get_env, require_env
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
COMPOSE_DIR = BASE_DIR / 'scripts' / 'ops' / 'dawarich'
RAILS_DIR = COMPOSE_DIR / 'rails'
OVERRIDES_YAML = BASE_DIR / 'config' / 'private' / 'dawarich_place_names.yaml'
PLACES_CSV = BASE_DIR / 'data' / 'timeline' / 'places.csv'
VISITS_CSV = BASE_DIR / 'data' / 'timeline' / 'visits.csv'
RESULT_PREFIX = 'RESULT_JSON:'
# Dawarich が読める軌跡ファイル（Tcx::Importer / Fit::Importer）。取得元を足したらここに1行足す
ROUTE_GLOBS = [
    'data/googlehealth/tcx/*.tcx',  # Fitbit の GPS 付き運動（exercise_route.py fetch）
    'data/gpslogger/*.gpx',         # GPSLogger の1日1ファイル、前日まで（gpslogger.py fetch）
    'data/xoss/fit/*.fit',          # XOSS サイコン（xoss.py fetch / import）
]
# 時間帯の基準にする import 名の拡張子（Fitbit の TCX・XOSS サイコンの FIT）。
# TCX と FIT は同時に記録しないので、両者の間に優先順位は無い
PRECISE_SUFFIXES = ('.tcx', '.fit')
# 基準の時間帯にあっても消さない import の source。Swarm はチェックインという出来事の点で、位置の精度の問題ではない
KEEP_SOURCES = {'swarm'}
APP_POINTS = BASE_DIR / 'data' / 'dawarich' / 'app_points.csv'
# Place Details の日次上限 200 のうち、vaio の timeline.py names（最大100）のぶんを残す
MAX_API_CALLS = 100

log = logging.getLogger('dawarich')


def _compose(*args: str, capture: bool = False) -> str:
    # cp は進み具合を stderr に出す。失敗は check=True の例外で分かる
    result = subprocess.run(
        ['docker', 'compose', '--project-directory', str(COMPOSE_DIR), *args],
        check=True, text=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=None if capture else subprocess.DEVNULL)
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

    targets = misses[:args.max_api]
    failed = lookup(targets) if targets else 0
    resolved, _ = place_names.resolve(ids, overrides, home_ids, places, place_names.read_cache())

    with tempfile.TemporaryDirectory() as tmp:
        names_json = Path(tmp) / 'place_names.json'
        names_json.write_text(json.dumps(resolved, ensure_ascii=False), encoding='utf-8')
        result = rails_runner(RAILS_DIR / 'apply_place_names.rb', names_json)
    log.info('改名 %(renamed)d 件 / Visit の name=Unknown を空に %(visit_names_cleared)d 件 / '
             '残る Unknown: Place %(places_unknown)d 件・Visit %(visits_unknown)d / %(visits_total)d 件', result)
    left = len(misses) - len(targets) + failed
    if left:
        log.warning('Places API で引けていない place ID が %d 件残っている。翌日また流す', left)
    return 1 if failed else 0


def cmd_import_routes(args) -> int:
    files = [p for pattern in ROUTE_GLOBS for p in BASE_DIR.glob(pattern)]
    url, api_key = get_env('DAWARICH_URL'), get_env('DAWARICH_API_KEY')
    if not url or not api_key:
        log.warning('DAWARICH_URL / DAWARICH_API_KEY が .env に無いので上げない（軌跡ファイル %d 件）', len(files))
        return 0
    client = DawarichClient(url, api_key)
    targets = not_imported(files, client.import_names())
    log.info('軌跡ファイル %d 件のうち Dawarich に未投入 %d 件', len(files), len(targets))
    failed = 0
    for p in targets:
        if args.dry_run:
            log.info('  %s', p.name)
            continue
        try:
            result = upload_route(client, p)
        except Exception as exc:  # 1件の失敗で残りを止めない。翌日また上げる
            log.error('%s: %r', p.name, exc)
            failed += 1
            continue
        log.info('%s -> import %s (%s)', p.name, result.get('id'), result.get('status'))
    try:
        remove_overlaps(client, args.dry_run)
    except Exception as exc:
        log.error('軌跡の時間帯の点を消せなかった: %r', exc)
        failed += 1
    return 1 if failed else 0


def upload_route(client: DawarichClient, path: Path) -> dict:
    """GPX は飛びを除いた写しを同じファイル名で上げる（import 名を変えないため）。正本は書き換えない"""
    if path.suffix.lower() != '.gpx':
        return client.upload(path)
    filtered, dropped = gpslogger.drop_jumps(path.read_bytes())
    log.info('%s: 飛んだ点 %d 件を除いて上げる', path.name, dropped)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / path.name
        tmp_path.write_bytes(filtered)
        return client.upload(tmp_path)


def remove_overlaps(client: DawarichClient, dry_run: bool) -> None:
    imports = client.imports()
    bases = precise_imports(imports, PRECISE_SUFFIXES)
    base_points = {i['id']: client.points(import_id=i['id'], slim=True) for i in bases}
    keep_ids = {pt['id'] for pts in base_points.values() for pt in pts}
    for imp in imports:
        if imp['source'] in KEEP_SOURCES:
            keep_ids |= {pt['id'] for pt in client.points(import_id=imp['id'], slim=True)}
    removed = set()
    for imp in bases:
        pts = base_points[imp['id']]
        if not pts:
            continue
        window = client.points(start_at=min(pt['timestamp'] for pt in pts),
                               end_at=max(pt['timestamp'] for pt in pts), slim=True)
        removed |= {pt['id'] for pt in overlapping_others(window, keep_ids)}
    log.info('軌跡 %d 本の時間帯にある他の点: %d 件', len(bases), len(removed))
    if removed and not dry_run:
        log.info('消した点: %d 件', client.delete_points(sorted(removed)))


def cmd_export_app_points(args) -> int:
    rows = rails_runner(RAILS_DIR / 'app_points.rb')
    path = require_private_path(APP_POINTS)
    ensure_dir(path.parent)
    before = len(pd.read_csv(path, dtype=str)) if path.exists() else 0
    merged = app_points.merge(rows, path)
    merged.to_csv(path, index=False)
    log.info('アプリの点: Dawarich %d 件 / CSV %d -> %d 件（%s）', len(rows), before, len(merged), path)
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)
    parser = argparse.ArgumentParser(description='Dawarich CLI')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_routes = subparsers.add_parser('import-routes', help='未投入の運動の軌跡を上げる')
    p_routes.add_argument('--dry-run', action='store_true', help='上げるファイルだけ出す')
    p_routes.set_defaults(func=cmd_import_routes)

    p_app = subparsers.add_parser('export-app-points', help='アプリの点を private へ写す')
    p_app.set_defaults(func=cmd_export_app_points)

    p_names = subparsers.add_parser('name-places', help='Unknown の Place に名前を付ける')
    p_names.add_argument('--dry-run', action='store_true', help='件数だけ出して DB も API も触らない')
    p_names.add_argument('--max-api', type=int, default=MAX_API_CALLS, help='Places API を呼ぶ回数の上限')
    p_names.set_defaults(func=cmd_name_places)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == '__main__':
    main()
