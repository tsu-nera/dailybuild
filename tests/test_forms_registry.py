"""config/forms.yaml（フォームのレジストリ）のテスト（ADR-002）。

守るのは「入力をやめたフォームの不在を事実として数えない」ことと、
「レジストリの直し漏れ・壊れが黙って fetch を止めない」こと。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

import journal_skeleton as js  # noqa: E402
from lib import forms_registry  # noqa: E402
from lib.forms_registry import RegistryError, load_forms  # noqa: E402

DAILY_FETCH = ROOT / 'scripts' / 'ops' / 'daily-fetch.sh'

# レジストリ導入前（#232）の journal_skeleton.py にあった行。表示を変えないことの基準
PIPELINE_BEFORE = [
    ('Fitbit sleep', 'data/wearable/sleep.csv', 'dateOfSleep', 1, 'active', ''),
    ('Fitbit HRV', 'data/wearable/hrv.csv', 'date', 1, 'active', ''),
    ('Fitbit activity', 'data/wearable/activity.csv', 'date', 1, 'active', ''),
    ('日次記録（朝）', 'data/daily_morning.csv', 'date', 2, 'active', ''),
    ('体組成', 'data/healthplanet_innerscan.csv', 'date', 3, 'active',
     '測らない日があるのが常態'),
    ('排便記録', 'data/bowel.csv', 'date', 4, 'active', '出ない日がある'),
    ('PHQ-9', 'data/phq9.csv', 'date', 8, 'active', '週次'),
    ('Toggl', 'data/toggl/time_entries.csv', 'start', 2, 'active', ''),
    ('MoneyForward', 'data/mf/収入・支出詳細_{year}.csv', '日付', 4, 'degraded',
     '連携が切れた口座の明細が入らない。**MF の集計は過少**。再認証しない方針'),
    ('Habitica', 'data/habitica/cron_log.csv', 'date', 1, 'active', ''),
]
SPARSE_BEFORE = [
    ('temperature_core', 'data/wearable/temperature_core.csv', 'date_time', '深部体温'),
    ('body_composition', 'data/healthplanet_innerscan.csv', 'date', '体組成'),
    ('bowel', 'data/bowel.csv', 'date', '排便'),
]

ENTRY = {
    'key': 'x', 'name': 'フォームX', 'csv': 'data/x.csv', 'date_column': 'date',
    'status': 'active', 'cadence': 'daily', 'stale_after_days': 2, 'note': '',
    'review': 'daily', 'fetch': ['scripts/x.py', 'fetch'], 'show': ['scripts/x.py', 'show'],
}


def write_registry(tmp_path, entries):
    path = tmp_path / 'forms.yaml'
    path.write_text(yaml.safe_dump({'forms': entries}, allow_unicode=True), encoding='utf-8')
    return path


# --- 改修前後で STATE.md の表が変わらない ---

def test_pipeline_rows_are_unchanged_by_registry():
    # 体組成だけフォームの後ろへ移った（フォームは yaml の順で1か所に入る）。行と値は同じ
    rows = js.pipeline_sources(load_forms())
    assert sorted(rows) == sorted(PIPELINE_BEFORE)
    assert [r[0] for r in rows] == [
        'Fitbit sleep', 'Fitbit HRV', 'Fitbit activity', '日次記録（朝）', '排便記録',
        'PHQ-9', '体組成', 'Toggl', 'MoneyForward', 'Habitica']


def test_sparse_rows_are_unchanged_by_registry():
    assert js.sparse_sources(load_forms()) == SPARSE_BEFORE


# --- deprecated は fetch だけ続ける ---

def test_deprecated_form_is_fetched_but_not_shown(tmp_path):
    entries = [
        dict(ENTRY),
        {**ENTRY, 'key': 'gone', 'name': '止めたフォーム', 'csv': 'data/gone.csv',
         'cadence': 'sparse', 'status': 'deprecated'},
    ]
    forms = load_forms(write_registry(tmp_path, entries))
    names = [r[0] for r in js.pipeline_sources(forms)]
    assert 'フォームX' in names
    assert '止めたフォーム' not in names
    assert 'gone' not in [r[0] for r in js.sparse_sources(forms)]
    assert [f.key for f in forms_registry.review_forms(forms, 'daily')] == ['x']
    assert [f.key for f in forms_registry.fetch_forms(forms)] == ['x', 'gone']


def test_real_registry_keeps_fetching_deprecated_emotion():
    out = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'forms.py'), 'fetch-list'],
                         capture_output=True, text=True, check=True).stdout
    assert 'emotion\t気分記録' in out.splitlines()
    forms = load_forms()
    assert '気分記録' not in [r[0] for r in js.pipeline_sources(forms)]
    assert 'emotion' not in [f.key for f in forms_registry.review_forms(forms, 'daily')]


def test_stale_after_days_null_keeps_form_out_of_pipeline(tmp_path):
    forms = load_forms(write_registry(tmp_path, [{**ENTRY, 'stale_after_days': None}]))
    assert 'フォームX' not in [r[0] for r in js.pipeline_sources(forms)]


# --- 壊れたエントリは読み込み時に落とす ---

@pytest.mark.parametrize('field', forms_registry.REQUIRED)
def test_missing_field_raises(tmp_path, field):
    entry = {k: v for k, v in ENTRY.items() if k != field}
    with pytest.raises(RegistryError, match=field):
        load_forms(write_registry(tmp_path, [entry]))


@pytest.mark.parametrize('field,value', [
    ('status', 'retired'), ('cadence', 'monthly'), ('review', 'monthly'),
    ('stale_after_days', 'two'), ('fetch', []),
])
def test_invalid_value_raises(tmp_path, field, value):
    with pytest.raises(RegistryError, match=field):
        load_forms(write_registry(tmp_path, [{**ENTRY, field: value}]))


@pytest.mark.parametrize('field', ['csv', 'key'])
def test_duplicate_raises(tmp_path, field):
    other = {**ENTRY, 'key': 'y', 'csv': 'data/y.csv', field: ENTRY[field]}
    with pytest.raises(RegistryError, match='重複'):
        load_forms(write_registry(tmp_path, [ENTRY, other]))


def test_review_without_show_raises(tmp_path):
    with pytest.raises(RegistryError, match='show'):
        load_forms(write_registry(tmp_path, [{**ENTRY, 'show': None}]))


# --- daily-fetch.sh はフォームを1つずつ step で回す ---

FAKE_UV = r'''#!/bin/bash
echo "$*" >> "$UV_CALLS"
case "$*" in
  *"forms.py fetch-list"*)
    [ -n "$FAIL_LIST" ] && exit 1
    printf 'a\tフォームA\nb\tフォームB\nc\tフォームC\n' ;;
  *"forms.py fetch b"*) exit 1 ;;
  # stdin を読む fetch があっても後続のフォームが消えないこと
  *"forms.py fetch"*) cat > /dev/null ;;
esac
exit 0
'''


@pytest.fixture
def fetch_env(tmp_path):
    repo = tmp_path / 'repo'
    (repo / 'scripts' / 'ops').mkdir(parents=True)
    shutil.copy(DAILY_FETCH, repo / 'scripts' / 'ops' / 'daily-fetch.sh')
    private = tmp_path / 'private'
    for d in ('data', 'reports', 'config'):
        (private / d).mkdir(parents=True)
    (repo / 'config').mkdir()
    (repo / 'data').symlink_to(private / 'data')
    (repo / 'reports').symlink_to(private / 'reports')
    (repo / 'config' / 'private').symlink_to(private / 'config')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'uv').write_text(FAKE_UV)
    (bin_dir / 'uv').chmod(0o755)
    calls = tmp_path / 'calls.log'
    env = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'UV_CALLS': str(calls)}
    return repo, env, calls


def run_fetch(repo, env):
    return subprocess.run(['bash', str(repo / 'scripts' / 'ops' / 'daily-fetch.sh')],
                          env=env, capture_output=True, text=True)


def test_daily_fetch_runs_each_form_as_its_own_step(fetch_env):
    repo, env, calls = fetch_env
    r = run_fetch(repo, env)
    assert r.returncode == 1
    for name in ('フォームA', 'フォームB', 'フォームC'):
        assert f'>>> {name}' in r.stdout
    assert '=== 失敗した取得: フォームB ===' in r.stdout
    log = calls.read_text()
    assert 'forms.py fetch a' in log and 'forms.py fetch c' in log
    assert '>>> ジャーナル骨組み' in r.stdout


def test_daily_fetch_reports_unreadable_registry_and_continues(fetch_env):
    repo, env, calls = fetch_env
    r = run_fetch(repo, {**env, 'FAIL_LIST': '1'})
    assert r.returncode == 1
    assert '=== 失敗した取得: フォームのレジストリ ===' in r.stdout
    assert '>>> Toggl' in r.stdout
    assert 'forms.py fetch ' not in calls.read_text().replace('fetch-list', '')
