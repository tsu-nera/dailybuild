#!/usr/bin/env python
# coding: utf-8
"""
Google Drive API クライアント（読み取り専用）

Hevy CSV export のように、手動で Drive に置かれるファイルを読むためだけに
使う。認証情報の探索順序は gsheets_client.create_client() と揃えてある
（引数 -> GOOGLE_APPLICATION_CREDENTIALS -> GOOGLE_SERVICE_ACCOUNT ->
~/.config/gcp/gdrive-creds.json）。
"""

import io
import json
import os

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

_DEFAULT_CREDS_PATHS = [
    os.path.expanduser('~/.config/gcp/gdrive-creds.json'),
]


def create_service(creds_file=None):
    """
    認証済み Drive service (v3) を作る

    Args:
        creds_file: Service AccountのJSONファイルパス（省略時は環境変数・共通パスから探索）

    Returns:
        googleapiclient.discovery.Resource (drive v3)
    """
    if creds_file and os.path.exists(creds_file):
        creds = service_account.Credentials.from_service_account_file(
            creds_file, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)

    env_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if env_path and os.path.exists(env_path):
        creds = service_account.Credentials.from_service_account_file(
            env_path, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)

    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT')
    if creds_json:
        info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)

    for path in _DEFAULT_CREDS_PATHS:
        if os.path.exists(path):
            creds = service_account.Credentials.from_service_account_file(
                path, scopes=SCOPES)
            return build('drive', 'v3', credentials=creds)

    raise ValueError("認証情報が見つかりません（GOOGLE_APPLICATION_CREDENTIALS / GOOGLE_SERVICE_ACCOUNT / ~/.config/gcp/gdrive-creds.json）")


def download_latest(service, folder_id, name) -> bytes:
    """
    指定フォルダ内で指定名の最新ファイルをダウンロードする

    Drive は同名ファイルを上書きせず、アップロードのたびに別 fileId で
    重複作成する（実測: measurement_data.csv が同名同サイズで2件存在）。
    そのため名前だけではファイルが1件に決まらず、createdTime 降順で
    並べた先頭（＝最新のアップロード）を採る必要がある。

    Args:
        service: create_service() で作った Drive service
        folder_id: 検索対象のフォルダ ID
        name: ファイル名（完全一致）

    Returns:
        bytes: ファイルの内容

    Raises:
        FileNotFoundError: 該当フォルダに指定名のファイルが1件もない場合
    """
    query = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    response = service.files().list(
        q=query,
        orderBy='createdTime desc',
        fields='files(id, name, createdTime)',
    ).execute()

    files = response.get('files', [])
    if not files:
        raise FileNotFoundError(
            f"フォルダ {folder_id} に {name} が見つかりません")

    file_id = files[0]['id']

    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    return buf.getvalue()
