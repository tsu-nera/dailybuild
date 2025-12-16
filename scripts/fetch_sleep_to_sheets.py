#!/usr/bin/env python
# coding: utf-8
"""
Fitbit睡眠データ → Google Spreadsheet + CSV保存
"""

import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import datetime as dt

import fitbit
import pandas as pd

from lib.clients import fitbit_api, gsheets_client
from lib.utils import csv_utils

BASE_DIR = Path(__file__).parent.parent
# 開発用（ローカル実行時）
CREDS_FILE = BASE_DIR / 'config/fitbit_creds_dev.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token_dev.json'
GCP_CREDS_FILE = BASE_DIR / 'config/gcp_service_account.json'
OUT_FILE = BASE_DIR / 'data/fitbit/sleep.csv'
OUT_LEVELS_FILE = BASE_DIR / 'data/fitbit/sleep_levels.csv'


def get_fitbit_credentials():
    """Fitbit認証情報を取得（環境変数優先）"""
    if os.environ.get('FITBIT_CREDS') and os.environ.get('FITBIT_TOKEN'):
        creds = json.loads(os.environ['FITBIT_CREDS'])
        token = json.loads(os.environ['FITBIT_TOKEN'])
        return creds, token, None

    with open(CREDS_FILE) as f:
        creds = json.load(f)
    with open(TOKEN_FILE) as f:
        token = json.load(f)
    return creds, token, TOKEN_FILE


def create_fitbit_client():
    """
    トークン更新時のコールバック付きFitbitクライアント作成

    Returns:
        (client, updated_token_holder): クライアントと更新トークン格納用dict
    """
    creds, token_data, token_file = get_fitbit_credentials()

    updated_token = {'value': None}

    def update_token(token):
        updated_token['value'] = token
        if token_file:
            fitbit_api.save_token(str(token_file), token)

    client = fitbit.Fitbit(
        creds['client_id'],
        creds['client_secret'],
        oauth2=True,
        access_token=token_data['access_token'],
        refresh_token=token_data['refresh_token'],
        refresh_cb=update_token
    )

    return client, updated_token


def save_to_csv(df, response):
    """CSVに保存（既存データとマージ）"""
    df_merged = csv_utils.merge_csv(df, OUT_FILE, 'dateOfSleep')
    df_merged.to_csv(OUT_FILE)
    print(f"CSVに保存: {OUT_FILE} ({len(df_merged)}件)")

    levels_data = fitbit_api.parse_sleep_levels(response)
    if levels_data:
        df_levels = pd.DataFrame(levels_data)
        df_levels['dateTime'] = pd.to_datetime(df_levels['dateTime'])
        df_levels.sort_values(['dateOfSleep', 'dateTime'], inplace=True)
        df_levels = csv_utils.merge_csv_by_columns(
            df_levels, OUT_LEVELS_FILE,
            key_columns=['dateOfSleep', 'dateTime'],
            parse_dates=['dateTime'],
            sort_by=['dateOfSleep', 'dateTime']
        )
        df_levels.to_csv(OUT_LEVELS_FILE, index=False)
        print(f"詳細データを保存: {OUT_LEVELS_FILE} ({len(df_levels)}件)")

    return df_merged


def save_to_sheets(df, response, spreadsheet_id):
    """Google Spreadsheetに保存"""
    gc = gsheets_client.create_client(
        creds_file=str(GCP_CREDS_FILE) if GCP_CREDS_FILE.exists() else None
    )
    spreadsheet = gc.open_by_key(spreadsheet_id)

    # summaryシート: 全データを上書き更新
    summary_ws = gsheets_client.get_or_create_worksheet(spreadsheet, 'summary')
    df_for_sheets = df.reset_index()
    df_for_sheets['dateOfSleep'] = df_for_sheets['dateOfSleep'].astype(str)
    # NaN/NaTをNoneに変換
    df_for_sheets = df_for_sheets.where(pd.notnull(df_for_sheets), None)
    gsheets_client.update_dataframe(summary_ws, df_for_sheets)
    print(f"summaryシートを更新: {len(df_for_sheets)}件")

    # raw_dataシート: 生JSONを追記
    raw_ws = gsheets_client.get_or_create_worksheet(spreadsheet, 'raw_data')
    today_str = dt.date.today().isoformat()
    raw_json = json.dumps(response, ensure_ascii=False)
    gsheets_client.append_row(raw_ws, [today_str, 'fitbit_sleep', raw_json])
    print(f"raw_dataシートに追記: {today_str}")


def output_github_actions_token(updated_token):
    """GitHub Actions用にトークンを出力"""
    if updated_token['value'] and os.environ.get('GITHUB_OUTPUT'):
        token_json = json.dumps(updated_token['value'])
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"fitbit_token={token_json}\n")
        print("Fitbitトークンが更新されました（GitHub Actionsに出力）")


def main():
    parser = argparse.ArgumentParser(description='Fitbit睡眠データ→Google Sheets')
    parser.add_argument('--days', type=int, default=14, help='取得日数')
    parser.add_argument('--csv-only', action='store_true', help='CSVのみ保存（Sheets書き込みスキップ）')
    args = parser.parse_args()

    spreadsheet_id = os.environ.get('SPREADSHEET_ID')
    if not args.csv_only and not spreadsheet_id:
        print("警告: SPREADSHEET_IDが未設定のためCSVのみ保存します")
        args.csv_only = True

    print("Fitbitクライアントを作成中...")
    client, updated_token = create_fitbit_client()

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=args.days)

    print(f"睡眠データを取得中... ({start_date} ~ {end_date})")
    response = fitbit_api.get_sleep_log_by_date_range(client, start_date, end_date)

    sleep_data = fitbit_api.parse_sleep(response)
    if not sleep_data:
        print("データがありません")
        return

    df = pd.DataFrame(sleep_data)
    df['dateOfSleep'] = pd.to_datetime(df['dateOfSleep'])
    df.set_index('dateOfSleep', inplace=True)
    df.sort_index(inplace=True)

    df_merged = save_to_csv(df, response)

    if not args.csv_only:
        print("Google Sheetsに書き込み中...")
        save_to_sheets(df_merged, response, spreadsheet_id)

    output_github_actions_token(updated_token)

    print("完了")


if __name__ == '__main__':
    main()
