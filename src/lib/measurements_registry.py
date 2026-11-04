"""
config/measurements.yaml（手入力で疎に測る指標のレジストリ）の読み込みと検証

「何日おきに・どんなときに測るか」をレビュー手順の文章に指標ごとに書くと、
指標が増えるたびに手順が伸び、定義も二か所に分かれる。宣言はこの yaml に寄せ、
遅れの判定は journal_skeleton.py が STATE.md に出す。

検証は forms_registry と同じく読み込み時に全件行い、1件でも壊れていれば例外にする。
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from lib.forms_registry import RegistryError

MEASUREMENTS_YAML = Path(__file__).resolve().parents[2] / 'config' / 'measurements.yaml'

REQUIRED = ('key', 'name', 'csv', 'date_column', 'expect_every_days', 'when')


@dataclass(frozen=True)
class Measurement:
    key: str
    name: str
    csv: str
    date_column: str
    expect_every_days: int | None = None
    when: str = ''


def _parse(entry, index) -> Measurement:
    where = f'measurements[{index}]'
    if not isinstance(entry, dict):
        raise RegistryError(f'{where}: マッピングではない')
    where = f"measurements[{index}]（{entry.get('key', '?')}）"
    missing = [f for f in REQUIRED if f not in entry]
    if missing:
        raise RegistryError(f"{where}: 必須項目が無い: {', '.join(missing)}")
    unknown = set(entry) - set(REQUIRED)
    if unknown:
        raise RegistryError(f"{where}: 未知の項目: {', '.join(sorted(unknown))}")
    for field in ('key', 'name', 'csv', 'date_column'):
        if not isinstance(entry[field], str) or not entry[field]:
            raise RegistryError(f'{where}: {field} は空でない文字列')
    every = entry['expect_every_days']
    if every is not None and (isinstance(every, bool) or not isinstance(every, int)
                              or every < 1):
        raise RegistryError(f'{where}: expect_every_days は1以上の整数か null')
    when = entry['when'] or ''
    if not isinstance(when, str):
        raise RegistryError(f'{where}: when は文字列')
    return Measurement(key=entry['key'], name=entry['name'], csv=entry['csv'],
                       date_column=entry['date_column'], expect_every_days=every,
                       when=when)


def load_measurements(path: Path = MEASUREMENTS_YAML) -> list[Measurement]:
    """レジストリを yaml の順に返す。壊れたエントリがあれば RegistryError"""
    with Path(path).open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    entries = data.get('measurements') if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise RegistryError(f'{path}: measurements のリストが無い')
    items = [_parse(e, i) for i, e in enumerate(entries)]
    seen = set()
    for item in items:
        if item.key in seen:
            raise RegistryError(f'key が重複している: {item.key}')
        seen.add(item.key)
    return items
