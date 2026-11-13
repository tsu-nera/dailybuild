"""
Dawarich の HTTP API（imports）。URL と API キーは .env の DAWARICH_URL / DAWARICH_API_KEY

同じファイル名で POST すると Dawarich は名前に時刻を足して**別の import として受け付ける**
（generate_unique_import_name）。points は (user, timestamp, lonlat) で一意なので点は増えないが、
import が積み上がるので、上げる前に既存の import 名と突き合わせる。

点の削除（bulk_destroy）は soft delete ではなく DB から消える（Points::Destroyer の destroy_all）。
トラックの作り直しは Dawarich が削除時に自分で積む。
"""

from pathlib import Path

import requests

PER_PAGE = 100
POINTS_PER_PAGE = 10_000   # PointsController::MAX_PER_PAGE
DESTROY_CHUNK = 5_000      # PointsController::BULK_DESTROY_MAX


class DawarichClient:
    def __init__(self, url: str, api_key: str):
        self.url = url.rstrip('/')
        self.headers = {'Authorization': f'Bearer {api_key}'}

    def _pages(self, path: str, params: dict) -> list[dict]:
        rows, page = [], 1
        while True:
            r = requests.get(f'{self.url}{path}', headers=self.headers,
                             params={**params, 'page': page}, timeout=120)
            r.raise_for_status()
            rows.extend(r.json())
            if page >= int(r.headers.get('X-Total-Pages', page)):
                return rows
            page += 1

    def imports(self) -> list[dict]:
        return self._pages('/api/v1/imports', {'per_page': PER_PAGE})

    def import_names(self) -> set[str]:
        return {i['name'] for i in self.imports()}

    def points(self, start_at: int | None = None, end_at: int | None = None,
               import_id: int | None = None, slim: bool = False) -> list[dict]:
        """異常値の印が付いた点も含めて返す"""
        params = {'per_page': POINTS_PER_PAGE, 'order': 'asc', 'include_anomalies': 'true'}
        if start_at is not None:
            params['start_at'] = str(start_at)
        if end_at is not None:
            params['end_at'] = str(end_at)
        if import_id is not None:
            params['import_id'] = str(import_id)
        if slim:
            params['slim'] = 'true'
        return self._pages('/api/v1/points', params)

    def delete_points(self, ids: list[int]) -> int:
        deleted = 0
        for i in range(0, len(ids), DESTROY_CHUNK):
            r = requests.delete(f'{self.url}/api/v1/points/bulk_destroy', headers=self.headers,
                                json={'point_ids': ids[i:i + DESTROY_CHUNK]}, timeout=300)
            r.raise_for_status()
            deleted += r.json().get('count', 0)
        return deleted

    def upload(self, path: Path) -> dict:
        with path.open('rb') as f:
            r = requests.post(f'{self.url}/api/v1/imports', headers=self.headers,
                              files={'file': (path.name, f, 'application/xml')}, timeout=120)
        r.raise_for_status()
        return r.json()


def not_imported(files: list[Path], imported: set[str]) -> list[Path]:
    return [p for p in sorted(files) if p.name not in imported]


def precise_imports(imports: list[dict], suffixes: tuple[str, ...]) -> list[dict]:
    """時間帯の基準にする import（取り込み済みのもの）。処理中のものは翌日に回す"""
    return [i for i in imports if i['name'].lower().endswith(suffixes) and i['status'] == 'completed']


def overlapping_others(window_points: list[dict], keep_ids: set[int]) -> list[dict]:
    """基準の時間帯にある、消してよい点。keep_ids は全基準 import の点と KEEP_SOURCES の点の id。
    自分以外の基準だけで引くと、時間の重なる2本（Fitbit とサイコン）が互いを消し合う"""
    return [p for p in window_points if p['id'] not in keep_ids]
