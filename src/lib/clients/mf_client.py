"""
MoneyForward ME 家計簿データ取得クライアント

MF ME に公式 API は無い。ブラウザのログインセッション（Cookie）で
`/cf/csv` を叩くと収入・支出詳細の CSV がそのまま落ちてくるため、
画面のスクレイピングはせずこのエンドポイントだけを使う。

Cookie は Playwright の storage_state として config/mf_state.json に持つ。
初回とセッション切れのときだけ headful ブラウザで手動ログイン（2FA 含む）
させる。認証情報自体はローカルに保存しない。

注意点:
- CSV の実体は cp932。レスポンスヘッダの charset=utf-8 は正しくない
- 未ログインだと 200 のままログイン画面の HTML が返る。欠測を捏造しない
  よう、CSV ヘッダで内容を検証して NotLoggedInError で落とす
- MF は User-Agent に HeadlessChrome を含むリクエストを 403 で弾く。
  headless で動かすには UA を通常の Chrome に差し替える必要がある
- CSV に出るのは MF が金融機関から取り込み済みの明細だけ。一括更新
  （kick_refresh）を叩かないと自動更新のタイミング次第で数日古いままになる。
  更新は金融機関ごとに非同期で走り、カード会社は完了まで10分以上かかることが
  あるため、完了は待たない（結果は次回の取得で回収する）
"""

import datetime as dt
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

CF_URL = 'https://moneyforward.com/cf'
CSV_URL = 'https://moneyforward.com/cf/csv'
ACCOUNTS_URL = 'https://moneyforward.com/accounts'
# 画面の「金融機関からのデータ一括更新」ボタンが叩く Rails UJS のエンドポイント
REFRESH_URL = 'https://moneyforward.com/faggregation_queue2'
LOGIN_HOST = 'id.moneyforward.com'

# レスポンスヘッダは charset=utf-8 と名乗るが実体は cp932
CSV_ENCODING = 'cp932'
# ログイン画面の HTML が 200 で返るケースを弾くための検証
EXPECTED_HEADER = '計算対象'

LOGIN_TIMEOUT_SEC = 300

# HeadlessChrome を名乗ると 403 になるため通常の Chrome に偽装する
USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')

# 保存する Cookie のドメイン。広告トラッカーの Cookie まで抱え込まない
COOKIE_DOMAIN_SUFFIX = 'moneyforward.com'


def _save_state(context, state_file: Path) -> None:
    """storage_state を MF のドメインの Cookie だけに絞って保存する"""
    state = context.storage_state()
    state['cookies'] = [
        cookie for cookie in state['cookies']
        if cookie['domain'].lstrip('.').endswith(COOKIE_DOMAIN_SUFFIX)
    ]
    state_file.write_text(json.dumps(state, ensure_ascii=False))


class NotLoggedInError(RuntimeError):
    """セッションが無効。--login で取り直す必要がある"""


def login(state_file: Path, timeout_sec: int = LOGIN_TIMEOUT_SEC) -> None:
    """headful ブラウザを開いて手動ログインさせ、Cookie を state_file に保存する"""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.goto(CF_URL)

        print("ブラウザでマネーフォワード ME にログインしてください（2FA 含む）。")
        print(f"家計簿画面に到達したら自動で保存します（最大 {timeout_sec} 秒待機）。")

        page.wait_for_url(
            lambda url: url.startswith(CF_URL),
            timeout=timeout_sec * 1000,
        )

        state_file.parent.mkdir(parents=True, exist_ok=True)
        _save_state(context, state_file)
        browser.close()

    print(f"セッションを保存しました: {state_file}")


class MoneyForwardSession:
    """保存済み Cookie で CSV を取得するセッション（with 文で使う）"""

    def __init__(self, state_file: Path):
        if not state_file.exists():
            raise NotLoggedInError(
                f"セッションファイルがありません: {state_file}\n"
                f"  uv run scripts/fetch_mf.py --login"
            )
        self._state_file = state_file
        self._playwright = None
        self._browser = None
        self._context = None
        self._accounts_page = None

    def __enter__(self) -> 'MoneyForwardSession':
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            storage_state=str(self._state_file), user_agent=USER_AGENT)
        return self

    def __exit__(self, *exc_info) -> None:
        # セッション延長分の Cookie を書き戻す（正常終了時のみ）
        if exc_info[0] is None and self._context is not None:
            _save_state(self._context, self._state_file)
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def _csrf_token(self) -> str:
        """/accounts を開いて Rails の CSRF トークンを取る"""
        page = self._context.new_page()
        response = page.goto(ACCOUNTS_URL)
        if LOGIN_HOST in page.url or response.status != 200:
            raise NotLoggedInError(
                f"連携口座一覧を開けません (status={response.status}, url={page.url})\n"
                f"  セッション切れの可能性があります: uv run scripts/fetch_mf.py --login"
            )
        token = page.evaluate(
            "() => document.querySelector('meta[name=\"csrf-token\"]')?.content")
        self._accounts_page = page
        if not token:
            raise NotLoggedInError('CSRF トークンを取得できません')
        return token

    def kick_refresh(self) -> None:
        """金融機関からのデータ一括更新をキックする（完了は待たない）"""
        token = self._csrf_token()
        response = self._context.request.post(REFRESH_URL, headers={
            'X-CSRF-Token': token,
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'text/javascript, application/javascript, */*; q=0.01',
            'Referer': ACCOUNTS_URL,
        })
        if response.status != 200:
            raise RuntimeError(f"一括更新をキックできません (status={response.status})")

    def account_status(self) -> list[tuple[str, str, str]]:
        """連携口座の (名前, 最終取得日時, 状態) を返す"""
        if getattr(self, '_accounts_page', None) is None:
            self._csrf_token()
        rows = self._accounts_page.evaluate(r"""() =>
            [...document.querySelectorAll('table tr')]
                .map(r => r.innerText.replace(/\s+/g, ' ').trim())
                .filter(t => /\(\d\d\/\d\d \d\d:\d\d\)|更新中|取得中/.test(t))""")
        parsed = []
        for row in rows:
            name = row.split(' (')[0].strip()
            match = re.search(r'\((\d\d/\d\d \d\d:\d\d)\)\s*(.*)$', row)
            fetched_at = match.group(1) if match else ''
            status = (match.group(2) if match else row).strip()
            parsed.append((name, fetched_at, status))
        return parsed

    def fetch_month_csv(self, year: int, month: int) -> str:
        """指定月の収入・支出詳細 CSV を文字列で返す"""
        response = self._context.request.get(CSV_URL, params={
            'from': f'{year:04d}/{month:02d}/01',
            'month': str(month),
            'year': str(year),
        })

        if LOGIN_HOST in response.url or response.status != 200:
            raise NotLoggedInError(
                f"CSV を取得できません (status={response.status}, url={response.url})\n"
                f"  セッション切れの可能性があります: uv run scripts/fetch_mf.py --login"
            )

        text = response.body().decode(CSV_ENCODING, errors='replace')

        if EXPECTED_HEADER not in text.split('\n', 1)[0]:
            raise NotLoggedInError(
                f"CSV ではない応答が返りました ({year}/{month:02d})。"
                f"セッション切れの可能性があります: uv run scripts/fetch_mf.py --login"
            )

        return text


def month_range(start: dt.date, end: dt.date) -> list[tuple[int, int]]:
    """start〜end を (year, month) のリストに展開する（両端含む）"""
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months
