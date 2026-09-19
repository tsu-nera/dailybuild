#!/usr/bin/env python
# coding: utf-8
"""Hevy（筋トレ記録）

Hevy 無料版に API は無く、アプリからの手動 export が唯一の経路。export 先の
Google Drive フォルダから最新の CSV を取って `data/hevy/` を置き換える。

Usage:
    python scripts/hevy.py fetch           # Drive から最新の export を取得する
    python scripts/hevy.py fetch --force   # 行数が減っていても書き込む

週1回（土日）の export を前提にしている。export を忘れると古い CSV が黙って
残り「今週トレーニング0回」に見えるため、Drive 側のファイルが古ければ警告する。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import logging

import pandas as pd
import yaml

from lib import hevy_csv
from lib.clients import gdrive_client
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).parent.parent
PERSONAL_YAML = BASE_DIR / 'config' / 'personal.yaml'
WORKOUTS_CSV = BASE_DIR / 'data' / 'hevy' / 'workouts.csv'
MEASUREMENTS_CSV = BASE_DIR / 'data' / 'hevy' / 'measurements.csv'

# export を忘れたまま回した週を検出する閾値。週1運用なので7日ちょうどは正常
STALE_DAYS = 8

logger = logging.getLogger('hevy')


def _load_folder_id():
    with PERSONAL_YAML.open() as f:
        personal = yaml.safe_load(f) or {}
    folder_id = (personal.get('gdrive') or {}).get('hevy_folder_id')
    if not folder_id:
        raise SystemExit(f'gdrive.hevy_folder_id が無い: {PERSONAL_YAML}')
    return folder_id


def _warn_if_stale(meta):
    created = dt.datetime.fromisoformat(meta['createdTime'].replace('Z', '+00:00'))
    age_days = (dt.datetime.now(dt.timezone.utc) - created).days
    if age_days >= STALE_DAYS:
        logger.warning(
            '%s は %d 日前の export（%s）。アプリから export し直さないと '
            '最近のセッションが入らない',
            meta['name'], age_days, created.astimezone().strftime('%Y-%m-%d'),
        )
    return age_days


def _existing_rows(path):
    """既存 CSV の行数。無ければ 0（初回取得）

    行数の比較だけなので日付の解釈はしない（measurements.csv は保存時に
    ISO へ直しており、Hevy の日時フォーマットでは読めない）。
    """
    if not path.exists():
        return 0
    try:
        return len(pd.read_csv(path))
    except Exception as exc:  # 壊れた既存ファイルでガードを止めない
        logger.warning('既存の %s を読めなかったので行数ガードを外す: %s', path.name, exc)
        return 0


def _fetch_one(service, folder_id, drive_name, dest, parse, write, force):
    """Drive の drive_name を取得して dest を置き換える。書いたら True"""
    meta = gdrive_client.latest_file(service, folder_id, drive_name)
    _warn_if_stale(meta)

    content = gdrive_client.download_file(service, meta['id'])

    # 先にパースして落とす。壊れた export で正本を潰さない
    tmp = dest.parent / f'.{dest.name}.download'
    ensure_dir(dest.parent)
    tmp.write_bytes(content)
    try:
        new_df = parse(tmp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    before = _existing_rows(dest)
    after = len(new_df)
    if after < before and not force:
        tmp.unlink(missing_ok=True)
        logger.error(
            '%s の行数が減る（%d → %d）ので書き込まない。'
            'Hevy 側で記録を消したのなら --force を付けて実行する',
            dest.name, before, after,
        )
        return False

    write(new_df, tmp, dest)
    tmp.unlink(missing_ok=True)
    logger.info('%s を更新した（%d → %d 行、export %s）',
                dest.name, before, after, meta['createdTime'][:10])
    return True


def _write_verbatim(df, tmp, dest):
    """export の中身をそのまま正本にする（読み取り時にパースする）"""
    dest.write_bytes(tmp.read_bytes())


def _write_measurements(df, tmp, dest):
    """measurement は日付を ISO に直して保存する（空欄は空欄のまま）"""
    df.to_csv(dest, index=False)


def fetch(force=False):
    folder_id = _load_folder_id()
    require_private_path(WORKOUTS_CSV)
    require_private_path(MEASUREMENTS_CSV)

    service = gdrive_client.create_reader_service()

    targets = [
        ('workout_data.csv', WORKOUTS_CSV,
         hevy_csv.parse_hevy_csv, _write_verbatim),
        ('measurement_data.csv', MEASUREMENTS_CSV,
         hevy_csv.parse_hevy_measurements, _write_measurements),
    ]

    ok = True
    for drive_name, dest, parse, write in targets:
        ok &= _fetch_one(service, folder_id, drive_name, dest, parse, write, force)
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser(description='Hevy の export を Drive から取得する')
    sub = parser.add_subparsers(dest='command', required=True)

    p_fetch = sub.add_parser('fetch', help='Drive から最新の export を取得する')
    p_fetch.add_argument('--force', action='store_true',
                         help='行数が減っていても書き込む')

    args = parser.parse_args()

    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format='%(levelname)s: %(message)s')

    if args.command == 'fetch':
        return fetch(force=args.force)
    return 1


if __name__ == '__main__':
    sys.exit(main())
