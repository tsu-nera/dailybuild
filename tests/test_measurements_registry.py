"""config/measurements.yaml（手入力で疎に測る指標のレジストリ）のテスト（ADR-002）。

壊れたエントリを黙って飛ばすと、その指標が STATE.md から消えても誰も気づかない。
"""
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from lib.forms_registry import RegistryError  # noqa: E402
from lib.measurements_registry import load_measurements  # noqa: E402

ENTRY = {'key': 'x', 'name': '指標X', 'csv': 'data/x.csv', 'date_column': 'date',
         'expect_every_days': 7, 'when': '気になる日'}


def write_registry(tmp_path, entries):
    path = tmp_path / 'measurements.yaml'
    path.write_text(yaml.safe_dump({'measurements': entries}, allow_unicode=True),
                    encoding='utf-8')
    return path


def test_repository_registry_loads():
    items = {m.key: m for m in load_measurements()}
    assert items['temperature_core'].expect_every_days == 7
    assert items['blood_pressure'].expect_every_days == 7
    assert items['body_composition'].expect_every_days is None


def test_loads_entry(tmp_path):
    [m] = load_measurements(write_registry(tmp_path, [ENTRY]))
    assert (m.key, m.name, m.csv, m.date_column, m.expect_every_days, m.when) == (
        'x', '指標X', 'data/x.csv', 'date', 7, '気になる日')


def test_null_interval_and_empty_when(tmp_path):
    [m] = load_measurements(write_registry(
        tmp_path, [{**ENTRY, 'expect_every_days': None, 'when': None}]))
    assert m.expect_every_days is None
    assert m.when == ''


@pytest.mark.parametrize('field', list(ENTRY))
def test_missing_required_key_raises(tmp_path, field):
    entry = {k: v for k, v in ENTRY.items() if k != field}
    with pytest.raises(RegistryError, match=field):
        load_measurements(write_registry(tmp_path, [entry]))


@pytest.mark.parametrize('value', [0, -1, '7', True, 1.5])
def test_invalid_interval_raises(tmp_path, value):
    with pytest.raises(RegistryError, match='expect_every_days'):
        load_measurements(write_registry(tmp_path, [{**ENTRY, 'expect_every_days': value}]))


def test_unknown_key_raises(tmp_path):
    with pytest.raises(RegistryError, match='未知'):
        load_measurements(write_registry(tmp_path, [{**ENTRY, 'every': 7}]))


def test_duplicate_key_raises(tmp_path):
    with pytest.raises(RegistryError, match='重複'):
        load_measurements(write_registry(tmp_path, [ENTRY, {**ENTRY, 'csv': 'data/y.csv'}]))
