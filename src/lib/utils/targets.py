"""
config/targets.yaml の読み出し

目標値は yaml が単一の真実。以前は FFMI の目標が
`generate_body_report_interval.py` の TARGET_FFMI（21.0）と yaml（19.0）と
各スキルの本文（21.0）に散っており、yaml だけ更新されて他が古いまま残っていた。
レビューは 21.0 を前提に進捗を評価していた。
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
