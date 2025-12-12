#!/usr/bin/env python
# coding: utf-8
"""
Google Sheets APIクライアント
"""

import json
import os

import gspread


def create_client(creds_file=None):
    """
    Google Sheetsクライアントを作成

    Args:
        creds_file: Service AccountのJSONファイルパス（省略時は環境変数から読み込み）

    Returns:
        gspread.Client
    """
    if creds_file and os.path.exists(creds_file):
        return gspread.service_account(filename=creds_file)

    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT')
    if creds_json:
        creds = json.loads(creds_json)
        return gspread.service_account_from_dict(creds)

    raise ValueError("認証情報が見つかりません（ファイルまたはGOOGLE_SERVICE_ACCOUNT環境変数）")


def get_or_create_worksheet(spreadsheet, title, rows=1000, cols=30):
    """
    ワークシートを取得、なければ作成

    Args:
        spreadsheet: gspread.Spreadsheet
        title: シート名
        rows: 作成時の行数
        cols: 作成時の列数

    Returns:
        gspread.Worksheet
    """
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def update_dataframe(worksheet, df, include_header=True):
    """
    DataFrameでワークシートを上書き更新

    Args:
        worksheet: gspread.Worksheet
        df: pandas.DataFrame
        include_header: ヘッダー行を含めるか
    """
    values = df.values.tolist()
    if include_header:
        values = [df.columns.tolist()] + values

    worksheet.clear()
    if values:
        worksheet.update(values, 'A1')


def append_rows(worksheet, rows):
    """
    複数行をワークシートに追記

    Args:
        worksheet: gspread.Worksheet
        rows: 追記する行のリスト [[val1, val2, ...], ...]
    """
    if rows:
        worksheet.append_rows(rows)


def append_row(worksheet, values):
    """
    1行をワークシートに追記

    Args:
        worksheet: gspread.Worksheet
        values: 追記する値のリスト [val1, val2, ...]
    """
    worksheet.append_row(values)
