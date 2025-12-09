#!/usr/bin/env python3
"""
Google SpreadsheetからCSVファイルをダウンロードするスクリプト

使い方:
    # CSVとしてダウンロード
    python scripts/download_meditation_log.py --sheet-id <SPREADSHEET_ID> --output ./data/meditation_log.csv

    # シート名を指定してダウンロード
    python scripts/download_meditation_log.py --sheet-id <SPREADSHEET_ID> --sheet-name "シート1" --output ./data/meditation_log.csv

環境変数:
    GOOGLE_APPLICATION_CREDENTIALS: サービスアカウントJSONファイルのパス
    MEDITATION_SHEET_ID: デフォルトのスプレッドシートID（オプション）
"""

import argparse
import csv
import io
import os
import sys
from pathlib import Path
from typing import Optional, List

from google.oauth2 import service_account
from googleapiclient.discovery import build


# デフォルト設定
DEFAULT_SHEET_ID = "1S0SwyRbM2cAATv_IOpkOspor-_Ov49rTygyTFr2gkwA"
DEFAULT_CREDENTIALS = "private/gdrive-creds.json"

# APIスコープ（読み取り専用）
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]


def authenticate(credentials_path: Optional[str] = None):
    """
    Google APIに認証する

    Args:
        credentials_path: サービスアカウントJSONファイルのパス
                          Noneの場合は環境変数 GOOGLE_APPLICATION_CREDENTIALS を使用

    Returns:
        Sheets APIサービスオブジェクト, Drive APIサービスオブジェクト
    """
    if credentials_path is None:
        credentials_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if not credentials_path:
            # デフォルトパスを試行
            if os.path.exists(DEFAULT_CREDENTIALS):
                credentials_path = DEFAULT_CREDENTIALS
            else:
                raise ValueError(
                    "認証情報が見つかりません。\n"
                    "--credentials オプションで指定するか、\n"
                    "環境変数 GOOGLE_APPLICATION_CREDENTIALS を設定してください。"
                )

    if not os.path.exists(credentials_path):
        raise FileNotFoundError(f"認証情報ファイルが見つかりません: {credentials_path}")

    print(f"認証情報: {credentials_path}")

    credentials = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=SCOPES
    )

    sheets_service = build('sheets', 'v4', credentials=credentials)
    drive_service = build('drive', 'v3', credentials=credentials)

    print("✅ Google API 認証成功")
    return sheets_service, drive_service


def get_sheet_names(sheets_service, spreadsheet_id: str) -> List[str]:
    """
    スプレッドシート内のシート名一覧を取得

    Args:
        sheets_service: Sheets APIサービス
        spreadsheet_id: スプレッドシートID

    Returns:
        シート名のリスト
    """
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id
    ).execute()

    sheet_names = []
    for sheet in spreadsheet.get('sheets', []):
        props = sheet.get('properties', {})
        sheet_names.append(props.get('title', ''))

    return sheet_names


def download_sheet_as_csv(
    sheets_service,
    spreadsheet_id: str,
    sheet_name: Optional[str] = None,
    output_path: str = './data/meditation_log.csv'
) -> str:
    """
    スプレッドシートをCSVとしてダウンロード

    Args:
        sheets_service: Sheets APIサービス
        spreadsheet_id: スプレッドシートID
        sheet_name: シート名（省略時は最初のシート）
        output_path: 出力ファイルパス

    Returns:
        保存したファイルのパス
    """
    # シート名が指定されていない場合、最初のシートを使用
    if sheet_name is None:
        sheet_names = get_sheet_names(sheets_service, spreadsheet_id)
        if not sheet_names:
            raise ValueError("スプレッドシートにシートが見つかりません")
        sheet_name = sheet_names[0]
        print(f"シート名: {sheet_name}")

    # シートのデータを取得
    range_name = f"'{sheet_name}'"
    print(f"\nデータを取得中: {range_name}")

    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name
    ).execute()

    values = result.get('values', [])

    if not values:
        print("⚠️  データが見つかりませんでした")
        return None

    print(f"✅ {len(values)} 行のデータを取得")

    # 出力ディレクトリ作成
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # CSVとして保存
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for row in values:
            writer.writerow(row)

    print(f"✅ CSVファイルを保存: {output_file}")
    return str(output_file)


def list_sheets(sheets_service, spreadsheet_id: str):
    """
    スプレッドシート内のシート一覧を表示

    Args:
        sheets_service: Sheets APIサービス
        spreadsheet_id: スプレッドシートID
    """
    spreadsheet = sheets_service.spreadsheets().get(
        spreadsheetId=spreadsheet_id
    ).execute()

    title = spreadsheet.get('properties', {}).get('title', '不明')
    print(f"\nスプレッドシート: {title}")
    print("=" * 50)

    sheets = spreadsheet.get('sheets', [])
    print(f"シート数: {len(sheets)}")
    print()

    for i, sheet in enumerate(sheets, 1):
        props = sheet.get('properties', {})
        name = props.get('title', '不明')
        grid = props.get('gridProperties', {})
        rows = grid.get('rowCount', 0)
        cols = grid.get('columnCount', 0)
        print(f"{i}. {name} ({rows}行 x {cols}列)")


def main():
    parser = argparse.ArgumentParser(
        description='Google SpreadsheetからCSVファイルをダウンロード',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # シート一覧を表示
  python %(prog)s --sheet-id 1ABC123... --list

  # CSVとしてダウンロード（最初のシート）
  python %(prog)s --sheet-id 1ABC123... --output ./data/meditation_log.csv

  # 特定のシートをダウンロード
  python %(prog)s --sheet-id 1ABC123... --sheet-name "シート1" --output ./data/meditation_log.csv

  # 認証情報を明示的に指定
  python %(prog)s --credentials private/credentials.json --sheet-id 1ABC123... --output ./data/meditation_log.csv
        """
    )

    parser.add_argument(
        '--credentials',
        type=str,
        help='サービスアカウントJSONファイルのパス（省略時は環境変数 GOOGLE_APPLICATION_CREDENTIALS を使用）'
    )

    parser.add_argument(
        '--sheet-id',
        type=str,
        default=os.environ.get('MEDITATION_SHEET_ID', DEFAULT_SHEET_ID),
        help='スプレッドシートID（省略時はデフォルト値を使用）'
    )

    parser.add_argument(
        '--sheet-name',
        type=str,
        help='ダウンロードするシート名（省略時は最初のシート）'
    )

    parser.add_argument(
        '--list',
        action='store_true',
        help='シート一覧を表示'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='./tmp/meditation_log.csv',
        help='出力ファイルパス（デフォルト: ./tmp/meditation_log.csv）'
    )

    args = parser.parse_args()

    try:
        # 認証
        sheets_service, drive_service = authenticate(args.credentials)

        if args.list:
            # シート一覧表示
            list_sheets(sheets_service, args.sheet_id)
        else:
            # CSVダウンロード
            output_path = download_sheet_as_csv(
                sheets_service,
                args.sheet_id,
                args.sheet_name,
                args.output
            )

            if output_path:
                print(f"\n✅ すべての処理が完了しました")
                print(f"ファイルパス: {output_path}")

    except Exception as e:
        print(f"\n❌ エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
