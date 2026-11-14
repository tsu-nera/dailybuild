"""
dashboard.py のテスト

画面と画面用 CSV（reports/dashboard/）の計算はテストしない（CLAUDE.md「テスト方針」）。
ここに残すのは、STATE.md と共有する鮮度の許容日数、symlink 未マウント時の書き込み、
全画面 JSON の静的検査だけ。
"""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import dashboard
import journal_skeleton as js
from lib.utils import private_data


def test_collect_pipeline_は許容日数を返す():
    assert all('tolerance' in r for r in js.collect_pipeline(dt.date(2026, 11, 7)))


def test_未マウントの_reports_へは書かずに落ちる(tmp_path, monkeypatch):
    repo = tmp_path / 'dailybuild'
    (repo / 'reports').mkdir(parents=True)
    monkeypatch.setattr(private_data, 'REPO_ROOT', repo)
    target = repo / 'reports' / 'dashboard'
    with pytest.raises(FileNotFoundError):
        dashboard.write_csvs({'status': []}, target)
    assert not target.exists()


def test_grafana_画面ごとの_json_は全クエリに_url_options_を持つ():
    """url_options が無いと画面側の Infinity が落ちて全パネルが空になる（API だけでは見つからない）"""
    paths = sorted((Path(__file__).parent.parent / 'scripts/ops/grafana/dashboards').glob('*/*.json'))
    assert {p.stem for p in paths} >= {'goals', 'body', 'sleep', 'mind', 'consumables', 'assets'}
    for path in paths:
        d = json.loads(path.read_text(encoding='utf-8'))
        uid = path.stem
        assert d['uid'] == uid
        # フォルダはディレクトリ名、行き来はジャンルのタグ（docs/grafana.md）
        assert path.parent.name in d['tags'], uid
        for t in d.get('templating', {}).get('list', []):
            if 'infinityQuery' in t.get('query', {}):
                assert t['query']['infinityQuery']['url_options'] == {'method': 'GET'}, (uid, t['name'])
        for p in d['panels']:
            for t in p.get('targets', []):
                assert t['url_options'] == {'method': 'GET'}, (uid, p['title'])
