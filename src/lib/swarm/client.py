"""Swarm（Foursquare）v2 API クライアント

履歴の全件一覧は v2 の users/self/checkins にしか無い（新しい Personalization API は
直近3時間の recent だけ）。認証は OAuth2 の code フローで、access token に期限は無い
（Foursquare 側で連携を取り消すまで有効）。

code は redirect_uri（既定 localhost:8765）で待ち受けて受け取る。標準入力に貼らせる方式は
Claude Code の `!` 実行で stdin が無く EOFError になったのでやめた。
"""

import http.server
import logging
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from lib.utils.env import ENV_FILE, get_env, require_env

logger = logging.getLogger(__name__)

API_URL = 'https://api.foursquare.com/v2'
AUTHORIZE_URL = 'https://foursquare.com/oauth2/authenticate'
TOKEN_URL = 'https://foursquare.com/oauth2/access_token'

# v2 は日付でレスポンス形式を固定する（無いと 410 で落ちる）
API_VERSION = '20240601'

DEFAULT_REDIRECT_URI = 'http://localhost:8765/callback'
KEY_HINT = 'https://foursquare.com/developers でアプリを登録し、Client ID と Client Secret を書く'

REQUEST_TIMEOUT = 60
PAGE_LIMIT = 250
PAGE_INTERVAL_SEC = 1.0
MAX_RETRIES = 4


class SwarmError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f'Foursquare error {code}: {message}')
        self.code = code


def load_credentials(env_file: Path = ENV_FILE, environ=os.environ) -> tuple[str, str, str]:
    """(client_id, client_secret, redirect_uri)。id/secret が無ければ MissingEnvError"""
    return (
        require_env('FOURSQUARE_CLIENT_ID', hint=KEY_HINT, env_file=env_file, environ=environ),
        require_env('FOURSQUARE_CLIENT_SECRET', hint=KEY_HINT, env_file=env_file, environ=environ),
        get_env('FOURSQUARE_REDIRECT_URI', DEFAULT_REDIRECT_URI, env_file=env_file, environ=environ),
    )


def authorize_url(client_id: str, redirect_uri: str) -> str:
    query = urlencode({'client_id': client_id, 'response_type': 'code', 'redirect_uri': redirect_uri})
    return f'{AUTHORIZE_URL}?{query}'


def code_from_redirect(pasted: str) -> str:
    """貼られたリダイレクト先 URL（または code そのもの）から code を取り出す"""
    pasted = pasted.strip()
    if '://' not in pasted:
        return pasted
    codes = parse_qs(urlparse(pasted).query).get('code')
    if not codes:
        raise ValueError(f'URL に code が無い: {pasted}')
    return codes[0]


def wait_for_code(redirect_uri: str, timeout_sec: int = 600) -> str:
    """redirect_uri のホスト・ポートで待ち受け、ブラウザが運んできた code を返す"""
    parsed = urlparse(redirect_uri)
    received: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                received['code'] = code_from_redirect(f'http://localhost{self.path}')
                status, text = 200, 'OK. このタブは閉じてよい。'
            except ValueError:
                status, text = 400, 'code がありません。'
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(text.encode('utf-8'))

        def log_message(self, *args):
            pass

    with http.server.HTTPServer((parsed.hostname, parsed.port or 80), Handler) as server:
        server.timeout = 5
        deadline = time.monotonic() + timeout_sec
        while 'code' not in received:
            if time.monotonic() > deadline:
                raise TimeoutError(f'{timeout_sec}秒待ったが {redirect_uri} に code が届かない')
            server.handle_request()
    return received['code']


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
    response = requests.get(TOKEN_URL, params={
        'client_id': client_id, 'client_secret': client_secret,
        'grant_type': 'authorization_code', 'redirect_uri': redirect_uri, 'code': code,
    }, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    body = response.json()
    if 'access_token' not in body:
        raise SwarmError(response.status_code, str(body))
    return body['access_token']


def get(path: str, token: str, **params) -> tuple[dict, requests.Response]:
    """v2 を叩いて (response 本体, Response) を返す。429・5xx は待って取り直す"""
    # locale を省くとマシンによって category・住所の言語が揺れ、取り直すたびに行が書き換わる（2026-11-12 実測）
    query = {'oauth_token': token, 'v': API_VERSION, 'locale': 'ja', **params}
    for attempt in range(MAX_RETRIES + 1):
        response = requests.get(f'{API_URL}{path}', params=query, timeout=REQUEST_TIMEOUT)
        if (response.status_code == 429 or response.status_code >= 500) and attempt < MAX_RETRIES:
            wait = 2 ** attempt * 30
            logger.warning('Foursquare %s: HTTP %d。%d秒後に取り直す（X-RateLimit-Remaining=%s）',
                           path, response.status_code, wait,
                           response.headers.get('X-RateLimit-Remaining'))
            time.sleep(wait)
            continue
        body = response.json()
        meta = body.get('meta') or {}
        if meta.get('code') != 200:
            raise SwarmError(meta.get('code', response.status_code),
                             f"{meta.get('errorType')}: {meta.get('errorDetail')}")
        return body['response'], response
    raise AssertionError('unreachable')


def fetch_checkins(token: str, after_timestamp: int | None = None) -> list[dict]:
    """自分のチェックインを新しい順に全件取る（after_timestamp を渡すとそれ以降だけ）

    offset ページングで、空ページか offset が count に届いたら止める。
    sort=oldestfirst は付けない: offset が無視されて毎ページ同じ250件が返る（2026-11-12 実測）。
    ページ間で id が重なったら取りこぼしなので、保存させずに落とす。
    """
    items: list[dict] = []
    seen: set[str] = set()
    offset = 0
    started = time.monotonic()
    while True:
        params = {'limit': PAGE_LIMIT, 'offset': offset}
        if after_timestamp is not None:
            params['afterTimestamp'] = after_timestamp
        body, response = get('/users/self/checkins', token, **params)
        page = body['checkins'].get('items') or []
        count = int(body['checkins'].get('count') or 0)
        dup = seen.intersection(c['id'] for c in page)
        if dup:
            raise SwarmError(0, f'offset {offset} のページが前のページと {len(dup)} 件重なった（ページングが壊れている）')
        seen.update(c['id'] for c in page)
        items.extend(page)
        offset += len(page)
        logger.info('Swarm checkins offset %d/%d: %d件（X-RateLimit-Remaining=%s / Limit=%s, %.0f秒経過）',
                    offset, count, len(page),
                    response.headers.get('X-RateLimit-Remaining'),
                    response.headers.get('X-RateLimit-Limit'),
                    time.monotonic() - started)
        if not page or offset >= count:
            return items
        time.sleep(PAGE_INTERVAL_SEC)
