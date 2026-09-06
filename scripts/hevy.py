#!/usr/bin/env python
# coding: utf-8
"""
Hevy 筋トレ記録（Google Drive 経由の CSV export）

Hevy アプリの Export Workouts で Drive の hevy フォルダへ保存された
CSV を取得し、data/hevy/workouts.csv を置換する。取得経路の詳細・
行数減少ガードの理由は GitHub issue #153 を参照。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import yaml
from lib.clients import gdrive_client
from lib.hevy import store

BASE_DIR = Path(__file__).parent.parent
PERSONAL_YAML = BASE_DIR / 'config/personal.yaml'
DRIVE_FILE_NAME = 'workout_data.csv'


def load_hevy_folder_id() -> str:
    with open(PERSONAL_YAML) as f:
        conf = yaml.safe_load(f)
    folder_id = conf.get('gdrive', {}).get('hevy_folder_id')
    if not folder_id:
        raise ValueError(
            f'gdrive.hevy_folder_id が未設定: {PERSONAL_YAML}')
    return folder_id


def cmd_fetch(args):
    folder_id = load_hevy_folder_id()

    service = gdrive_client.create_service()

    print(f"取得中: {DRIVE_FILE_NAME} (folder={folder_id})", file=sys.stderr)
    csv_bytes = gdrive_client.download_latest(service, folder_id, DRIVE_FILE_NAME)
    print(f"ダウンロード完了: {len(csv_bytes)} bytes", file=sys.stderr)

    try:
        existing_rows, new_rows = store.save_workouts(csv_bytes, force=args.force)
    except store.WorkoutsShrankError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"保存完了: {store.CSV_FILE} (既存 {existing_rows}行 -> 新規 {new_rows}行)")


def main():
    parser = argparse.ArgumentParser(description='Hevy 筋トレ記録（Google Drive経由）')
    sub = parser.add_subparsers(dest='command', required=True)

    p_fetch = sub.add_parser('fetch', help='Drive から最新の export を取得して CSV を置換する')
    p_fetch.add_argument('--force', action='store_true',
                         help='行数が減っていても上書きする')
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
