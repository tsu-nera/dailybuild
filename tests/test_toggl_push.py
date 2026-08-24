"""
Toggl push（Issue #58）の冪等性判定・ソース抽出のテスト

API を叩かない純粋ロジックのみ対象。select_pending は ledger_df / entries_df を
引数で受ける純粋関数にしてあるので、require_private_path に依存せずテストできる。
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from lib.toggl.push import Interval, is_entries_csv_stale, push_intervals, select_pending
from lib.toggl import sources as toggl_sources

JST = ZoneInfo('Asia/Tokyo')


def _interval(source_id: str, start_str: str, stop_str: str) -> Interval:
    start = dt.datetime.fromisoformat(start_str).replace(tzinfo=JST)
    stop = dt.datetime.fromisoformat(stop_str).replace(tzinfo=JST)
    return Interval(
        source='fitbit_sleep', source_id=source_id, start=start, stop=stop,
        description='睡眠', project='Sleep', tags=('auto',),
    )


def _ledger_df(rows: list[dict]) -> pd.DataFrame:
    cols = ['source', 'source_id', 'toggl_entry_id', 'start', 'pushed_at']
    return pd.DataFrame(rows, columns=cols)


def _entries_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=['id', 'start'])


def test_not_in_ledger_is_pending():
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([])
    pending, skipped = select_pending(intervals, ledger, None, check_deleted=False)
    assert pending == intervals
    assert skipped == 0


def test_in_ledger_and_in_csv_is_skipped():
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'fitbit_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    entries = _entries_df([{'id': '999', 'start': '2026-08-20 22:00:00'}])
    pending, skipped = select_pending(intervals, ledger, entries, check_deleted=True)
    assert pending == []
    assert skipped == 1


def test_deleted_in_toggl_within_coverage_is_repushed():
    """台帳にあるが time_entries.csv に居らず、start がCSVのカバー範囲内 → 再投入対象"""
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'fitbit_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    # CSVのカバー範囲は 08-19〜08-22 だが id=999 は居ない(手動削除された)
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-19 08:00:00'},
        {'id': '222', 'start': '2026-08-22 08:00:00'},
    ])
    pending, skipped = select_pending(intervals, ledger, entries, check_deleted=True)
    assert pending == intervals
    assert skipped == 0


def test_deleted_but_outside_coverage_is_not_repushed():
    """カバー範囲外は「未取得」と区別できないので再投入しない（安全弁）"""
    intervals = [_interval('100', '2026-07-01T22:00:00', '2026-07-02T06:00:00')]
    ledger = _ledger_df([{
        'source': 'fitbit_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-07-01T22:00:00+09:00', 'pushed_at': '2026-07-02T07:00:00+09:00',
    }])
    # CSVのカバー範囲は 08月のみ。7月分の削除有無は判定できない
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-19 08:00:00'},
        {'id': '222', 'start': '2026-08-22 08:00:00'},
    ])
    pending, skipped = select_pending(intervals, ledger, entries, check_deleted=True)
    assert pending == []
    assert skipped == 1


def test_max_writes_carries_over_excess():
    intervals = [
        _interval('1', '2026-08-18T22:00:00', '2026-08-19T06:00:00'),
        _interval('2', '2026-08-19T22:00:00', '2026-08-20T06:00:00'),
        _interval('3', '2026-08-20T22:00:00', '2026-08-21T06:00:00'),
    ]
    ledger = _ledger_df([])
    result = push_intervals(
        intervals=intervals, ledger_df=ledger, entries_df=None,
        max_writes=2, dry_run=True, api_token=None, out=__import__('io').StringIO(),
    )
    assert len(result['to_push']) == 2
    assert len(result['carried_over']) == 1
    assert result['carried_over'][0].source_id == '3'


def test_is_entries_csv_stale_missing():
    assert is_entries_csv_stale(None, dt.date(2026, 8, 24)) is True


def test_is_entries_csv_stale_old_data():
    entries = _entries_df([{'id': '1', 'start': '2026-08-10 08:00:00'}])
    assert is_entries_csv_stale(entries, dt.date(2026, 8, 24)) is True


def test_is_entries_csv_fresh():
    entries = _entries_df([{'id': '1', 'start': '2026-08-23 08:00:00'}])
    assert is_entries_csv_stale(entries, dt.date(2026, 8, 24)) is False


def test_fitbit_sleep_intervals_includes_nap_and_preserves_log_id(tmp_path, monkeypatch):
    csv_path = tmp_path / 'sleep.csv'
    csv_path.write_text(
        'dateOfSleep,startTime,endTime,logId,isMainSleep\n'
        '2026-08-20,2026-08-19T22:17:30.000,2026-08-20T05:33:00.000,'
        '3658461866274873688,True\n'
        '2026-08-20,2026-08-20T13:00:00.000,2026-08-20T13:30:00.000,'
        '3658461866274873689,False\n'
    )
    monkeypatch.setattr(toggl_sources, 'SLEEP_CSV_FILE', csv_path)

    config = {'sources': {'fitbit_sleep': {
        'enabled': True, 'project': 'Sleep', 'description': '睡眠', 'tags': ['auto'],
    }}}
    intervals = toggl_sources.fitbit_sleep_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), config, JST,
    )

    assert len(intervals) == 2
    source_ids = {i.source_id for i in intervals}
    assert source_ids == {'3658461866274873688', '3658461866274873689'}
    # 19桁のlogIdがfloat化して精度が飛んでいないこと
    assert '3658461866274873688' in source_ids

    main_sleep = next(i for i in intervals if i.source_id == '3658461866274873688')
    assert main_sleep.start.tzinfo is not None
    assert main_sleep.start == dt.datetime(2026, 8, 19, 22, 17, 30, tzinfo=JST)
    assert main_sleep.stop == dt.datetime(2026, 8, 20, 5, 33, 0, tzinfo=JST)


def test_fitbit_sleep_intervals_disabled_returns_empty(tmp_path, monkeypatch):
    csv_path = tmp_path / 'sleep.csv'
    csv_path.write_text(
        'dateOfSleep,startTime,endTime,logId,isMainSleep\n'
        '2026-08-20,2026-08-19T22:17:30.000,2026-08-20T05:33:00.000,111,True\n'
    )
    monkeypatch.setattr(toggl_sources, 'SLEEP_CSV_FILE', csv_path)
    config = {'sources': {'fitbit_sleep': {'enabled': False}}}
    intervals = toggl_sources.fitbit_sleep_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), config, JST,
    )
    assert intervals == []
