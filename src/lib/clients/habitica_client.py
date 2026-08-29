"""Habitica API クライアント

認証時のレート制限は 30 req/min（1リクエスト1消費）。429 には `Retry-After`
が秒（小数）で必ず入るので、素直に待って1度だけ再試行する。

詳細と落とし穴は docs/habitica.md を参照。
"""

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_URL = 'https://habitica.com/api/v3'
APP_NAME = 'dailybuild'
MAX_RETRY_WAIT = 90.0


class HabiticaError(RuntimeError):
    """API が期待どおりに応答しなかった（欠測を捏造せず落とすために投げる）"""


class HabiticaClient:
    def __init__(self, user_id: str, api_token: str):
        self.user_id = user_id
        self._headers = {
            'x-api-user': user_id,
            'x-api-key': api_token,
            'x-client': f'{user_id}-{APP_NAME}',
            'content-type': 'application/json',
        }

    @classmethod
    def from_config(cls, path: Path) -> 'HabiticaClient':
        if not path.exists():
            raise HabiticaError(
                f"認証情報がありません: {path}\n"
                "https://habitica.com/user/settings/api の User ID と API Token を\n"
                '{"user_id": "...", "api_token": "..."} の形で置いてください。'
            )
        creds = json.loads(path.read_text())
        missing = [k for k in ('user_id', 'api_token') if not creds.get(k)]
        if missing:
            raise HabiticaError(f"{path} に {', '.join(missing)} がありません")
        return cls(creds['user_id'], creds['api_token'])

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        """API を叩いて data 部を返す。429 は Retry-After に従って1度だけ待つ。"""
        for attempt in (1, 2):
            try:
                return self._raw_request(method, path, body)
            except HabiticaError as e:
                wait = getattr(e, 'retry_after', None)
                if wait is None or attempt == 2:
                    raise
                if wait > MAX_RETRY_WAIT:
                    raise HabiticaError(
                        f"レート制限の待ち時間が長すぎます（{wait:.0f}秒）: {method} {path}"
                    ) from e
                logger.warning("レート制限。%.1f秒待って再試行します", wait)
                time.sleep(wait)
        raise AssertionError('unreachable')

    def _raw_request(self, method: str, path: str, body: dict | None) -> dict:
        req = urllib.request.Request(
            BASE_URL + path,
            method=method,
            headers=self._headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                payload = json.loads(res.read())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = {'message': raw[:200].decode('utf-8', 'replace')}
            err = HabiticaError(
                f"{method} {path} が {e.code}: "
                f"{payload.get('error', '')} {payload.get('message', '')}".strip()
            )
            if e.code == 429:
                err.retry_after = _parse_retry_after(e.headers.get('Retry-After'))
            raise err from None
        except urllib.error.URLError as e:
            raise HabiticaError(f"{method} {path} に接続できません: {e.reason}") from None

        if not payload.get('success'):
            raise HabiticaError(f"{method} {path} が success=false: {payload}")
        return payload.get('data', {})

    def get_user(self) -> dict:
        """ユーザー情報。userFields を付けると needsCron が返らないので付けない。"""
        return self.request('GET', '/user')

    def run_cron(self) -> dict:
        """未処理の日付をまたぐ処理を走らせる（Daily の history はこれでしか増えない）"""
        return self.request('POST', '/cron')

    def get_tasks(self, task_type: str) -> list:
        data = self.request('GET', f'/tasks/user?type={task_type}')
        if not isinstance(data, list):
            raise HabiticaError(f"tasks/user?type={task_type} がリストを返しません: {type(data)}")
        return data


def _parse_retry_after(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
