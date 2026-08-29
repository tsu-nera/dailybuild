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


def scale_item(title: str, low: int, high: int, low_label: str,
              high_label: str, required: bool = True) -> dict:
    """均等目盛（scaleQuestion）の item spec"""
    return {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'scaleQuestion': {
                    'low': low,
                    'high': high,
                    'lowLabel': low_label,
                    'highLabel': high_label,
                },
            },
        },
    }


def checkbox_item(title: str, choices: list, required: bool = True) -> dict:
    """チェックボックス（choiceQuestion）の item spec"""
    return {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'choiceQuestion': {
                    'type': 'CHECKBOX',
                    'options': [{'value': c} for c in choices],
                },
            },
        },
    }


def radio_item(title: str, choices: list, required: bool = True) -> dict:
    """ラジオボタン（choiceQuestion, type RADIO）の item spec"""
    return {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'choiceQuestion': {
                    'type': 'RADIO',
                    'options': [{'value': c} for c in choices],
                },
            },
        },
    }


def text_item(title: str, required: bool = False) -> dict:
    """記述式（textQuestion）の item spec"""
    return {
        'title': title,
        'questionItem': {
            'question': {
                'required': required,
                'textQuestion': {'paragraph': False},
            },
        },
    }


def _question_kind(item: dict) -> str | None:
    """item から質問の種類を取り出す（scaleQuestion / choiceQuestion / textQuestion）"""
    question = item.get('questionItem', {}).get('question', {})
    for kind in ('scaleQuestion', 'choiceQuestion', 'textQuestion'):
        if kind in question:
            return kind
    return None


def sync_questions(service, form_id: str, items: list,
                   existing_form: dict = None) -> dict:
    """フォームの質問を items（望ましい item spec のリスト）に合わせる

    existing_form が None なら全 item を新規作成する。
    existing_form があれば、既存 item と items を「質問の種類」で
    突き合わせて createItem / updateItem に振り分ける。

    index で突き合わせてはいけない。questionId は item に紐づいて保持される
    ため、既存 item の型を作り変える（= 別の質問として updateItem する）と、
    過去の回答の questionId が新しい質問のものとして残ってしまう。

    さらに実機で確認した Forms API の癖として、updateItem の
    questionItem.question に questionId を明示しないと、たとえ既存 item を
    正しく標的にしていても **API 側が新しい questionId を割り当てて
    しまう**（title だけの変更でも起きる）。これをやると過去回答の
    questionId が古いままになり、CSV 側から二度と引けなくなる。
    そのため update する item には既存の questionId を明示的に埋め込む。
    """
    if existing_form is None:
        requests = [
            {'createItem': {'item': item, 'location': {'index': i}}}
            for i, item in enumerate(items)
        ]
        return service.forms().batchUpdate(
            formId=form_id, body={'requests': requests}).execute()

    existing_items = [i for i in existing_form.get('items', [])
                      if 'questionItem' in i]
    existing_by_kind = {}
    for item in existing_items:
        kind = _question_kind(item)
        existing_by_kind.setdefault(kind, []).append(item)

    create_requests = []
    update_requests = []
    final_index = 0
    used_item_ids = set()
    for spec in items:
        kind = _question_kind(spec)
        bucket = existing_by_kind.get(kind, [])
        if bucket:
            existing_item = bucket.pop(0)
            used_item_ids.add(existing_item.get('itemId'))
            existing_question_id = existing_item.get(
                'questionItem', {}).get('question', {}).get('questionId')
            update_item = {
                'title': spec['title'],
                'questionItem': {
                    'question': {
                        **spec['questionItem']['question'],
                        'questionId': existing_question_id,
                    },
                },
            }
            update_requests.append({
                'updateItem': {
                    'item': update_item,
                    'location': {'index': final_index},
                    'updateMask': 'title,questionItem.question',
                },
            })
        else:
            create_requests.append({
                'createItem': {'item': spec, 'location': {'index': final_index}},
            })
        final_index += 1

    leftover = [i for i in existing_items if i.get('itemId') not in used_item_ids]
    if leftover:
        raise GoogleFormsError(
            '望ましい質問構成に対応しない既存の質問が残っている'
            '（画面で手編集された可能性がある）: '
            f"{[(i.get('title'), _question_kind(i)) for i in leftover]}"
        )

    # createItem を先に適用し、updateItem の index は create 適用後
    # （= 最終的な望ましい順序）の index を使う
    requests = create_requests + update_requests
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
