#!/usr/bin/env python
# coding: utf-8
"""
Google Drive API クライアント（フォルダ移動専用）

forms.create は親フォルダを指定できずマイドライブ直下に作る（Forms API に
その引数が無い）。作成後にこのクライアントで config/personal.yaml の
gdrive.folder_id 配下へ移動する。

gforms_client.SCOPES に drive スコープを足さない。config/gforms_token.json は
emotion / bowel / phq9 の日次 fetch が共用しており、スコープを増やすと
非対話の daily-routine.sh が落ちうる（トークンのスコープ変更は再認可が要る）。
そのため独自トークンファイルを持つ。

認証情報:
  config/googlehealth_creds.json  OAuth クライアント（gforms_client と共用）
  config/gdrive_token.json        認可済みトークン（authorize() が生成）
"""

import io
import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BASE_DIR = Path(__file__).parent.parent.parent.parent
CREDS_FILE = BASE_DIR / 'config/googlehealth_creds.json'
TOKEN_FILE = BASE_DIR / 'config/gdrive_token.json'

# ファイル作成はしない（forms.create が行う）。移動のみなので drive.file で足りる
SCOPES = ['https://www.googleapis.com/auth/drive.file']


class GoogleDriveError(RuntimeError):
    """Google Drive API 呼び出しの失敗"""


def authorize(interactive: bool = True) -> Credentials:
    """認証済み Credentials を返す（gforms_client.authorize と同じ流儀）"""
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
        return creds

    if not interactive:
        raise GoogleDriveError(
            f'有効なトークンがない: {TOKEN_FILE}。'
            'authorize(interactive=True) を対話環境で実行すること'
        )

    if not CREDS_FILE.exists():
        raise GoogleDriveError(f'OAuth クライアントがない: {CREDS_FILE}')

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def create_service(interactive: bool = True):
    return build('drive', 'v3', credentials=authorize(interactive),
                 cache_discovery=False)


def move_to_folder(service, file_id: str, folder_id: str) -> dict:
    """file_id を folder_id 配下へ移動する（既存の親からは外す）"""
    meta = service.files().get(fileId=file_id, fields='parents').execute()
    existing_parents = ','.join(meta.get('parents', []))
    return service.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=existing_parents,
        fields='id, parents',
    ).execute()


# --- 読み取り（service account） ---------------------------------------
#
# 上の authorize() は drive.file スコープなので、**このアプリが作っていない
# ファイルは list にすら出ない**（端末の Hevy が置いた CSV は 0 件で返り、
# 例外は出ない）。他人が置いたファイルを読む経路は service account に分ける。
# 認証情報の探索順は gsheets_client.create_client() と揃える。

READONLY_SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

_DEFAULT_SA_PATHS = [
    os.path.expanduser('~/.config/gcp/gdrive-creds.json'),
]


def _service_account_credentials(creds_file=None):
    for path in [creds_file, os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')]:
        if path and os.path.exists(path):
            return service_account.Credentials.from_service_account_file(
                path, scopes=READONLY_SCOPES)

    creds_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT')
    if creds_json:
        return service_account.Credentials.from_service_account_info(
            json.loads(creds_json), scopes=READONLY_SCOPES)

    for path in _DEFAULT_SA_PATHS:
        if os.path.exists(path):
            return service_account.Credentials.from_service_account_file(
                path, scopes=READONLY_SCOPES)

    raise GoogleDriveError(
        '認証情報が見つかりません'
        '（GOOGLE_APPLICATION_CREDENTIALS / GOOGLE_SERVICE_ACCOUNT / '
        '~/.config/gcp/gdrive-creds.json）'
    )


def create_reader_service(creds_file=None):
    """service account で読み取り専用の Drive サービスを作る"""
    return build('drive', 'v3',
                 credentials=_service_account_credentials(creds_file),
                 cache_discovery=False)


def latest_file(service, folder_id: str, name: str) -> dict:
    """folder_id 直下の name のうち、最後に作られたものを1件返す

    Drive は同名アップロードを上書きせず別 ID で並べる（Hevy の export は
    毎回新しいファイルになる）。名前では1件に決まらないので createdTime の
    降順で先頭を取る。返すのは `id` `name` `createdTime` `size`。

    **フォルダは ID で指定する。** 親（`gdrive.folder_id` の dailybuild）は
    service account に共有されておらず 404 になるため、名前でパスを辿れない。
    """
    query = f"'{folder_id}' in parents and name = '{name}' and trashed = false"
    files = service.files().list(
        q=query,
        fields='files(id, name, createdTime, size)',
        orderBy='createdTime desc',
        pageSize=10,
    ).execute().get('files', [])

    if not files:
        raise GoogleDriveError(
            f'ファイルが見つからない: {name}（フォルダ {folder_id}）。'
            'service account に共有されているかを確認すること'
        )
    return files[0]


def download_file(service, file_id: str) -> bytes:
    """file_id の中身をそのまま返す（Google ネイティブ形式は対象外）"""
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()
