"""
journal_skeleton の冪等性と非破壊性のテスト

骨組みは daily-routine.sh から毎日走る。壊れ方は2つとも「気づけない」種類:

1. 再実行のたびにエントリが増える（同じ日が何度も積み上がる）
2. 人と agent が対話で書いた考察を機械が上書きする

2 は取り返しがつかない。ジャーナルは経過ログで、当時の対話は再生成できない。
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import journal_skeleton as js


@pytest.fixture
def journal_dir(tmp_path, monkeypatch):
    """週ファイルの書き先を一時ディレクトリへ向ける"""
    monkeypatch.setattr(js, 'JOURNAL_DIR', tmp_path)
    monkeypatch.setattr(js, 'INDEX_FILE', tmp_path / 'JOURNAL.md')
    # 骨組みの中身はデータ依存なので固定する（ここでの関心は書き込み制御）
    monkeypatch.setattr(js, 'render_skeleton',
                        lambda target: f'{js.START_MARKER}\nBODY {target}\n{js.END_MARKER}')
    return tmp_path


def test_creates_week_file_and_entry(journal_dir):
    day = dt.date(2026, 8, 29)
    assert js.upsert_entry(day) == 'created'

    path = journal_dir / '2026-W35.md'
    text = path.read_text(encoding='utf-8')
    assert '# 2026-W35 (08/24 - 08/30)' in text
    assert '## 2026-08-29 (土)' in text
    assert 'BODY 2026-08-29' in text


def test_rerun_does_not_duplicate_entry(journal_dir):
    day = dt.date(2026, 8, 29)
    js.upsert_entry(day)
    assert js.upsert_entry(day) == 'unchanged'

    text = (journal_dir / '2026-W35.md').read_text(encoding='utf-8')
    assert text.count('## 2026-08-29') == 1
    assert text.count(js.START_MARKER) == 1


def test_refresh_replaces_only_skeleton_and_keeps_discussion(journal_dir, monkeypatch):
    day = dt.date(2026, 8, 29)
    js.upsert_entry(day)

    path = journal_dir / '2026-W35.md'
    text = path.read_text(encoding='utf-8')
    path.write_text(text.rstrip('\n') + '\n\n**Discussion**: 手で書いた考察\n',
                    encoding='utf-8')

    monkeypatch.setattr(js, 'render_skeleton',
                        lambda target: f'{js.START_MARKER}\nUPDATED\n{js.END_MARKER}')
    assert js.upsert_entry(day) == 'updated'

    text = path.read_text(encoding='utf-8')
    assert 'UPDATED' in text
    assert 'BODY 2026-08-29' not in text
    assert '**Discussion**: 手で書いた考察' in text


def test_never_touches_entry_without_markers(journal_dir):
    """移行前の手書きエントリ（マーカー無し）は書き換えない"""
    path = journal_dir / '2026-W32.md'
    original = (
        '# 2026-W32 (08/03 - 08/09)\n\n'
        '## 2026-08-07 (金)\n\n'
        '**状態**: 注意 — 人が書いた本文\n'
    )
    path.write_text(original, encoding='utf-8')

    assert js.upsert_entry(dt.date(2026, 8, 7)) == 'skipped'
    assert path.read_text(encoding='utf-8') == original


def test_inserts_in_date_order(journal_dir):
    js.upsert_entry(dt.date(2026, 8, 29))
    js.upsert_entry(dt.date(2026, 8, 25))
    js.upsert_entry(dt.date(2026, 8, 27))

    text = (journal_dir / '2026-W35.md').read_text(encoding='utf-8')
    order = [line for line in text.splitlines() if line.startswith('## 2026-')]
    assert order == ['## 2026-08-25 (火)', '## 2026-08-27 (木)', '## 2026-08-29 (土)']


def test_index_row_added_once_and_summary_preserved(journal_dir):
    index = journal_dir / 'JOURNAL.md'
    index.write_text('# Health Journal Index\n\n| 期間 | ファイル | 要約 |\n|---|---|---|\n',
                     encoding='utf-8')

    assert js.ensure_index_row(dt.date(2026, 8, 29)) == 'added'
    assert js.ensure_index_row(dt.date(2026, 8, 29)) == 'exists'

    text = index.read_text(encoding='utf-8')
    assert text.count('[2026-W35]') == 1

    # 要約を書き換えたあとに再実行しても上書きしない
    index.write_text(text.replace('（骨組みのみ・要約未記入）', '週の要約'), encoding='utf-8')
    assert js.ensure_index_row(dt.date(2026, 8, 29)) == 'exists'
    assert '週の要約' in index.read_text(encoding='utf-8')
