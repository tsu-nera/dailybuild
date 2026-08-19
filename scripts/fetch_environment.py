#!/usr/bin/env python
# coding: utf-8
"""
室内環境データ（CO2/温度/湿度）取得スクリプト

LSENLTY WiFi CO2モニター（Tuya系デバイス）から Tuya Cloud API 経由でログを取得し、
JSTに変換して data/environment.csv に蓄積する。

Tuya Cloud API は最大1週間分しか遡れないため、日次実行で差分を蓄積する前提。

Usage:
    python scripts/fetch_environment.py --days 7
    python scripts/fetch_environment.py --raw
    python scripts/fetch_environment.py --start-date 2026-08-12 --end-date 2026-08-19
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt
import json

from lib.clients import tuya_client
from lib.clients.tuya_client import TuyaCloudError
from lib.utils import csv_utils

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config' / 'tuya_creds.json'
CSV_FILE = BASE_DIR / 'data' / 'environment.csv'

REQUIRED_KEYS = ['api_region', 'api_key', 'api_secret', 'device_id']


def load_creds() -> dict:
    if not CREDS_FILE.exists():
        print(f"⚠️ 認証情報ファイルが見つかりません: {CREDS_FILE}")
        print("以下の手順で作成してください:")
        print(f"  1. config/tuya_creds.json.sample を {CREDS_FILE} にコピーして値を埋める")
        print("  2. Tuya IoT Platform (https://iot.tuya.com/) で Cloud Project を作成"
              "（Data CenterはWestern America）")
        print("  3. Service API に以下をサブスクライブしてAuthorize: Industry Basic Service / "
              "Smart Home Basic Service / Device Status Notification / Authorization / "
              "IoT Core / Smart Home Scene Linkage / IoT Data Analytics")
        print("  4. Devices → Link App Account でSmart LifeアカウントをQRスキャン連携")
        print("  5. `uv run python -m tinytuya wizard` を実行して device_id / local_key を取得")
        sys.exit(1)

    with open(CREDS_FILE, 'r') as f:
        creds = json.load(f)

    missing = [k for k in REQUIRED_KEYS if not creds.get(k)]
    if missing:
        print(f"⚠️ 認証情報に不足しているキーがあります: {missing}")
        print(f"  {CREDS_FILE} を確認してください（必須キー: {REQUIRED_KEYS}）")
        sys.exit(1)

    return creds


def resolve_period(args) -> tuple[dt.date, dt.date]:
    """引数から取得期間を決定"""
    end = dt.date.today()
    if args.start_date and args.end_date:
        return (dt.datetime.strptime(args.start_date, '%Y-%m-%d').date(),
                dt.datetime.strptime(args.end_date, '%Y-%m-%d').date())
    return end - dt.timedelta(days=args.days - 1), end


def main():
    parser = argparse.ArgumentParser(description='室内環境データ（CO2/温度/湿度）取得')
    parser.add_argument('--days', type=int, default=7, help='取得日数（今日から遡る）')
    parser.add_argument('--start-date', type=str, help='開始日（YYYY-MM-DD）')
    parser.add_argument('--end-date', type=str, help='終了日（YYYY-MM-DD）')
    parser.add_argument('--interval-min', type=int, default=5, help='リサンプル間隔（分）')
    parser.add_argument('--raw', action='store_true',
                         help='生ログのcode一覧を表示して終了（CSVは書かない）')
    args = parser.parse_args()

    creds = load_creds()

    start, end = resolve_period(args)
    print(f"室内環境データ取得: {start} ～ {end}")

    try:
        cloud = tuya_client.create_cloud(creds)
        logs = tuya_client.fetch_device_log(cloud, creds['device_id'], start, end)

        if args.raw:
            print(tuya_client.summarize_raw_logs(logs))
            if not logs:
                sys.exit(1)
            return 0

        if not logs:
            print(f"⚠️ 期間 {start}〜{end} のログが0件。"
                  "デバイスがオフラインか、取得が壊れている可能性がある")
            sys.exit(1)

        scales = tuya_client.resolve_scales(cloud, creds['device_id'])
        df_new = tuya_client.logs_to_dataframe(logs, scales=scales,
                                                interval_min=args.interval_min)

        if df_new.empty:
            print(f"⚠️ 期間 {start}〜{end} のログから有効なデータを抽出できなかった"
                  "（DP_CODE_MAPが実機のcodeと一致していない可能性がある。--raw で確認すること）")
            sys.exit(1)

        df_merged = csv_utils.merge_csv_by_columns(
            df_new, CSV_FILE, key_columns=['datetime'], sort_by=['datetime'],
        )

        CSV_FILE.parent.mkdir(parents=True, exist_ok=True)
        df_merged.to_csv(CSV_FILE, index=False)

        period_min = df_merged['datetime'].min()
        period_max = df_merged['datetime'].max()
        print(f"取得件数: {len(df_new)}行（リサンプル後）")
        print(f"保存完了: {CSV_FILE} (総行数 {len(df_merged)}行)")
        print(f"CSVの期間: {period_min} ～ {period_max}")
        return 0

    except TuyaCloudError as e:
        print(f"⚠️ Tuya Cloud APIエラー: {e}")
        print("Tuya IoT Platform の Trial アカウントの有効期限切れの可能性がある。"
              "管理画面から延長申請を確認すること。")
        sys.exit(1)


if __name__ == '__main__':
    sys.exit(main())
