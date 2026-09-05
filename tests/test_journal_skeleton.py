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


def _index_weeks(path):
    import re
    return re.findall(r'\[(\d{4}-W\d{2})\]', path.read_text(encoding='utf-8'))


def test_index_stays_newest_first_when_backfilling(journal_dir):
    """遡り生成では古い週を後から足す。常に先頭へ入れると順序が壊れる"""
    index = journal_dir / 'JOURNAL.md'
    index.write_text(
        '# Health Journal Index\n\n'
        '| 期間 | ファイル | 要約 |\n|---|---|---|\n'
        '| 08/03-08/09 | [2026-W32](2026-W32.md) | 既存の要約 |\n',
        encoding='utf-8')

    # 当週を足したあとに、間の2週を古い順で埋める（--since の処理順）
    js.ensure_index_row(dt.date(2026, 8, 29))   # W35
    js.ensure_index_row(dt.date(2026, 8, 10))   # W33
    js.ensure_index_row(dt.date(2026, 8, 17))   # W34

    assert _index_weeks(index) == ['2026-W35', '2026-W34', '2026-W33', '2026-W32']
    assert '既存の要約' in index.read_text(encoding='utf-8')


def test_index_does_not_disturb_monthly_table(journal_dir):
    """月ファイルの行は別表。週の追加で巻き込まない"""
    index = journal_dir / 'JOURNAL.md'
    index.write_text(
        '| 期間 | ファイル | 要約 |\n|---|---|---|\n'
        '| 08/03-08/09 | [2026-W32](2026-W32.md) | 週 |\n'
        '\n## 月次\n\n| 月 | ファイル | 要約 |\n|---|---|---|\n'
        '| 2026-04 | [2026-04](2026-04.md) | 月 |\n',
        encoding='utf-8')

    js.ensure_index_row(dt.date(2026, 8, 29))

    text = index.read_text(encoding='utf-8')
    assert _index_weeks(index) == ['2026-W35', '2026-W32']
    assert text.index('[2026-W32]') < text.index('## 月次') < text.index('[2026-04]')


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """CSV の読み先を一時ディレクトリへ向ける"""
    monkeypatch.setattr(js, 'BASE_DIR', tmp_path)
    (tmp_path / 'd').mkdir()
    return tmp_path


def _write(root, name, rows):
    (root / 'd' / name).write_text('date,v\n' + ''.join(f'{d},1\n' for d in rows),
                                   encoding='utf-8')


def test_sparse_source_absence_is_not_reported_as_missing(data_root, monkeypatch):
    """疎な指標は当日に記録が無くても欠測として出さない

    毎日「欠測」と書くと故障と未記録が同じ見た目になり、毎日出る警告は
    読み飛ばされる。実際 temperature_core がこれで、測らなかった日すべてに
    警告が出ていた。
    """
    _write(data_root, 'daily.csv', ['2026-08-29'])
    _write(data_root, 'sparse.csv', ['2026-08-23'])
    monkeypatch.setattr(js, 'DAILY_SOURCES', [('daily', 'd/daily.csv', 'date')])
    monkeypatch.setattr(js, 'SPARSE_SOURCES',
                        [('sparse', 'd/sparse.csv', 'date', '疎な指標')])

    target = dt.date(2026, 8, 29)
    assert js.collect_missing(target) == []
    assert js.collect_last_seen(target) == ['疎な指標 6日前（08-23）']


def test_daily_source_absence_is_still_reported(data_root, monkeypatch):
    """毎日あるはずのソースが欠けたら従来どおり欠測として出す"""
    _write(data_root, 'daily.csv', ['2026-08-28'])
    monkeypatch.setattr(js, 'DAILY_SOURCES', [('daily', 'd/daily.csv', 'date')])
    monkeypatch.setattr(js, 'SPARSE_SOURCES', [])

    assert js.collect_missing(dt.date(2026, 8, 29)) == ['daily']


def test_sparse_source_never_recorded(data_root, monkeypatch):
    """一度も記録が無い疎な指標は「記録なし」と出す（0日前と誤読させない）"""
    _write(data_root, 'sparse.csv', [])
    monkeypatch.setattr(js, 'DAILY_SOURCES', [])
    monkeypatch.setattr(js, 'SPARSE_SOURCES',
                        [('sparse', 'd/sparse.csv', 'date', '疎な指標')])

    assert js.collect_last_seen(dt.date(2026, 8, 29)) == ['疎な指標 記録なし']


# --- 排便（Bristol） ---

def _write_bowel(root, rows):
    """rows: (timestamp, bristol) のリスト。bristol は None で未回答"""
    (root / 'data').mkdir(exist_ok=True)
    body = ''.join(f"{ts},{ts[:10]},{'' if b is None else b}\n" for ts, b in rows)
    (root / 'data' / 'bowel.csv').write_text('timestamp,date,bristol\n' + body,
                                             encoding='utf-8')


def test_bowel_absent_csv_is_none(data_root):
    """CSV が無ければ None。骨組みに「排便」の行自体を出さない"""
    assert js.collect_bowel(dt.date(2026, 9, 1)) is None


def test_bowel_counts_and_categories(data_root):
    _write_bowel(data_root, [
        ('2026-09-01 07:12:00', 2),
        ('2026-09-01 19:40:00', 4),
        ('2026-08-30 08:05:00', 7),
        # 窓の外（7日前より古い）。直近7日に混ぜない
        ('2026-08-20 08:00:00', 4),
    ])
    got = js.collect_bowel(dt.date(2026, 9, 1))

    assert got['today'] == [2, 4]
    assert got['week_count'] == 3
    assert got['week_days'] == 2
    assert got['week_categories'] == {'硬い': 1, '正常': 1, 'ゆるい': 1}


def test_bowel_no_record_today_is_not_zero(data_root):
    """当日に記録が無い日を「0回」と書かない

    記録の無い日が未記録なのか出なかったのか判別できない。0 と書くと
    便秘として集計に混ざる（欠測の捏造）。
    """
    _write_bowel(data_root, [('2026-08-30 08:05:00', 4)])
    got = js.collect_bowel(dt.date(2026, 9, 1))

    assert got['today'] == []
    assert got['today_rows'] == 0
    assert '記録なし' in js._fmt_bowel(got)
    assert '0回' not in js._fmt_bowel(got)


def test_bowel_unparseable_type_is_not_dropped_silently(data_root):
    """送信はあったが型が読めない日を「記録なし」にしない"""
    _write_bowel(data_root, [('2026-09-01 07:12:00', None)])
    got = js.collect_bowel(dt.date(2026, 9, 1))

    assert got['today'] == []
    assert got['today_rows'] == 1
    assert '型 不明' in js._fmt_bowel(got)
