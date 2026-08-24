"""非公開データマウントの検証（symlink 未設定で public 側へ書かせない）"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lib.utils import private_data
from lib.utils.private_data import ensure_dir, require_private_write


def _unmounted_repo(tmp_path, monkeypatch):
    """symlink が張られていない dailybuild を模したツリーを作る"""
    repo = tmp_path / 'dailybuild'
    (repo / 'data').mkdir(parents=True)
    monkeypatch.setattr(private_data, 'REPO_ROOT', repo)
    return repo


def test_未マウントの_data_配下への書き込みは落ちる(tmp_path, monkeypatch):
    repo = _unmounted_repo(tmp_path, monkeypatch)
    with pytest.raises(FileNotFoundError):
        require_private_write(repo / 'data' / 'fitbit' / 'sleep.csv')


def test_未マウントなら_ensure_dir_はディレクトリを作らない(tmp_path, monkeypatch):
    repo = _unmounted_repo(tmp_path, monkeypatch)
    target = repo / 'reports' / 'daily'
    with pytest.raises(FileNotFoundError):
        ensure_dir(target)
    assert not target.exists()


def test_private_へ解決されるパスは素通りする(tmp_path, monkeypatch):
    repo = _unmounted_repo(tmp_path, monkeypatch)
    private = tmp_path / 'dailybuild-private' / 'data'
    private.mkdir(parents=True)
    (repo / 'data').rmdir()
    (repo / 'data').symlink_to(private)
    assert require_private_write(repo / 'data' / 'weather.csv')


def test_リポジトリ外のパスは対象外(tmp_path, monkeypatch):
    _unmounted_repo(tmp_path, monkeypatch)
    outside = tmp_path / 'scratch' / 'x.csv'
    assert require_private_write(outside) == outside


def test_data_reports_以外は素通りする(tmp_path, monkeypatch):
    repo = _unmounted_repo(tmp_path, monkeypatch)
    assert require_private_write(repo / 'config' / 'creds.json')
