"""Last.fm API クライアント

再生履歴を非公開（Settings → Privacy の Hide recent listening information）にしていると、
api_key だけの user.getRecentTracks は error 17（要ログイン）で落ちる。そのため
認証セッション（sk）付きの署名リクエストで読む。

セッションは auth.getToken → ブラウザで許可 → auth.getSession で得る。sk に期限は無い
（Last.fm 側で連携を取り消すまで有効）。
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path

import requests

from lib.utils.env import ENV_FILE, require_env

logger = logging.getLogger(__name__)

API_URL = 'https://ws.audioscrobbler.com/2.0/'
AUTH_URL = 'https://www.last.fm/api/auth/'

KEY_HINT = 'https://www.last.fm/api/accounts（無ければ /api/account/create で発行）の API key と Shared secret'

REQUEST_TIMEOUT = 60
PAGE_LIMIT = 200
# 公式の目安は「1秒に5回を超えない」
PAGE_INTERVAL_SEC = 0.25

# 一時的なエラー（Operation failed / Service Offline / Temporarily unavailable / Rate limit exceeded）
RETRYABLE_ERRORS = {8, 11, 16, 29}
MAX_RETRIES = 4

ERROR_TOKEN_NOT_AUTHORIZED = 14


class LastfmError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f'Last.fm error {code}: {message}')
        self.code = code


def load_credentials(env_file: Path = ENV_FILE, environ=os.environ) -> tuple[str, str, str]:
    """(api_key, api_secret, user)。どれか無ければ MissingEnvError"""
    return (
        require_env('LASTFM_API_KEY', hint=KEY_HINT, env_file=env_file, environ=environ),
        require_env('LASTFM_API_SECRET', hint=KEY_HINT, env_file=env_file, environ=environ),
        require_env('LASTFM_USER', env_file=env_file, environ=environ),
    )


def sign(params: dict, api_secret: str) -> str:
    """api_sig: format・callback を除くパラメータを名前順に name+value で連結し、secret を足した md5"""
    payload = ''.join(f'{k}{params[k]}' for k in sorted(params) if k not in ('format', 'callback'))
    return hashlib.md5((payload + api_secret).encode('utf-8')).hexdigest()


def call(method: str, api_key: str, api_secret: str, **params) -> dict:
    """署名付きで method を呼ぶ。一時的なエラーは待って取り直す"""
    query = {'method': method, 'api_key': api_key, **{k: str(v) for k, v in params.items()}}
    query['api_sig'] = sign(query, api_secret)
    query['format'] = 'json'

    for attempt in range(MAX_RETRIES + 1):
        response = requests.get(API_URL, params=query, timeout=REQUEST_TIMEOUT)
        try:
            body = response.json()
        except json.JSONDecodeError:
            response.raise_for_status()
            raise
        if 'error' not in body:
            response.raise_for_status()
            return body
        code = int(body['error'])
        if code in RETRYABLE_ERRORS and attempt < MAX_RETRIES:
            wait = 2 ** attempt * 5
            logger.warning('Last.fm %s: error %d（%s）。%d秒後に取り直す',
                           method, code, body.get('message'), wait)
            time.sleep(wait)
            continue
        raise LastfmError(code, body.get('message', ''))
    raise AssertionError('unreachable')


def get_token(api_key: str, api_secret: str) -> str:
    return call('auth.getToken', api_key, api_secret)['token']


def auth_url(api_key: str, token: str) -> str:
    return f'{AUTH_URL}?api_key={api_key}&token={token}'


def wait_for_session(api_key: str, api_secret: str, token: str,
                     timeout_sec: int = 600, interval_sec: int = 5) -> dict:
    """ブラウザで許可されるまで auth.getSession を叩き続ける。{'name', 'key', ...} を返す"""
    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            return call('auth.getSession', api_key, api_secret, token=token)['session']
        except LastfmError as exc:
            if exc.code != ERROR_TOKEN_NOT_AUTHORIZED or time.monotonic() > deadline:
                raise
        time.sleep(interval_sec)


def fetch_recent_tracks(api_key: str, api_secret: str, session_key: str, user: str,
                        from_uts: int | None = None) -> list[dict]:
    """from_uts 以降（None なら全期間）の scrobble を全ページ取る

    再生中の曲（@attr.nowplaying）も混ざって返るが、ここでは除かない（store 側で落とす）。
    """
    tracks = []
    page = 1
    while True:
        params = {'user': user, 'sk': session_key, 'limit': PAGE_LIMIT, 'page': page}
        if from_uts is not None:
            params['from'] = from_uts
        body = call('user.getRecentTracks', api_key, api_secret, **params)['recenttracks']
        page_tracks = body.get('track') or []
        if isinstance(page_tracks, dict):  # 1件だけだと配列でなく object で返る
            page_tracks = [page_tracks]
        tracks.extend(page_tracks)
        total_pages = int(body['@attr']['totalPages'])
        logger.info('Last.fm scrobble page %d/%d: %d件', page, total_pages, len(page_tracks))
        if page >= total_pages:
            return tracks
        page += 1
        time.sleep(PAGE_INTERVAL_SEC)
