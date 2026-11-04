"""
config/targets.yaml の読み出し

目標値は yaml が単一の真実。FFMI の目標は gtd（~/repo/gtd/goals/strength.md）に
移したので、ここには無い。
"""

from pathlib import Path

import yaml

TARGETS_YAML = Path(__file__).resolve().parents[3] / 'config' / 'targets.yaml'


def load_targets() -> list[dict]:
    """targets.yaml の targets を返す。無ければ空リスト"""
    if not TARGETS_YAML.exists():
        return []
    with TARGETS_YAML.open() as f:
        data = yaml.safe_load(f) or {}
    return data.get('targets', []) or []


def get_target(key: str, default=None):
    """key の目標値を返す。宣言が無ければ default

    default を返した場合、その値は yaml に由来しない。呼び出し側が
    「宣言されていない」と分かる形で扱うこと。
    """
    for target in load_targets():
        if target.get('key') == key:
            return target.get('target', default)
    return default
