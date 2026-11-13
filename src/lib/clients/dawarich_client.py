"""
Dawarich の HTTP API（imports）。URL と API キーは .env の DAWARICH_URL / DAWARICH_API_KEY

同じファイル名で POST すると Dawarich は名前に時刻を足して**別の import として受け付ける**
（generate_unique_import_name）。points は (user, timestamp, lonlat) で一意なので点は増えないが、
import が積み上がるので、上げる前に既存の import 名と突き合わせる。
"""

from pathlib import Path

import requests

PER_PAGE = 100


class DawarichClient:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.headers = {'Authorization': f'Bearer {api_key}'}

    def import_names(self) -> set[str]:
        names, page = set(), 1
        while True:
            r = requests.get(f'{self.url}/api/v1/imports', headers=self.headers,
                             params={'page': page, 'per_page': PER_PAGE}, timeout=60)
            r.raise_for_status()
            names.update(i['name'] for i in r.json())
            if page >= int(r.headers.get('X-Total-Pages', page)):
                return names
            page += 1

    def upload(self, path: Path) -> dict:
        with path.open('rb') as f:
            r = requests.post(f'{self.url}/api/v1/imports', headers=self.headers,
                              files={'file': (path.name, f, 'application/xml')}, timeout=120)
        r.raise_for_status()
        return r.json()


def not_imported(files: list[Path], imported: set[str]) -> list[Path]:
    return [p for p in sorted(files) if p.name not in imported]
