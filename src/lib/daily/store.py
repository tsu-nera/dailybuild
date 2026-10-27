"""
日次記録 CSV の置き場（朝・夜）

朝は data/daily_morning.csv、夜は data/daily_evening.csv（どちらも
dailybuild-private への symlink）。1つの CSV にマージしない理由・スキーマの
差（夜に source が無い、satisfaction/achievement に _score 接尾辞が無い）は
docs/forms.md。

スキーマの正本は config/daily_{morning,evening}_def.yaml の questions
（Issue #167）。列名・型・グリッド行・表示ラベル・日付境界（day_start_hour）・
source 列の有無はすべて yaml にあり、lib.forms.schema が導出する。朝・夜は
固有処理を持たないフォームと同じ経路（scripts/forms.py）でも fetch / show できる。
ここが持つのはファイルの置き場だけ。
"""

from pathlib import Path

import pandas as pd

from lib.forms import defs, schema
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

DEF_FILES = {
    'morning': BASE_DIR / 'config' / 'daily_morning_def.yaml',
    'evening': BASE_DIR / 'config' / 'daily_evening_def.yaml',
}

SLOTS = {
    'morning': {
        'csv_file': require_private_path(BASE_DIR / 'data' / 'daily_morning.csv'),
        'grid_history_file': require_private_path(
            BASE_DIR / 'data' / 'daily_morning_grid_history.csv'),
    },
    'evening': {
        'csv_file': require_private_path(BASE_DIR / 'data' / 'daily_evening.csv'),
        'grid_history_file': require_private_path(
            BASE_DIR / 'data' / 'daily_evening_grid_history.csv'),
    },
}


def load_def(slot: str) -> dict:
    """config/daily_{slot}_def.yaml を読む（スキーマの唯一の正本）"""
    return defs.load_def(DEF_FILES[slot])


def load_entries(slot: str) -> pd.DataFrame:
    """slot（'morning'/'evening'）の記録を date 昇順で読む（schema.load_entries）"""
    return schema.load_entries(SLOTS[slot]['csv_file'], load_def(slot))
