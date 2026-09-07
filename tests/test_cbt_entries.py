"""認知再構成エントリーの frontmatter が集計可能な状態を保っているか。

集計は frontmatter だけを読むので、欄の書き忘れ・語彙外の値は
例外を出さずに「その回は無かったこと」になる。落とすのはそこだけ。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))


def _load_cbt():
    """symlink 未マウントなら skip（0件で無風に通るのを防ぐ）。"""
    spec = importlib.util.spec_from_file_location('cbt', BASE_DIR / 'scripts' / 'cbt.py')
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # private データ未マウント
        pytest.skip(f'reports/ が未マウント: {exc}')
    return module


@pytest.fixture(scope='module')
def cbt():
    return _load_cbt()


@pytest.fixture(scope='module')
def entries(cbt):
    entries = cbt.load_entries()
    assert entries, 'エントリーが0件。glob が空振りしている'
    return entries


def test_frontmatter_has_required_fields(entries):
    required = {'date', 'mode', 'summary', 'emotions', 'distortions'}
    for path, fm in entries:
        missing = required - set(fm)
        assert not missing, f'{path.name}: 欄が無い {missing}'


def test_distortions_are_burns_ten(cbt, entries):
    for path, fm in entries:
        for d in fm['distortions']:
            assert d in cbt.DISTORTIONS, f'{path.name}: 語彙外の歪み名 {d!r}'


def test_intensities_are_null_not_zero(entries):
    """取らなかった強度を 0 で埋めると平均に混ざる。null で残っていること。"""
    for path, fm in entries:
        for e in fm['emotions']:
            for k in ('before', 'after'):
                assert e.get(k) != 0, f'{path.name}: {e["label"]}.{k} が 0（欠測なら null）'


def test_belief_is_text_not_label(entries):
    """B番号を焼き付けると、ラベル付け替え時に不変のエントリーを書き換える羽目になる。"""
    for path, fm in entries:
        belief = fm.get('belief_text')
        if belief:
            assert not belief.startswith('B'), f'{path.name}: belief_text がラベル {belief!r}'


@pytest.mark.parametrize('name,builder', [
    ('INDEX.md', 'build_index'),
    ('entries.jsonl', 'build_jsonl'),
])
def test_generated_artifacts_are_up_to_date(cbt, entries, name, builder):
    """どちらも生成物。手で追記せず再生成されていること。"""
    current = (cbt.ENTRY_DIR / name).read_text(encoding='utf-8')
    assert current == getattr(cbt, builder)(entries), (
        f'{name} が古い。`uv run scripts/cbt.py index` を実行すること'
    )
