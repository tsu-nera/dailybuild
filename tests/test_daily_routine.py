"""daily-routine.sh の失敗モードを守るテスト（ADR-002）。

守るのは「取得したデータを失わない・他の書き手を上書きしない」の2点。
実 private や vaio には触れず、bare repo を remote にした一時 clone で回す。
"""
import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'ops' / 'daily-routine.sh'

pytestmark = pytest.mark.skipif(shutil.which('flock') is None, reason='flock が無い')


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def clone(remote, dest):
    subprocess.run(['git', 'clone', '-q', str(remote), str(dest)], check=True, capture_output=True)
    git(dest, 'config', 'user.name', 'test')
    git(dest, 'config', 'user.email', 'test@example.com')
    return dest


@pytest.fixture
def env(tmp_path):
    remote = tmp_path / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', str(remote)], check=True)
    seed = clone(remote, tmp_path / 'seed')
    (seed / 'data.csv').write_text('base\n')
    git(seed, 'add', '-A')
    git(seed, 'commit', '-q', '-m', 'init')
    git(seed, 'push', '-q', 'origin', 'HEAD:main')
    private = clone(remote, tmp_path / 'private')
    marker = tmp_path / 'ran'
    return remote, private, marker, tmp_path


def run(private, tmp_path, marker, body):
    stub = tmp_path / 'stub.sh'
    stub.write_text(f'#!/bin/bash\ntouch {marker}\ncd {private}\n{body}\n')
    stub.chmod(0o755)
    e = {**os.environ, 'DAILYBUILD_PRIVATE': str(private), 'DAILYBUILD_FETCH': str(stub)}
    return subprocess.run(['bash', str(SCRIPT)], env=e, capture_output=True, text=True)


def test_routine失敗でもcommitとpushを行い終了コードを保つ(env):
    remote, private, marker, tmp = env
    r = run(private, tmp, marker,
            'echo fetched > data.csv\necho "=== 失敗した取得: toggl mf ==="\nexit 1')
    assert r.returncode == 1
    assert git(remote, 'show', 'main:data.csv') == 'fetched'
    assert '(failed: toggl mf)' in git(remote, 'log', '-1', '--format=%s', 'main')


def test_差分が無ければcommitしない(env):
    remote, private, marker, tmp = env
    r = run(private, tmp, marker, 'true')
    assert r.returncode == 0
    assert git(remote, 'rev-list', '--count', 'main') == '1'


def test_lock保持中は実行せず75で終わる(env):
    remote, private, marker, tmp = env
    with open(private / '.git' / 'dailybuild-routine.lock', 'w') as f:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = run(private, tmp, marker, 'echo x > data.csv')
    assert r.returncode == 75
    assert not marker.exists()


def test_rebase衝突では強制pushせずabortする(env):
    remote, private, marker, tmp = env
    other = clone(remote, tmp / 'other')
    (other / 'data.csv').write_text('theirs\n')
    git(other, 'commit', '-q', '-am', 'other')
    other_head = git(other, 'rev-parse', 'HEAD')
    # routine の実行中に他の clone が先に push した状況を作る（pull 後・push 前）
    r = run(private, tmp, marker,
            f'echo mine > data.csv\ngit -C {other} push -q origin HEAD:main')
    assert r.returncode != 0
    assert git(remote, 'rev-parse', 'main') == other_head
    gitdir = private / '.git'
    assert not (gitdir / 'rebase-merge').exists()
    assert not (gitdir / 'rebase-apply').exists()


def test_衝突が残ったままの次回も取得してローカルにcommitする(env):
    remote, private, marker, tmp = env
    other = clone(remote, tmp / 'other')
    (other / 'data.csv').write_text('theirs\n')
    git(other, 'commit', '-q', '-am', 'other')
    git(other, 'push', '-q', 'origin', 'HEAD:main')
    # 前回の衝突で push できなかった commit が残っている状態
    (private / 'data.csv').write_text('mine\n')
    git(private, 'commit', '-q', '-am', 'stuck')
    r = run(private, tmp, marker, 'echo fetched > new.csv')
    assert r.returncode != 0
    assert marker.exists()
    assert (private / 'new.csv').exists()
    assert git(private, 'status', '--porcelain') == ''
    gitdir = private / '.git'
    assert not (gitdir / 'rebase-merge').exists()
    assert not (gitdir / 'rebase-apply').exists()
