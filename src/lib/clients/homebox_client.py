"""Homebox（sysadminsmedia fork 0.27 系）の REST API の薄いクライアント

認証は UI か API で発行した API key（`Authorization: Bearer <key>`）。
0.26 から物と場所は `/api/v1/entities` に統合され、種別は entity-types の isLocation で分かれる。
"""

import requests

from lib.utils.env import require_env


class HomeboxClient:
    def __init__(self, url: str, api_key: str, timeout: float = 30):
        self.base = url.rstrip('/') + '/api/v1'
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Bearer {api_key}'
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> 'HomeboxClient':
        return cls(require_env('HOMEBOX_URL'), require_env('HOMEBOX_API_KEY'))

    def _request(self, method: str, path: str, **kwargs):
        r = self.session.request(method, self.base + path, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else None

    def entity_types(self) -> list[dict]:
        return self._request('GET', '/entity-types')

    def list_entities(self, entity_type_id: str) -> list[dict]:
        """種別1つぶんの summary を全ページ取る（archived も含む）"""
        out, page = [], 1
        while True:
            res = self._request('GET', '/entities', params={
                'entityTypeIds': entity_type_id, 'page': page, 'pageSize': 100,
                'includeArchived': 'true'})
            out.extend(res['items'])
            if len(out) >= res['total'] or not res['items']:
                return out
            page += 1

    def get_entity(self, entity_id: str) -> dict:
        return self._request('GET', f'/entities/{entity_id}')

    def create_entity(self, body: dict) -> dict:
        return self._request('POST', '/entities', json=body)

    def update_entity(self, entity_id: str, body: dict) -> dict:
        return self._request('PUT', f'/entities/{entity_id}', json=body)

    def tags(self) -> list[dict]:
        return self._request('GET', '/tags')

    def create_tag(self, name: str) -> dict:
        return self._request('POST', '/tags', json={'name': name})
