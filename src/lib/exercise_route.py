"""
運動の GPS 軌跡（TCX）。正本は data/googlehealth/tcx/<開始日>_<exercise id>.tcx

軌跡があるのは exercise.csv の has_gps=True の行（Fitbit の自転車モードなど手動開始）だけ。
自動検出（PASSIVELY_MEASURED）には位置が無いので取りに行かない。
TCX は記録が確定した後は変わらない前提で、ファイルがあれば取り直さない。
"""

import time
from pathlib import Path

import pandas as pd
import requests

from lib.clients import googlehealth_client as api

RETRY_STATUSES = (429, 500, 502, 503, 504)
MAX_RETRIES = 3
RETRY_WAIT_SEC = 5


def tcx_name(exercise_id: str, start: str) -> str:
    """ファイル名。Dawarich の import 名にもそのまま使い、二重投入の判定キーにする"""
    return f'{start[:10]}_{exercise_id}.tcx'


def pending(exercise_csv: Path, tcx_dir: Path) -> list[tuple[str, str]]:
    """軌跡を持つのに TCX がまだ無い運動の (id, ファイル名)。開始時刻の昇順"""
    df = pd.read_csv(exercise_csv, dtype=str, keep_default_na=False)
    gps = df[df['has_gps'] == 'True'].sort_values('start')
    have = {p.name for p in tcx_dir.glob('*.tcx')} if tcx_dir.exists() else set()
    return [(row.id, name) for row in gps.itertuples()
            if (name := tcx_name(row.id, row.start)) not in have]


def export_tcx(creds, exercise_id: str) -> str:
    path = f'{api.USER}/dataTypes/exercise/dataPoints/{exercise_id}:exportExerciseTcx'
    for attempt in range(MAX_RETRIES + 1):
        r = requests.get(f'{api.API_BASE}/{path}', params={'alt': 'media'},
                         headers={'Authorization': f'Bearer {creds.token}'}, timeout=120)
        if r.status_code == 200:
            return r.text
        if r.status_code not in RETRY_STATUSES or attempt == MAX_RETRIES:
            raise api.GoogleHealthError(f'GET {path} -> HTTP {r.status_code}: {r.text[:300]}')
        time.sleep(RETRY_WAIT_SEC * (attempt + 1))
