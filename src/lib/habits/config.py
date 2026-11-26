"""習慣の設定と日次表の読み込み（habits.py と dashboard.py で共有）

- config/habits.yaml: 対象のクライアント名（good / bad）
- config/private/habits.yaml: 良い習慣の target_per_week（習慣名を含むので private）
- reports/habits_daily.csv: habits.py build が全上書きで作る日次表
"""

from pathlib import Path

import pandas as pd
import yaml

from lib.habits.daily import HABITS_DAILY_COLUMNS
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
HABITS_DAILY_CSV = BASE_DIR / 'reports' / 'habits_daily.csv'
CLIENTS_YAML = BASE_DIR / 'config' / 'habits.yaml'
# 習慣名そのものが非公開なので private 側に置く（dailybuild は public）
ROSTER_YAML = BASE_DIR / 'config' / 'private' / 'habits.yaml'


def load_clients(path: Path = CLIENTS_YAML) -> dict:
    """{'good': <クライアント名>, 'bad': <クライアント名>}"""
    clients = (yaml.safe_load(path.read_text()) or {}).get('clients') or {}
    missing = [k for k in ('good', 'bad') if not clients.get(k)]
    if missing:
        raise ValueError(f'{path} の clients に {"/".join(missing)} がありません')
    return clients


def load_roster(path: Path = ROSTER_YAML) -> dict:
    """良い習慣のプロジェクト名 → {target_per_week}。**無ければ落とす**

    空で続けると全習慣が目標なしになり、ずれとしてしか気づけない。
    """
    path = require_private_path(path)
    if not path.exists():
        raise FileNotFoundError(f'習慣の設定がありません: {path}\n'
                                'dailybuild-private の config/habits.yaml を確認してください。')
    roster = (yaml.safe_load(path.read_text()) or {}).get('habits') or {}
    return {name: (spec or {}) for name, spec in roster.items()}


def load_daily(path: Path = HABITS_DAILY_CSV) -> pd.DataFrame:
    """habits_daily.csv。無ければ空（行が無い = 観測していない）"""
    path = require_private_path(path)
    if not path.exists():
        return pd.DataFrame(columns=HABITS_DAILY_COLUMNS)
    return pd.read_csv(path, dtype={'date': str, 'habit': str})
