#!/usr/bin/env python
# coding: utf-8
"""Google マップ Timeline（場所ごとの訪問）

Timeline は端末内保存で API が無く、アプリからの手動 export（`タイムライン.json`）が
唯一の経路。export 先の Google Drive フォルダから最新の JSON を取り、visit だけを
`data/timeline/visits.csv` に取り込む。

Usage:
    python scripts/timeline.py fetch    # Drive から最新の export を取り込む
    python scripts/timeline.py names [--limit N]
                                        # 訪問日数の多い未解決の place ID の名前を Places API で引く
    python scripts/timeline.py show --start 2026-10-01 --end 2026-10-07
                                        # 期間の場所別 訪問日数・滞在時間を stdout へ

daily-fetch.sh から日次で fetch / names する運用。export は月1回ほどなので、Drive 側の
modifiedTime が前回取り込んだものと同じなら何もしない（数十MBを毎日落とさない）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import json
import logging

import pandas as pd
import yaml

from lib import timeline
from lib.clients import gdrive_client, places_client
from lib.utils import csv_utils
from lib.utils.env import get_env
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
PERSONAL_YAML = BASE_DIR / 'config' / 'personal.yaml'
VISITS_CSV = BASE_DIR / 'data' / 'timeline' / 'visits.csv'
PLACES_CSV = BASE_DIR / 'data' / 'timeline' / 'places.csv'
STATE_JSON = BASE_DIR / 'data' / 'timeline' / 'fetch_state.json'

DRIVE_NAME = 'タイムライン.json'

# export は月1回ほどの手動運用。1ヶ月を少し超えたら忘れていると見なす
STALE_DAYS = 40

logger = logging.getLogger('timeline')


def _load_folder_id():
    with PERSONAL_YAML.open() as f:
        personal = yaml.safe_load(f) or {}
    folder_id = (personal.get('gdrive') or {}).get('timeline_folder_id')
    if not folder_id:
        raise SystemExit(f'gdrive.timeline_folder_id が無い: {PERSONAL_YAML}')
    return folder_id


def _warn_if_stale(meta):
    modified = dt.datetime.fromisoformat(meta['modifiedTime'].replace('Z', '+00:00'))
    age_days = (dt.datetime.now(dt.timezone.utc) - modified).days
    if age_days >= STALE_DAYS:
        logger.warning(
            '%s は %d 日前の export（%s）。端末から export し直さないと '
            '最近の訪問が入らない',
            meta['name'], age_days, modified.astimezone().strftime('%Y-%m-%d'),
        )
    return age_days


def _already_imported(meta):
    if not STATE_JSON.exists():
        return False
    try:
        state = json.loads(STATE_JSON.read_text())
    except ValueError:
        return False  # 壊れた状態ファイルは無かったことにして取り直す
    return (state.get('id') == meta['id']
            and state.get('modifiedTime') == meta['modifiedTime'])


def fetch(service=None):
    folder_id = _load_folder_id()
    require_private_path(VISITS_CSV)
    require_private_path(STATE_JSON)

    if service is None:
        service = gdrive_client.create_reader_service()

    meta = gdrive_client.latest_file(service, folder_id, DRIVE_NAME)
    _warn_if_stale(meta)

    if _already_imported(meta):
        logger.info('前回取り込んだ export（%s）から変わっていないので何もしない',
                    meta['modifiedTime'])
        return 0

    content = gdrive_client.download_file(service, meta['id'])

    # パースに失敗したら例外のまま落とす。CSV にもステートにも触れない
    new_df = timeline.parse_export(content)
    if new_df.empty:
        raise ValueError('visit が1件も無い。export が空か形が違うので書き込まない')

    days = new_df['start_time'].astype(str).str[:10]
    ensure_dir(VISITS_CSV.parent)
    merged = csv_utils.replace_csv_period(
        new_df, VISITS_CSV, 'start_time', days.min(), days.max(),
        sort_by=['start_time'], label='timeline')
    merged.to_csv(VISITS_CSV, index=False)

    # CSV を書き終えてから記録する（途中で落ちたら次回また取り込む）
    STATE_JSON.write_text(json.dumps(
        {'id': meta['id'], 'modifiedTime': meta['modifiedTime']}, ensure_ascii=False))
    logger.info('%s を更新した（export %d 件 → 合計 %d 行、%s 〜 %s）',
                VISITS_CSV.name, len(new_df), len(merged), days.min(), days.max())
    return 0


def _api_key():
    return get_env('GOOGLE_MAPS_API_KEY')


def names(limit=100, session=None):
    """訪問日数の多い未解決の place ID の名前を引き places.csv に足す

    キーが無ければ warning を出して 0 で終わる（日次を失敗させない）。
    API エラーでは、それまでに引いた分を書いてから 1 を返す。
    """
    api_key = _api_key()
    if not api_key:
        logger.warning('GOOGLE_MAPS_API_KEY が無いので場所の名前を引かない')
        return 0

    require_private_path(PLACES_CSV)
    require_private_path(VISITS_CSV)
    if not VISITS_CSV.exists():
        logger.error('%s が無い。先に fetch を実行する', VISITS_CSV)
        return 1

    visits = pd.read_csv(VISITS_CSV, dtype={'place_id': str, 'semantic_type': str})
    targets = timeline.places_to_resolve(
        visits, timeline.read_places(PLACES_CSV), limit)

    kwargs = {} if session is None else {'session': session}
    rows = []
    for place_id in targets:
        resolved_at = dt.datetime.now(dt.timezone.utc).astimezone().isoformat(
            timespec='seconds')
        try:
            place = places_client.get_place(place_id, api_key, **kwargs)
            row = {'place_id': place_id, **place, 'status': 'ok'}
        except places_client.PlaceNotFound:
            row = {'place_id': place_id, 'display_name': '', 'primary_type': '',
                   'status': 'not_found'}
        except Exception as exc:  # 認証・クォータ・5xx・通信断。引けた分は残して止める
            timeline.append_places(PLACES_CSV, rows)
            logger.error('%s の取得に失敗した（%d 件は保存済み）: %r',
                         place_id, len(rows), exc)
            return 1
        rows.append({**row, 'resolved_at': resolved_at})

    timeline.append_places(PLACES_CSV, rows)
    logger.info('%s に %d 件を足した（対象 %d 件）', PLACES_CSV.name, len(rows), len(targets))
    return 0


def _hours(minutes):
    return f'{minutes / 60:.1f}'


def show(start, end):
    """期間の場所別 訪問日数・滞在時間と、前期間との入れ替わりを markdown で stdout へ出す

    API は叩かず data/timeline/ の visits.csv と places.csv（あれば）だけを読む。判断語は書かない（数値のみ）。
    """
    if not VISITS_CSV.exists():
        logger.error('%s が無い。先に fetch を実行する', VISITS_CSV)
        return 1

    visits = pd.read_csv(VISITS_CSV, dtype={'place_id': str, 'semantic_type': str})
    places = timeline.read_places(PLACES_CSV)
    result = timeline.summarize(visits, start, end, places=places)
    labels = result['labels']

    print(f'# 場所別の訪問（{start} 〜 {end}）\n')
    print(f'前期間: {result["prev_start"]} 〜 {result["prev_end"]}\n')

    table = result['current']
    if table.empty:
        print('該当期間に訪問が無い\n')
    else:
        out = pd.DataFrame({
            '場所': table['place_id'].map(labels),
            '訪問日数': table['visit_days'],
            '滞在時間(h)': table['duration_min'].map(_hours),
            '初回': table['first_date'],
            '最終': table['last_date'],
        })
        print(out.to_markdown(index=False))
        print()

    for title, ids in (('上位に入った', result['entered']),
                       ('上位から外れた', result['dropped'])):
        print(f'## {title}\n')
        if ids:
            for pid in ids:
                print(f'- {labels.get(pid, pid)}')
        else:
            print('なし')
        print()

    return 0


def _date(text):
    return dt.date.fromisoformat(text)


def main():
    parser = argparse.ArgumentParser(description='Timeline の export を Drive から取り込む')
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('fetch', help='Drive から最新の export を取り込む')

    p_names = sub.add_parser('names', help='place ID の名前を Places API で引き places.csv へ足す')
    p_names.add_argument('--limit', type=int, default=100, help='1回に引く上限（既定 100）')

    p_show = sub.add_parser('show', help='期間の場所別サマリを markdown で stdout へ出す')
    p_show.add_argument('--start', type=_date, required=True, help='開始日 YYYY-MM-DD')
    p_show.add_argument('--end', type=_date, required=True, help='終了日 YYYY-MM-DD')

    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format='%(levelname)s: %(message)s')

    if args.command == 'fetch':
        return fetch()
    if args.command == 'names':
        return names(args.limit)
    if args.command == 'show':
        return show(args.start, args.end)
    return 1


if __name__ == '__main__':
    sys.exit(main())
