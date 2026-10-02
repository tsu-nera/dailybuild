"""
くらしTEPCO web 電力使用量取得クライアント

公式 API は無いが、画面（Angular SPA）の裏に JSON API（kcx-api.tepco-z.com）があり、
画面を解析せずこれを直接叩く。ポップアップ類は描画すらされない。

認証は Auth0（epauth.tepco.co.jp、PKCE、refresh token なし）。Cookie を Playwright の
storage_state として config/tepco_state.json に持ち、SPA を開かせて silent auth で
Bearer を取らせ、それを横取りして API を叩く。初回とセッション切れのときだけ
headful ブラウザで手動ログインさせる。認証情報自体はローカルに保存しない。

注意点:
- 既定の headless（chrome-headless-shell）では SPA が白画面のまま API を1本も
  呼ばない。new headless（channel='chromium'）なら通る
- Bearer だけでは 400。`x-api-request-id` / `x-kcx-tracking-id`（UUID）が必須
- 値の無いコマは billingStatus=00 で usedInfo が欠落する。0kWh ではなく欠測
- 30分値は約2年で消える（2026-10 時点で 2024-10 は有、2024-06 は無）
- 契約番号は引越しで変わる。SPA が選択中の契約（最初の billing 呼び出し）を使う
"""

import time
import uuid
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

APP_URL = 'https://www.app.kurashi.tepco.co.jp/'
API_URL = 'https://kcx-api.tepco-z.com/kcx'
LOGIN_HOST = 'epauth.tepco.co.jp'

LOGIN_TIMEOUT_SEC = 300
# silent auth → SPA の初回 API 呼び出しまでの待ち
AUTH_TIMEOUT_MS = 60_000
# 連続呼び出しの間隔。制限値は不明なので控えめに
REQUEST_INTERVAL_SEC = 0.3

# 電気の契約種別（ガスは別値）
CONTRACT_CLASS_ELECTRIC = '02'

USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')


class NotLoggedInError(RuntimeError):
    """セッションが無効。--login で取り直す必要がある"""


def _is_authorized_api_request(request) -> bool:
    return request.url.startswith(API_URL) and 'authorization' in request.headers


def login(state_file: Path, timeout_sec: int = LOGIN_TIMEOUT_SEC) -> None:
    """headful ブラウザを開いて手動ログインさせ、Cookie を state_file に保存する"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        print("ブラウザでくらしTEPCO web にログインしてください（認証コード含む）。")
        print(f"ホーム画面が API を呼んだら自動で保存します（最大 {timeout_sec} 秒待機）。")

        with page.expect_request(_is_authorized_api_request, timeout=timeout_sec * 1000):
            page.goto(APP_URL)

        state_file.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state_file))
        browser.close()

    print(f"セッションを保存しました: {state_file}")


class TepcoSession:
    """保存済み Cookie で使用量を取得するセッション（with 文で使う）"""

    def __init__(self, state_file: Path):
        if not state_file.exists():
            raise NotLoggedInError(
                f"セッションファイルがありません: {state_file}\n"
                f"  uv run scripts/tepco.py fetch --login"
            )
        self._state_file = state_file
        self._playwright = None
        self._browser = None
        self._context = None
        self._headers: dict[str, str] = {}
        self.contract_num: str | None = None

    def __enter__(self) -> 'TepcoSession':
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True, channel='chromium')
        self._context = self._browser.new_context(
            storage_state=str(self._state_file), user_agent=USER_AGENT)
        self._authenticate()
        return self

    def __exit__(self, *exc_info) -> None:
        # silent auth で延長された Cookie を書き戻す（正常終了時のみ）
        if exc_info[0] is None and self._context is not None:
            self._context.storage_state(path=str(self._state_file))
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _authenticate(self) -> None:
        page = self._context.new_page()
        billing_urls: list[str] = []
        page.on('request', lambda r: r.url.startswith(f'{API_URL}/billing/') and billing_urls.append(r.url))
        try:
            with page.expect_request(_is_authorized_api_request, timeout=AUTH_TIMEOUT_MS) as info:
                page.goto(APP_URL)
            # 契約番号は billing の呼び出しにしか出ない
            if not billing_urls:
                page.wait_for_event('request', lambda r: r.url.startswith(f'{API_URL}/billing/'),
                                    timeout=AUTH_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            raise NotLoggedInError(
                f"silent auth が通りません (url={page.url})\n"
                f"  uv run scripts/tepco.py fetch --login"
            ) from None

        self._headers = {
            k: v for k, v in info.value.all_headers().items()
            if not k.startswith(':') and k not in ('cookie', 'host', 'content-length')
        }
        self.contract_num = billing_urls[0].split('contractNum=')[1].split('&')[0]
        page.close()

    def _get(self, path: str, params: dict[str, str]) -> dict:
        request_id = str(uuid.uuid4())
        headers = {**self._headers,
                   'x-api-request-id': request_id, 'x-kcx-tracking-id': request_id}
        query = {'contractNum': self.contract_num,
                 'contractClass': CONTRACT_CLASS_ELECTRIC, 'readOffset': '0', **params}
        response = self._context.request.get(f'{API_URL}{path}', headers=headers, params=query)
        time.sleep(REQUEST_INTERVAL_SEC)
        if response.status in (401, 403):
            raise NotLoggedInError(f"{path}: status={response.status}")
        if response.status != 200:
            raise RuntimeError(f"{path} {params}: status={response.status} {response.text()[:200]}")
        body = response.json()
        error = body.get('commonInfo', {}).get('errorCode')
        if error:
            raise RuntimeError(f"{path} {params}: errorCode={error}")
        return body

    def hourly(self, day: str) -> dict:
        """1日分の30分値（usedDay=YYYYMMDD）。生の応答を返す"""
        return self._get('/billing/hourly', {'usedDay': day})
