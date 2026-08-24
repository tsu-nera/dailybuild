"""Toggl Track API v9 クライアント

API token による Basic 認証。OAuth のトークンリフレッシュは不要。
2025-09-05 導入のクォータにより、/me 系エンドポイントは全プラン共通で
30リクエスト/時（ユーザー単位・sliding window）。本モジュールは1回の取得で
/me/time_entries と /me の2リクエストのみ使うため、待機やスロットリングは持たない。
枠は Toggl の Web アプリや他のクライアントとも共有されるため、手元でカウンタを
持っても実際の残量は分からない。サーバーが返す X-Toggl-Quota-Remaining が唯一の
情報源なので、リクエストのたびに残量をログへ出す。
"""

import datetime as dt
import logging

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

API_BASE = 'https://api.track.toggl.com/api/v9'

REQUEST_TIMEOUT = 60

QUOTA_EXCEEDED_STATUS = 402


def _get(api_token: str, path: str, params: dict) -> requests.Response:
    """API を叩き、クォータ残量をログへ出す

    クォータ超過は HTTP 402 で返る。Toggl の 402 は決済要求ではなくレート制限で、
    そのままだと「Premium が必要」と読める汎用エラーになるため専用の例外にする。
    """
    response = requests.get(
        f'{API_BASE}{path}',
        params=params,
        auth=HTTPBasicAuth(api_token, 'api_token'),
        timeout=REQUEST_TIMEOUT,
    )

    remaining = response.headers.get('X-Toggl-Quota-Remaining')
    if remaining is not None:
        logger.info('Toggl クォータ残: %s/30 (%s)', remaining, path)

    if response.status_code == QUOTA_EXCEEDED_STATUS:
        resets_in = response.headers.get('X-Toggl-Quota-Resets-In', '不明')
        raise RuntimeError(
            f'Toggl API のクォータ超過（/me 系は 30リクエスト/時）。'
            f'{resets_in} 秒後に回復。Premium 制限ではない'
        )

    response.raise_for_status()
    return response


def fetch_time_entries(api_token: str, start: dt.date, end: dt.date) -> list[dict]:
    """指定期間のタイムエントリを取得

    Parameters
    ----------
    api_token : str
        Toggl Track の API token
    start, end : datetime.date
        取得期間（両端を含む）。API の end_date は排他的なので内部で +1日 して渡す

    Returns
    -------
    list[dict]
        タイムエントリのリスト
    """
    params = {
        'start_date': start.isoformat(),
        'end_date': (end + dt.timedelta(days=1)).isoformat(),
    }
    response = _get(api_token, '/me/time_entries', params)
    return response.json()


def fetch_projects(api_token: str) -> dict[int, str]:
    """プロジェクトID → プロジェクト名の対応表を取得

    プロジェクトが未設定の場合でもタイムエントリは取得できるため、
    projects が空/欠落でも例外にせず空 dict を返す。

    Parameters
    ----------
    api_token : str
        Toggl Track の API token

    Returns
    -------
    dict[int, str]
        {project_id: project_name}
    """
    response = _get(api_token, '/me', {'with_related_data': 'true'})
    data = response.json()
    projects = data.get('projects') or []
    return {p['id']: p['name'] for p in projects}
