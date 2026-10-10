"""Home Assistant WebSocket API クライアント（statistics と state 履歴の読み取りのみ）

認証情報は .env の HA_TOKEN（必須）と HA_URL（省略可）。読み込みは lib.utils.env。
"""

import json
from datetime import datetime

from lib.utils.env import MissingEnvError, get_env, require_env

DEFAULT_URL = 'http://localhost:8123'


class HomeAssistantError(Exception):
    pass


def load_settings(**env_kwargs) -> tuple[str, str]:
    """(url, token) を返す。env_kwargs は lib.utils.env へそのまま渡す（テスト用）"""
    try:
        token = require_env(
            'HA_TOKEN',
            hint='HA のプロフィール → セキュリティ → 長期アクセストークンを dailybuild 用に発行する',
            **env_kwargs)
    except MissingEnvError as exc:
        raise HomeAssistantError(str(exc)) from exc
    return get_env('HA_URL', DEFAULT_URL, **env_kwargs), token


def _ws_url(url: str) -> str:
    url = url.rstrip('/')
    if url.startswith('https://'):
        url = 'wss://' + url[len('https://'):]
    elif url.startswith('http://'):
        url = 'ws://' + url[len('http://'):]
    return url + '/api/websocket'


def _default_connect(ws_url: str):
    import websocket
    return websocket.create_connection(ws_url, timeout=60)


class HomeAssistantClient:
    def __init__(self, url: str, token: str, connect=_default_connect):
        self.ws_url = _ws_url(url)
        self.token = token
        self._connect = connect

    def statistics_during_period(self, start: datetime, end: datetime,
                                 statistic_ids: list[str], period: str = '5minute',
                                 types=('mean', 'min', 'max')) -> dict[str, list[dict]]:
        """recorder/statistics_during_period を呼ぶ。start/end は tz-aware 必須"""
        return self._call(start, end, {
            'type': 'recorder/statistics_during_period',
            'statistic_ids': list(statistic_ids),
            'period': period,
            'types': list(types),
        })

    def history_during_period(self, start: datetime, end: datetime,
                              entity_ids: list[str]) -> dict[str, list[dict]]:
        """history/history_during_period を呼ぶ。statistics を持たない文字列・真偽の state 用

        返り値は {entity_id: [{'s': state, 'lu': epoch秒, 'lc'?: epoch秒}, ...]}。
        先頭要素は start 時点の state（変化時刻ではない）。
        """
        return self._call(start, end, {
            'type': 'history/history_during_period',
            'entity_ids': list(entity_ids),
            'minimal_response': True,
            'no_attributes': True,
            'significant_changes_only': False,
        })

    def _call(self, start: datetime, end: datetime, payload: dict) -> dict:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError('start/end は tz-aware にする（HA 側のローカル tz 解釈に頼らない）')
        ws = self._connect(self.ws_url)
        try:
            msg = json.loads(ws.recv())
            if msg.get('type') != 'auth_required':
                raise HomeAssistantError(f"想定外の初期メッセージ: {msg}")
            ws.send(json.dumps({'type': 'auth', 'access_token': self.token}))
            msg = json.loads(ws.recv())
            if msg.get('type') == 'auth_invalid':
                raise HomeAssistantError(f"HA 認証失敗: {msg.get('message')}")
            if msg.get('type') != 'auth_ok':
                raise HomeAssistantError(f"想定外の認証応答: {msg}")
            ws.send(json.dumps({
                'id': 1,
                'start_time': start.isoformat(),
                'end_time': end.isoformat(),
                **payload,
            }))
            msg = json.loads(ws.recv())
            if msg.get('type') != 'result' or msg.get('id') != 1:
                raise HomeAssistantError(f"想定外の応答: {msg}")
            if not msg.get('success'):
                raise HomeAssistantError(f"HA がエラーを返した: {msg.get('error')}")
            return msg.get('result') or {}
        finally:
            ws.close()
