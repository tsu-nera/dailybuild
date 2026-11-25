"""config/longevity.yaml（老化の指標の台帳）と longevity 画面の表のテスト（ADR-002）。

壊れた台帳や typo の column を黙って飛ばすと、指標が「未測定」に見えたまま誰も気づかない。
欠測の月を 0 にしない・重複行を二重に数えない、もここで固める。
"""
import datetime as dt
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))

from lib import longevity  # noqa: E402
from lib.forms_registry import RegistryError  # noqa: E402
from lib.longevity import (  # noqa: E402
    build_catalog, build_labs, build_monthly, load_registry, read_observations)

SRC = {'csv': 'data/x.csv', 'column': 'v', 'date_column': 'date', 'kind': 'daily'}
ENTRY = {'key': 'x', 'name': '指標X', 'section': 1, 'unit': 'kg', 'sources': [SRC]}


def write_registry(tmp_path, entries):
    path = tmp_path / 'longevity.yaml'
    path.write_text(yaml.safe_dump({'metrics': entries}, allow_unicode=True), encoding='utf-8')
    return path


def write_csv(tmp_path, rel, text):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def resolver(tmp_path):
    return lambda rel: tmp_path / rel


def test_repository_registry_loads():
    items = {m.key: m for m in load_registry()}
    for key in ('body_age', 'phenoage', 'dunedinpace', 'vo2max', 'rhr', 'hrv', 'bp_systolic',
                'bp_diastolic', 'ldl', 'hdl', 'tg', 'apob', 'lpa', 'hscrp', 'hba1c',
                'fasting_glucose', 'ga', 'visceral_fat', 'waist', 'fasting_insulin', 'weight',
                'body_fat_rate', 'muscle_quality', 'bone_mass', 'ffmi', 'grip', 'dexa'):
        assert key in items
    for key in ('phenoage', 'apob', 'fasting_insulin', 'grip', 'dexa'):
        assert items[key].sources == ()
    assert len(items['bp_systolic'].sources) == 3


def test_valid_entry_loads(tmp_path):
    [m] = load_registry(write_registry(tmp_path, [ENTRY]))
    assert m.key == 'x' and m.sources[0].kind == 'daily'


def test_duplicate_key_rejected(tmp_path):
    with pytest.raises(RegistryError, match='重複'):
        load_registry(write_registry(tmp_path, [ENTRY, dict(ENTRY)]))


@pytest.mark.parametrize('section', [10, -1, True, '1'])
def test_section_out_of_range_rejected(tmp_path, section):
    with pytest.raises(RegistryError, match='section'):
        load_registry(write_registry(tmp_path, [{**ENTRY, 'section': section}]))


def test_kind_rejected(tmp_path):
    entry = {**ENTRY, 'sources': [{**SRC, 'kind': 'weekly'}]}
    with pytest.raises(RegistryError, match='kind'):
        load_registry(write_registry(tmp_path, [entry]))


@pytest.mark.parametrize('field', ['key', 'name', 'section', 'unit', 'sources'])
def test_missing_metric_field_rejected(tmp_path, field):
    entry = {k: v for k, v in ENTRY.items() if k != field}
    with pytest.raises(RegistryError, match='必須項目'):
        load_registry(write_registry(tmp_path, [entry]))


@pytest.mark.parametrize('field', ['csv', 'column', 'date_column', 'kind'])
def test_missing_source_field_rejected(tmp_path, field):
    entry = {**ENTRY, 'sources': [{k: v for k, v in SRC.items() if k != field}]}
    with pytest.raises(RegistryError, match='必須項目'):
        load_registry(write_registry(tmp_path, [entry]))


def test_unknown_field_rejected(tmp_path):
    with pytest.raises(RegistryError, match='未知'):
        load_registry(write_registry(tmp_path, [{**ENTRY, 'extra': 1}]))


def test_catalog_unmeasured_metric_has_empty_cells(tmp_path):
    write_csv(tmp_path, 'data/x.csv', 'date,v\n2026-01-05,1\n2026-02-05,3\n')
    metrics = load_registry(write_registry(
        tmp_path, [{**ENTRY, 'section': 2}, {**ENTRY, 'key': 'y', 'section': 0, 'sources': []}]))
    rows = build_catalog(metrics, read_observations(metrics, resolver(tmp_path)))
    assert [r['key'] for r in rows] == ['y', 'x']  # 区画順
    assert rows[0]['last_date'] is None and rows[0]['count'] is None
    assert rows[1]['last_date'] == '2026-02-05' and rows[1]['count'] == 2


def test_monthly_gap_month_is_none_not_zero(tmp_path):
    write_csv(tmp_path, 'data/x.csv',
              'date,v\n2026-01-05,1\n2026-01-20,3\n2026-03-10,5\n')
    metrics = load_registry(write_registry(tmp_path, [ENTRY]))
    obs = read_observations(metrics, resolver(tmp_path))
    rows = build_monthly(metrics, obs, dt.date(2026, 4, 15))
    assert [r['month'] for r in rows] == ['2026-01-01', '2026-02-01', '2026-03-01', '2026-04-01']
    assert [r['x'] for r in rows] == [2.0, None, 5.0, None]


def test_monthly_skips_point_sources(tmp_path):
    write_csv(tmp_path, 'data/x.csv', 'date,v\n2026-01-05,1\n')
    metrics = load_registry(write_registry(
        tmp_path, [{**ENTRY, 'sources': [{**SRC, 'kind': 'point'}]}]))
    assert longevity.monthly_keys(metrics) == []
    obs = read_observations(metrics, resolver(tmp_path))
    assert build_monthly(metrics, obs, dt.date(2026, 2, 1)) == []


def test_labs_duplicate_rows_collapse(tmp_path):
    write_csv(tmp_path, 'data/x.csv', 'date,v\n2026-01-05,1\n2026-01-05,1\n2026-02-05,2\n')
    write_csv(tmp_path, 'data/z.csv', 'date,v\n2026-01-05,9\n')
    point = {**SRC, 'kind': 'point'}
    metrics = load_registry(write_registry(tmp_path, [
        {**ENTRY, 'sources': [point, {**point, 'csv': 'data/z.csv'}]}]))
    obs = read_observations(metrics, resolver(tmp_path))
    rows = build_labs(metrics, obs)
    assert [(r['date'], r['value'], r['source']) for r in rows] == [
        ('2026-01-05', 1.0, 'x'), ('2026-01-05', 9.0, 'z'), ('2026-02-05', 2.0, 'x')]
    assert build_catalog(metrics, obs)[0]['count'] == 3  # 件数も重複を除いた数


def test_missing_column_raises(tmp_path):
    write_csv(tmp_path, 'data/x.csv', 'date,w\n2026-01-05,1\n')
    metrics = load_registry(write_registry(tmp_path, [ENTRY]))
    with pytest.raises(RegistryError, match="'v'"):
        read_observations(metrics, resolver(tmp_path))


def test_missing_date_column_raises(tmp_path):
    write_csv(tmp_path, 'data/x.csv', 'day,v\n2026-01-05,1\n')
    metrics = load_registry(write_registry(tmp_path, [ENTRY]))
    with pytest.raises(RegistryError, match="'date'"):
        read_observations(metrics, resolver(tmp_path))


def test_non_numeric_values_are_dropped(tmp_path):
    write_csv(tmp_path, 'data/x.csv', 'date,v\n2026-01-05,\n2026-01-06,abc\n2026-01-07,4\n')
    metrics = load_registry(write_registry(tmp_path, [ENTRY]))
    obs = read_observations(metrics, resolver(tmp_path))
    assert [(o.date, o.value) for o in obs['x']] == [(dt.date(2026, 1, 7), 4.0)]


def test_ffmi_computed_for_innerscan(tmp_path):
    write_csv(tmp_path, 'data/healthplanet_innerscan.csv',
              'date,weight,body_fat_mass\n2026-01-05,70,10\n')
    src = {'csv': 'data/healthplanet_innerscan.csv', 'column': 'ffmi',
           'date_column': 'date', 'kind': 'daily'}
    metrics = load_registry(write_registry(tmp_path, [{**ENTRY, 'key': 'ffmi', 'sources': [src]}]))
    obs = read_observations(metrics, resolver(tmp_path))
    # LBM 60kg・身長170cm: 60 / 1.7^2 + 6.1 * (1.8 - 1.7)
    assert obs['ffmi'][0].value == pytest.approx(60 / 1.7 ** 2 + 0.61)
