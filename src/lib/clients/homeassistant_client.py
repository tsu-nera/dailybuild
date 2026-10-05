"""Home Assistant WebSocket API クライアント（statistics 取得のみ）

認証情報は config/homeassistant_creds.json（url は省略可）。
"""

import json
from datetime import datetime
from pathlib import Path

DEFAULT_URL = 'http://localhost:8123'
CREDS_FILE = Path(__file__).parent.parent.parent.parent / 'config' / 'homeassistant_creds.json'


class HomeAssistantError(Exception):
    pass


def load_settings(path: Path = CREDS_FILE) -> tuple[str, str]:
    """(url, token) を返す。config/homeassistant_creds.json から読む"""
    guide = (
        "HA のプロフィール → セキュリティ → 長期アクセストークンを dailybuild 用に発行し、"
        f"{path.name} に置く（{path.name}.sample を参照）"
    )
    if not path.exists():
        raise HomeAssistantError(f"認証情報がありません: {path}\n  {guide}")
    creds = json.loads(path.read_text(encoding='utf-8'))
    if not creds.get('token'):
        raise HomeAssistantError(f"{path} に token がありません。{guide}")
    return creds.get('url') or DEFAULT_URL, creds['token']


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
                'type': 'recorder/statistics_during_period',
                'start_time': start.isoformat(),
                'end_time': end.isoformat(),
                'statistic_ids': list(statistic_ids),
                'period': period,
                'types': list(types),
            }))
            msg = json.loads(ws.recv())
            if msg.get('type') != 'result' or msg.get('id') != 1:
                raise HomeAssistantError(f"想定外の応答: {msg}")
            if not msg.get('success'):
                raise HomeAssistantError(f"HA がエラーを返した: {msg.get('error')}")
            return msg.get('result') or {}
        finally:
            ws.close()
