"""Notion 公式 REST API の薄いクライアント（data source の query とページのプロパティ更新だけ）

認証は internal integration の token（`Authorization: Bearer <token>`）。integration を DB に接続しないと
query は 404 を返す。data source の API は Notion-Version 2025-09-03 から。
"""

import requests

NOTION_API = 'https://api.notion.com/v1'
NOTION_VERSION = '2025-09-03'


class NotionClient:
    def __init__(self, token: str, timeout: float = 30):
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'Notion-Version': NOTION_VERSION,
            'Content-Type': 'application/json',
        })
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> dict:
        r = self.session.request(method, NOTION_API + path, timeout=self.timeout, **kwargs)
        r.raise_for_status()
        return r.json()

    def query_data_source(self, data_source_id: str) -> list[dict]:
        """data source の全ページを返す。has_more が立つ限りページ送りを続ける"""
        pages, cursor = [], None
        while True:
            body = {'page_size': 100}
            if cursor:
                body['start_cursor'] = cursor
            res = self._request('POST', f'/data_sources/{data_source_id}/query', json=body)
            pages.extend(res['results'])
            if not res.get('has_more'):
                return pages
            cursor = res['next_cursor']

    def set_rich_text(self, page_id: str, prop: str, text: str) -> dict:
        return self._request('PATCH', f'/pages/{page_id}', json={
            'properties': {prop: {'rich_text': [{'type': 'text', 'text': {'content': text}}]}}})
