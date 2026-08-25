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


def _request(api_token: str, method: str, path: str,
              params: dict | None = None, json_body: dict | None = None) -> requests.Response:
    """API を叩き、クォータ残量をログへ出す

    クォータ超過は HTTP 402 で返る。Toggl の 402 は決済要求ではなくレート制限で、
    そのままだと「Premium が必要」と読める汎用エラーになるため専用の例外にする。
    書き込み（POST）も同じ /me 系の枠を共有する前提で扱う。
    """
    response = requests.request(
        method,
        f'{API_BASE}{path}',
        params=params,
        json=json_body,
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


def _get(api_token: str, path: str, params: dict) -> requests.Response:
    return _request(api_token, 'GET', path, params=params)


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


def fetch_me(api_token: str) -> dict:
    """/me?with_related_data=true の生レスポンス

    default_workspace_id とプロジェクト一覧の両方をここから取る。
    """
    response = _get(api_token, '/me', {'with_related_data': 'true'})
    return response.json()


PROJECTS_PAGE_SIZE = 200


def fetch_projects(api_token: str, workspace_id: int | None = None,
                   active_only: bool = False) -> dict[int, str]:
    """プロジェクトID → プロジェクト名の対応表を取得

    /me?with_related_data=true の projects は **private プロジェクトを含まない**。
    そちらを使うと private プロジェクト（実測: 65件中45件）が名前解決に失敗し、
    push は project_id 無しで黙って投入してしまう。ワークスペースの
    /projects を使うこと。

    workspace_id を渡さない場合は /me を1回追加で叩いて解決する（クォータを
    1消費する）。呼び出し側が既に持っているなら渡すこと。

    プロジェクトが未設定の場合でもタイムエントリは取得できるため、
    応答が空でも例外にせず空 dict を返す。

    Parameters
    ----------
    api_token : str
        Toggl Track の API token
    workspace_id : int | None
        対象ワークスペース。None なら /me の default_workspace_id を使う
    active_only : bool
        True なら archive 済みを除く。既定（False）は archived も含む全件。
        過去エントリの project_name 解決には archived が要るので fetch/push は
        全件、時間を記録できる先だけが要る start/projects は True を使う

    Returns
    -------
    dict[int, str]
        {project_id: project_name}
    """
    if workspace_id is None:
        workspace_id = fetch_me(api_token).get('default_workspace_id')

    projects: dict[int, str] = {}
    page = 1
    while True:
        params = {'per_page': PROJECTS_PAGE_SIZE, 'page': page}
        if active_only:
            params['active'] = 'true'
        response = _get(api_token, f'/workspaces/{workspace_id}/projects', params)
        batch = response.json() or []
        projects.update({p['id']: p['name'] for p in batch})
        if len(batch) < PROJECTS_PAGE_SIZE:
            break
        page += 1
    return projects


def create_time_entry(api_token: str, workspace_id: int, payload: dict) -> dict:
    """POST /workspaces/{workspace_id}/time_entries でタイムエントリを作成

    Parameters
    ----------
    api_token : str
        Toggl Track の API token
    workspace_id : int
        投入先ワークスペースID
    payload : dict
        Toggl API の time entry 作成ペイロード（workspace_id を含む）

    Returns
    -------
    dict
        作成されたタイムエントリ
    """
    response = _request(
        api_token, 'POST', f'/workspaces/{workspace_id}/time_entries', json_body=payload,
    )
    return response.json()


def fetch_current_entry(api_token: str) -> dict | None:
    """GET /me/time_entries/current で計測中のエントリを取得

    計測中のものが無い場合、Toggl は 200 で JSON の null を返す（404 ではない）。
    """
    response = _get(api_token, '/me/time_entries/current', {})
    return response.json() or None


def start_time_entry(api_token: str, workspace_id: int, payload: dict) -> dict:
    """計測中のタイムエントリを開始する

    作成 API は stop 済みエントリと同じ POST だが、duration に負値を入れると
    「計測中」になる（v9 は -1 を受け付ける）。stop は渡さない。

    既に計測中のエントリがある状態で開始すると、Toggl 側が古い方を
    自動で停止する（クライアント側で stop を呼ぶ必要はない）。
    """
    return create_time_entry(api_token, workspace_id, payload)


def stop_time_entry(api_token: str, workspace_id: int, entry_id: int) -> dict:
    """PATCH /workspaces/{workspace_id}/time_entries/{entry_id}/stop で計測を止める"""
    response = _request(
        api_token, 'PATCH', f'/workspaces/{workspace_id}/time_entries/{entry_id}/stop',
    )
    return response.json()
