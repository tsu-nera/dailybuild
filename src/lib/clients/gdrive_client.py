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

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

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
