#!/usr/bin/env python
# coding: utf-8
"""
Google Calendar API クライアント（読み取り専用）

gforms_client.SCOPES に calendar スコープを足さない。config/gforms_token.json は
emotion / bowel / phq9 の日次 fetch が共用しており、スコープを増やすと
非対話の daily-fetch.sh が落ちうる（トークンのスコープ変更は再認可が要る）。
gdrive_client と同じ理由で、独自トークンファイルを持つ。

認証情報:
  config/googlehealth_creds.json  OAuth クライアント（gforms_client と共用）
  config/gcalendar_token.json     認可済みトークン（authorize() が生成）
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).parent.parent.parent.parent
CREDS_FILE = BASE_DIR / 'config/googlehealth_creds.json'
TOKEN_FILE = BASE_DIR / 'config/gcalendar_token.json'

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class GoogleCalendarError(RuntimeError):
    """Google Calendar API 呼び出しの失敗"""


def authorize(interactive: bool = True) -> Credentials:
    """認証済み Credentials を返す（gdrive_client.authorize と同じ流儀）"""
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
        raise GoogleCalendarError(
            f'有効なトークンがない: {TOKEN_FILE}。'
            '対話環境で scripts/gcalendar.py fetch --login を実行すること'
        )

    if not CREDS_FILE.exists():
        raise GoogleCalendarError(f'OAuth クライアントがない: {CREDS_FILE}')

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def create_service(interactive: bool = True):
    return build('calendar', 'v3', credentials=authorize(interactive),
                 cache_discovery=False)


def list_events(service, time_min: str, time_max: str) -> list[dict]:
    """primary の予定を全ページ取得する（繰り返しは展開、削除済みも含む）

    time_min / time_max は tz 付きの RFC3339 文字列。
    """
    items: list[dict] = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId='primary',
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            showDeleted=True,
            maxResults=2500,
            pageToken=page_token,
        ).execute()
        items.extend(resp.get('items', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            return items
