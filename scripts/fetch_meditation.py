#!/usr/bin/env python
# coding: utf-8
"""
Fitbit瞑想アクティビティデータ取得 → Google Spreadsheet + CSV保存

Usage:
    python scripts/fetch_meditation.py --days 14
    python scripts/fetch_meditation.py --days 14 --csv-only  # Sheets書き込みスキップ
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

from lib import fitbit_api, csv_utils, gsheets_client

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE = BASE_DIR / 'config/fitbit_creds.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token.json'
GCP_CREDS_FILE = BASE_DIR / 'config/gcloud_creds.json'
OUT_FILE = BASE_DIR / 'data/meditation_fitbit.csv'
SHEET_NAME = 'fitbit_meditation'


def get_fitbit_credentials():
    """Fitbit認証情報を取得（環境変数優先）"""
    fitbit_creds_env = os.environ.get('FITBIT_CREDS')
    fitbit_token_env = os.environ.get('FITBIT_TOKEN')

    if fitbit_creds_env and fitbit_token_env:
        print("環境変数から認証情報を取得")
        creds = json.loads(fitbit_creds_env)
        token = json.loads(fitbit_token_env)
        return creds, token, None

    print("ファイルから認証情報を取得")
    if not CREDS_FILE.exists():
        raise FileNotFoundError(
            f"認証情報が見つかりません。\n"
            f"環境変数 FITBIT_CREDS/FITBIT_TOKEN を設定するか、\n"
            f"{CREDS_FILE} を配置してください。"
        )

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


def logs_to_dataframe(meditation_logs):
    """瞑想ログをDataFrameに変換"""
    if not meditation_logs:
        return pd.DataFrame()

    records = []
    for log in meditation_logs:
        records.append({
            'logId': log['logId'],
            'timestamp': log['startTime'],
            'duration_min': log['durationMinutes'],
            'average_hr': log.get('averageHeartRate'),
            'calories': log.get('calories'),
        })

    df = pd.DataFrame(records)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # Museと同じ形式に統一: YYYY-MM-DD HH:MM:SS
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df.sort_values('timestamp', inplace=True)
    return df


def save_to_csv(df):
    """CSVに保存（既存データとマージ）"""
    if df.empty:
        print("瞑想データがありません")
        return None

    # 既存CSVとマージ（logIdで重複排除）
    df_merged = csv_utils.merge_csv_by_columns(
        df, OUT_FILE,
        key_columns=['logId'],
        parse_dates=['timestamp'],
        sort_by=['timestamp']
    )

    # 保存
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(OUT_FILE, index=False)
    print(f"CSVに保存: {OUT_FILE} ({len(df_merged)}件)")

    return df_merged


def clear_sheet(spreadsheet_id):
    """Google Spreadsheetのシートをクリア（ヘッダーも削除）"""
    gc = gsheets_client.create_client(
        creds_file=str(GCP_CREDS_FILE) if GCP_CREDS_FILE.exists() else None
    )
    spreadsheet = gc.open_by_key(spreadsheet_id)
    worksheet = gsheets_client.get_or_create_worksheet(spreadsheet, SHEET_NAME)

    # シート全体をクリア
    worksheet.clear()
    print(f"Spreadsheet({SHEET_NAME})をクリアしました")


def save_to_sheets(df, spreadsheet_id):
    """Google Spreadsheetに保存（既存データとマージ）"""
    if df.empty:
        print("Spreadsheetに保存するデータがありません")
        return

    gc = gsheets_client.create_client(
        creds_file=str(GCP_CREDS_FILE) if GCP_CREDS_FILE.exists() else None
    )
    spreadsheet = gc.open_by_key(spreadsheet_id)
    worksheet = gsheets_client.get_or_create_worksheet(spreadsheet, SHEET_NAME)

    # 既存データを取得（最初の行をヘッダーとして扱う）
    all_values = worksheet.get_all_values()

    # ヘッダーがあるかチェック
    has_header = len(all_values) > 0 and all_values[0] and all_values[0][0] == 'logId'

    if has_header:
        existing_log_ids = {str(row[0]) for row in all_values[1:] if row}
    else:
        existing_log_ids = set()

    # 新規データのみ抽出
    df_for_sheets = df.copy()
    df_for_sheets['logId'] = df_for_sheets['logId'].astype(str)
    df_for_sheets['timestamp'] = df_for_sheets['timestamp'].astype(str)
    # NaN値を空文字列に変換（JSON非対応のため）
    df_for_sheets = df_for_sheets.fillna('')
    df_for_sheets = df_for_sheets[~df_for_sheets['logId'].isin(existing_log_ids)]

    if df_for_sheets.empty:
        print(f"Spreadsheet({SHEET_NAME}): 新規データなし")
        return

    # ヘッダーがなければ追加
    if not has_header:
        worksheet.append_row(df_for_sheets.columns.tolist())

    # 新規データを追記
    rows = df_for_sheets.values.tolist()
    gsheets_client.append_rows(worksheet, rows)
    print(f"Spreadsheet({SHEET_NAME})に追記: {len(rows)}件")


def output_github_actions_token(updated_token):
    """GitHub Actions用にトークンを出力"""
    if updated_token['value'] and os.environ.get('GITHUB_OUTPUT'):
        token_json = json.dumps(updated_token['value'])
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f"fitbit_token={token_json}\n")
        print("Fitbitトークンが更新されました（GitHub Actionsに出力）")


def main():
    parser = argparse.ArgumentParser(description='Fitbit瞑想データ取得')
    parser.add_argument('--days', type=int, default=14, help='取得日数（デフォルト: 14）')
    parser.add_argument('--csv-only', action='store_true', help='CSVのみ保存（Sheets書き込みスキップ）')
    parser.add_argument('--clear-sheet', action='store_true', help='Spreadsheetのシートをクリアしてから保存')
    args = parser.parse_args()

    # Spreadsheet ID（環境変数または既存のシートIDを使用）
    spreadsheet_id = os.environ.get('GSHEET_SESSION_LOG_ID')
    if not args.csv_only and not spreadsheet_id:
        print("警告: GSHEET_SESSION_LOG_IDが未設定のためCSVのみ保存します")
        args.csv_only = True

    # シートクリア（オプション）
    if args.clear_sheet and spreadsheet_id:
        print("Spreadsheetシートをクリア中...")
        clear_sheet(spreadsheet_id)

    print("Fitbitクライアントを作成中...")
    client, updated_token = create_fitbit_client()

    # 期間設定
    today = dt.date.today()
    before_date = today + dt.timedelta(days=1)  # 今日を含めるため+1

    print(f"瞑想データを取得中... (過去{args.days}日)")
    meditation_logs = fitbit_api.get_meditation_logs(
        client,
        before_date=before_date,
        limit=100
    )

    # 指定日数でフィルタ
    cutoff_date = today - dt.timedelta(days=args.days)
    filtered_logs = []
    for log in meditation_logs:
        log_date = pd.to_datetime(log['startTime']).date()
        if log_date >= cutoff_date:
            filtered_logs.append(log)

    print(f"取得件数: {len(filtered_logs)}件")

    # DataFrameに変換
    df = logs_to_dataframe(filtered_logs)

    # Spreadsheetに保存（永続化）
    if not args.csv_only:
        print("Google Spreadsheetに保存中...")
        save_to_sheets(df, spreadsheet_id)

    # CSVに保存
    save_to_csv(df)

    output_github_actions_token(updated_token)

    print("完了")


if __name__ == '__main__':
    main()
