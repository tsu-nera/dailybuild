#!/usr/bin/env python
# coding: utf-8
"""
Google Forms API クライアント

気分記録のフォームを生成し、回答を直接読む。回答先スプレッドシートは
作らない（Forms API に回答先のリンク設定が無く、そこだけ手作業として
残ってしまうため）。

サービスアカウントは使えない。Drive の storageQuota が 0 でファイルを
所有できず、forms.create が 500 Internal になる。OAuth でユーザー自身が
所有する。

認証情報:
  config/googlehealth_creds.json  OAuth クライアント（Google Health と共用）
  config/gforms_token.json        認可済みトークン（authorize() が生成）
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

BASE_DIR = Path(__file__).parent.parent.parent.parent
CREDS_FILE = BASE_DIR / 'config/googlehealth_creds.json'
TOKEN_FILE = BASE_DIR / 'config/gforms_token.json'

SCOPES = [
    'https://www.googleapis.com/auth/forms.body',
    'https://www.googleapis.com/auth/forms.responses.readonly',
]


class GoogleFormsError(RuntimeError):
    """Google Forms API 呼び出しの失敗"""


def authorize(interactive: bool = True) -> Credentials:
    """認証済み Credentials を返す（googlehealth_api.authorize と同じ流儀）"""
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
        raise GoogleFormsError(
            f'有効なトークンがない: {TOKEN_FILE}。'
            'authorize(interactive=True) を対話環境で実行すること'
        )

    if not CREDS_FILE.exists():
        raise GoogleFormsError(f'OAuth クライアントがない: {CREDS_FILE}')

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
    creds = flow.run_local_server(port=8080, access_type='offline', prompt='consent')
    TOKEN_FILE.write_text(creds.to_json())
    return creds


def create_service(interactive: bool = True):
    return build('forms', 'v1', credentials=authorize(interactive),
                 cache_discovery=False)


def create_form(service, title: str, document_title: str = None) -> dict:
    """空のフォームを作る。create では info.title 以外を渡せない"""
    info = {'title': title}
    if document_title:
        info['documentTitle'] = document_title
    return service.forms().create(body={'info': info}).execute()


def add_questions(service, form_id: str, checkbox_title: str, choices: list,
                  text_title: str) -> dict:
    """チェックボックス（必須）と記述式（任意）を1つずつ足す"""
    requests = [
        {
            'createItem': {
                'item': {
                    'title': checkbox_title,
                    'questionItem': {
                        'question': {
                            'required': True,
                            'choiceQuestion': {
                                'type': 'CHECKBOX',
                                'options': [{'value': c} for c in choices],
                            },
                        },
                    },
                },
                'location': {'index': 0},
            },
        },
        {
            'createItem': {
                'item': {
                    'title': text_title,
                    'questionItem': {
                        'question': {
                            'required': False,
                            'textQuestion': {'paragraph': False},
                        },
                    },
                },
                'location': {'index': 1},
            },
        },
    ]
    return service.forms().batchUpdate(
        formId=form_id, body={'requests': requests}).execute()


def get_form(service, form_id: str) -> dict:
    return service.forms().get(formId=form_id).execute()


def question_id_by_title(form: dict) -> dict:
    """質問タイトル -> questionId。回答の突き合わせに使う"""
    result = {}
    for item in form.get('items', []):
        question = item.get('questionItem', {}).get('question')
        if question and 'questionId' in question:
            result[item.get('title')] = question['questionId']
    return result


def list_responses(service, form_id: str) -> list:
    """全回答を返す。ページングは尽きるまで辿る"""
    responses = []
    page_token = None
    while True:
        res = service.forms().responses().list(
            formId=form_id, pageToken=page_token).execute()
        responses.extend(res.get('responses', []))
        page_token = res.get('nextPageToken')
        if not page_token:
            return responses


def answer_values(response: dict, question_id: str) -> list:
    """1回答から指定質問の値リストを取り出す。未回答なら空リスト"""
    answer = response.get('answers', {}).get(question_id)
    if not answer:
        return []
    return [a['value'] for a in answer.get('textAnswers', {}).get('answers', [])]
