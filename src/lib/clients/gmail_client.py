#!/usr/bin/env python
# coding: utf-8
"""
Gmail API クライアント（読み取り専用）

gtd の Gmail トークン（~/.config/gcp/tokens/gmail.json）は gmail.modify を持つ。
こちらは注文確認を読むだけなので gmail.readonly の独自トークンを持つ。
処理済みの印を Gmail のラベルで付けない（CSV 側の message_id で冪等にする）ので
modify は要らない。

認証情報:
  config/googlehealth_creds.json  OAuth クライアント（gcalendar_client と共用）
  config/gmail_token.json         認可済みトークン（authorize() が生成）
"""

import base64
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).parent.parent.parent.parent
CREDS_FILE = BASE_DIR / 'config/googlehealth_creds.json'
TOKEN_FILE = BASE_DIR / 'config/gmail_token.json'

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


class GmailError(RuntimeError):
    """Gmail API 呼び出しの失敗"""


def authorize(interactive: bool = True) -> Credentials:
    """認証済み Credentials を返す（gcalendar_client.authorize と同じ流儀）"""
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
        raise GmailError(
            f'有効なトークンがない: {TOKEN_FILE}。'
            '対話環境で scripts/purchases.py fetch --login を実行すること'
        )

    if not CREDS_FILE.exists():
        raise GmailError(f'OAuth クライアントがない: {CREDS_FILE}')

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def create_service(interactive: bool = True):
    return build('gmail', 'v1', credentials=authorize(interactive),
                 cache_discovery=False)


def list_message_ids(service, query: str) -> list[str]:
    """query に一致するメッセージ ID を全ページ取得する"""
    ids: list[str] = []
    page_token = None
    while True:
        resp = service.users().messages().list(
            userId='me', q=query, pageToken=page_token, maxResults=500,
        ).execute()
        ids.extend(m['id'] for m in resp.get('messages', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            return ids


def get_message(service, message_id: str) -> dict:
    return service.users().messages().get(
        userId='me', id=message_id, format='full').execute()


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode()).decode('utf-8', errors='replace')


def body_parts(payload: dict) -> dict[str, str]:
    """MIME ツリーから最初の text/plain と text/html の本文を取り出す"""
    found: dict[str, str] = {}
    stack = [payload]
    while stack:
        part = stack.pop(0)
        mime = part.get('mimeType', '')
        data = (part.get('body') or {}).get('data')
        if data and mime in ('text/plain', 'text/html') and mime not in found:
            found[mime] = _decode(data)
        stack.extend(part.get('parts', []))
    return found
