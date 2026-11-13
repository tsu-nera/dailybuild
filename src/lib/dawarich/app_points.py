"""
スマホの Dawarich アプリが送った点の写し（data/dawarich/app_points.csv）

Dawarich の DB にしか無い点なので、既存の行は消さない（DB を作り直して点が消えても写しは残す）。
座標は文字列のまま比べる（float を経由すると同じ点が別の行になる）。
"""

from pathlib import Path

import pandas as pd

from lib.utils.csv_utils import merge_csv_by_columns

KEYS = ['timestamp', 'latitude', 'longitude']


def merge(rows: list[dict], path: Path) -> pd.DataFrame:
    return merge_csv_by_columns(pd.DataFrame(rows, dtype=str), path, KEYS, sort_by=['timestamp'],
                                read_csv_kwargs={'dtype': str})
