"""Toggl Track API v9 クライアント

API token による Basic 認証。OAuth のトークンリフレッシュは不要。
レートリミットは目安 1req/sec だが、日次1回の運用ではリトライ機構は不要。
"""

import datetime as dt
import logging

import requests
from requests.auth import HTTPBasicAuth

logger = logging.getLogger(__name__)

API_BASE = 'https://api.track.toggl.com/api/v9'

REQUEST_TIMEOUT = 60


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
    response = requests.get(
        f'{API_BASE}/me/time_entries',
        params=params,
        auth=HTTPBasicAuth(api_token, 'api_token'),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
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
    response = requests.get(
        f'{API_BASE}/me',
        params={'with_related_data': 'true'},
        auth=HTTPBasicAuth(api_token, 'api_token'),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    projects = data.get('projects') or []
    return {p['id']: p['name'] for p in projects}
