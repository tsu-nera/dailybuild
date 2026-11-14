"""
Toggl push の satoru_meditation ソース（Muse の瞑想の回 → Toggl「瞑想」）

session_log.csv と focus_entries.csv は tmp に置く。重なり判定は区間で行い、
端が接するだけは重ならない扱い。
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from lib import meditation
from lib.toggl import push as toggl_push
from lib.toggl import sources as toggl_sources
from lib.toggl.push import select_pending

JST = ZoneInfo('Asia/Tokyo')

CONFIG = {'sources': {'satoru_meditation': {
    'enabled': True, 'project': '瞑想', 'description': '瞑想', 'tags': ['auto'],
}}}

SESSION_LOG = (
    'timestamp,duration_min,pipeline_version,meditation_type\n'
    '2026-11-01 06:00:00,10.000,,\n'           # 期間外
    '2026-11-02 06:30:15,20.500,v3,shamatha\n'
    '2026-11-04 07:00:00,,v3,shamatha\n'        # duration 空は飛ばす
    '2026-11-05 21:00:00,15.000,,\n'            # pipeline_version 空でも入れる
)


@pytest.fixture
def session_log(tmp_path, monkeypatch):
    path = tmp_path / 'session_log.csv'
    path.write_text(SESSION_LOG)
    monkeypatch.setattr(meditation, 'SATORU_SESSION_LOG', path)
    return path


def _intervals():
    return toggl_sources.satoru_meditation_intervals(
        dt.date(2026, 11, 2), dt.date(2026, 11, 14), CONFIG, JST)


def _ledger(rows=()):
    return pd.DataFrame(list(rows), columns=toggl_push.LEDGER_COLUMNS)


def _focus_csv(tmp_path, rows):
    """(project_name, start, stop) の行を focus_entries.csv として書き、照合用に読み戻す"""
    path = tmp_path / 'focus_entries.csv'
    pd.DataFrame(
        [{'id': i, 'start': s, 'stop': e, 'duration_sec': 0, 'description': '',
          'project_id': 1, 'project_name': p, 'workspace_id': 42, 'tags': ''}
         for i, (p, s, e) in enumerate(rows)]
    ).to_csv(path, index=False)
    return toggl_push.load_focus_entries_for_match(path)


def test_intervals_from_session_log(session_log):
    intervals = _intervals()
    assert [i.source_id for i in intervals] == ['2026-11-02 06:30:15', '2026-11-05 21:00:00']
    first = intervals[0]
    assert first.start == dt.datetime(2026, 11, 2, 6, 30, 15, tzinfo=JST)
    assert first.stop == dt.datetime(2026, 11, 2, 6, 50, 45, tzinfo=JST)
    assert first.start.tzinfo is not None and first.stop.tzinfo is not None
    assert (first.source, first.project, first.description, first.tags) == \
        ('satoru_meditation', '瞑想', '瞑想', ('auto',))
    assert first.skip_on_overlap


def test_missing_session_log_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(meditation, 'SATORU_SESSION_LOG', tmp_path / 'missing.csv')
    with pytest.raises(FileNotFoundError):
        _intervals()


def test_disabled_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(meditation, 'SATORU_SESSION_LOG', tmp_path / 'missing.csv')
    config = {'sources': {'satoru_meditation': {'enabled': False}}}
    assert toggl_sources.satoru_meditation_intervals(
        dt.date(2026, 11, 2), dt.date(2026, 11, 14), config, JST) == []


def test_overlapping_meditation_entry_is_skipped(session_log, tmp_path):
    """11-02 06:30:15〜06:50:45 の Muse の回。YOGA が 06:20〜06:31 にあれば重なるので外す"""
    focus_df = _focus_csv(tmp_path, [('瞑想', '2026-11-02 06:20:00', '2026-11-02 06:31:00')])
    pending, skipped = select_pending(_intervals(), _ledger(), focus_df)
    assert [i.source_id for i in pending] == ['2026-11-05 21:00:00']
    assert skipped == 1


def test_touching_or_other_project_entry_does_not_block(session_log, tmp_path):
    """終わり＝相手の開始（端が接するだけ）・別プロジェクトの重なりは投入する"""
    focus_df = _focus_csv(tmp_path, [
        ('瞑想', '2026-11-02 06:50:45', '2026-11-02 07:10:00'),    # Muse の終わり＝相手の開始
        ('瞑想', '2026-11-05 20:40:00', '2026-11-05 21:00:00'),    # 相手の終わり＝Muse の開始
        ('サイクリング', '2026-11-02 06:00:00', '2026-11-02 08:00:00'),
    ])
    pending, skipped = select_pending(_intervals(), _ledger(), focus_df)
    assert len(pending) == 2 and skipped == 0


def test_running_entry_without_stop_is_ignored(session_log, tmp_path):
    focus_df = _focus_csv(tmp_path, [('瞑想', '2026-11-02 06:20:00', None)])
    pending, _ = select_pending(_intervals(), _ledger(), focus_df)
    assert len(pending) == 2


def test_ledgered_session_is_not_repushed(session_log):
    ledger = _ledger([{
        'source': 'satoru_meditation', 'source_id': '2026-11-02 06:30:15',
        'toggl_entry_id': '9001', 'start': '2026-11-02T06:30:15+09:00',
        'pushed_at': '2026-11-14T08:00:00+09:00',
    }])
    pending, skipped = select_pending(_intervals(), ledger, None)
    assert [i.source_id for i in pending] == ['2026-11-05 21:00:00']
    assert skipped == 1


def test_overlap_does_not_apply_to_other_sources(tmp_path):
    """googlehealth_* は従来どおり start 60秒以内の照合だけ（重なりでは外さない）"""
    interval = toggl_push.Interval(
        source='googlehealth_exercise', source_id='1',
        start=dt.datetime(2026, 11, 2, 6, 30, tzinfo=JST),
        stop=dt.datetime(2026, 11, 2, 6, 50, tzinfo=JST),
        description='瞑想', project='瞑想', tags=('auto',),
    )
    focus_df = _focus_csv(tmp_path, [('瞑想', '2026-11-02 06:20:00', '2026-11-02 06:40:00')])
    pending, skipped = select_pending([interval], _ledger(), focus_df)
    assert pending == [interval] and skipped == 0
