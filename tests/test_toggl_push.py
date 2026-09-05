"""
Toggl push（Issue #58）の冪等性判定・ソース抽出のテスト

API を叩かない純粋ロジックのみ対象。select_pending は ledger_df / entries_df を
引数で受ける純粋関数にしてあるので、require_private_path に依存せずテストできる。
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from lib.toggl.push import (
    Interval, build_payload, is_entries_csv_stale, push_intervals, select_pending,
)
from lib.toggl import client as toggl_client
from lib.toggl import sources as toggl_sources
from lib.toggl import store as toggl_store
from lib import exercise_source

JST = ZoneInfo('Asia/Tokyo')


def _interval(source_id: str, start_str: str, stop_str: str) -> Interval:
    start = dt.datetime.fromisoformat(start_str).replace(tzinfo=JST)
    stop = dt.datetime.fromisoformat(stop_str).replace(tzinfo=JST)
    return Interval(
        source='googlehealth_sleep', source_id=source_id, start=start, stop=stop,
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
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    entries = _entries_df([{'id': '999', 'start': '2026-08-20 22:00:00'}])
    pending, skipped = select_pending(intervals, ledger, entries, check_deleted=True)
    assert pending == []
    assert skipped == 1


def test_deleted_in_toggl_within_fetch_window_is_repushed():
    """台帳にあるが time_entries.csv に居らず、start が直近 fetch 窓の中 → 再投入対象"""
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    # 08-19〜08-22 を fetch したのに id=999 が返ってこない = 手動削除された
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-19 08:00:00'},
        {'id': '222', 'start': '2026-08-22 08:00:00'},
    ])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 19), dt.date(2026, 8, 22)),
        fetched_at=dt.datetime(2026, 8, 23, 8, 0, tzinfo=JST))
    assert pending == intervals
    assert skipped == 0


def test_deleted_but_outside_fetch_window_is_not_repushed():
    """fetch 窓の外は「未取得」と区別できないので再投入しない（安全弁）"""
    intervals = [_interval('100', '2026-07-01T22:00:00', '2026-07-02T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-07-01T22:00:00+09:00', 'pushed_at': '2026-07-02T07:00:00+09:00',
    }])
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-19 08:00:00'},
        {'id': '222', 'start': '2026-08-22 08:00:00'},
    ])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 19), dt.date(2026, 8, 22)))
    assert pending == []
    assert skipped == 1


def test_entry_pushed_before_fetch_window_is_not_repushed():
    """回帰: 睡眠の start は対象日の前日夜。fetch と push を同じ --days で回すと
    投入済みエントリがどの fetch 窓にも入らず、毎回「削除された」と誤判定されて
    重複投入されていた。CSV の start の min/max を窓に使うと再発する"""
    intervals = [_interval('100', '2026-08-23T22:46:00', '2026-08-24T07:24:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-23T22:46:00+09:00', 'pushed_at': '2026-08-25T11:01:00+09:00',
    }])
    # CSV は 08-12 から積み上がっている（min/max を使うと 08-23 はカバー内に見える）
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-12 09:07:00'},
        {'id': '222', 'start': '2026-08-24 22:08:00'},
    ])
    # だが直近 fetch は --days 2 で 08-24〜08-25 しか取りに行っていない
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 24), dt.date(2026, 8, 25)))
    assert pending == []
    assert skipped == 1


def test_no_fetch_window_disables_deletion_check():
    """fetch 期間の記録が無ければ削除検出はしない（fetch_state.json 未生成の環境）"""
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    entries = _entries_df([{'id': '111', 'start': '2026-08-20 08:00:00'}])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True, fetch_window=None)
    assert pending == []
    assert skipped == 1


def test_fetch_window_end_day_is_inclusive():
    """窓の end は日付。その日の 23:59 に始まるエントリも判定対象に含む"""
    intervals = [_interval('100', '2026-08-22T23:59:00', '2026-08-23T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-22T23:59:00+09:00', 'pushed_at': '2026-08-23T07:00:00+09:00',
    }])
    entries = _entries_df([{'id': '111', 'start': '2026-08-22 08:00:00'}])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 19), dt.date(2026, 8, 22)),
        fetched_at=dt.datetime(2026, 8, 23, 8, 0, tzinfo=JST))
    assert pending == intervals
    assert skipped == 0


def test_confirm_deleted_false_prevents_repush():
    """confirm_deleted が False（＝Toggl にまだ実体がある）を返すなら再投入しない

    取得窓のずれ（Issue #127）で「取得していないだけ」を「削除された」と誤判定
    しても、この確認で最後にブロックできることの回帰テスト
    """
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-19 08:00:00'},
        {'id': '222', 'start': '2026-08-22 08:00:00'},
    ])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 19), dt.date(2026, 8, 22)),
        fetched_at=dt.datetime(2026, 8, 23, 8, 0, tzinfo=JST),
        confirm_deleted=lambda entry_id: False)
    assert pending == []
    assert skipped == 1


def test_confirm_deleted_true_still_repushes():
    """confirm_deleted が True（＝実際に削除済みと確認できた）なら従来どおり再投入する"""
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-19 08:00:00'},
        {'id': '222', 'start': '2026-08-22 08:00:00'},
    ])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 19), dt.date(2026, 8, 22)),
        fetched_at=dt.datetime(2026, 8, 23, 8, 0, tzinfo=JST),
        confirm_deleted=lambda entry_id: True)
    assert pending == intervals
    assert skipped == 0


def test_confirm_deleted_none_keeps_old_behavior():
    """confirm_deleted=None（既定）は確認せず、これまで通り再投入する"""
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': '2026-08-21T07:00:00+09:00',
    }])
    entries = _entries_df([
        {'id': '111', 'start': '2026-08-19 08:00:00'},
        {'id': '222', 'start': '2026-08-22 08:00:00'},
    ])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 19), dt.date(2026, 8, 22)),
        fetched_at=dt.datetime(2026, 8, 23, 8, 0, tzinfo=JST))
    assert pending == intervals
    assert skipped == 0


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


def test_googlehealth_sleep_intervals_includes_nap_and_preserves_log_id(tmp_path, monkeypatch):
    csv_path = tmp_path / 'sleep.csv'
    csv_path.write_text(
        'dateOfSleep,startTime,endTime,logId,isMainSleep\n'
        '2026-08-20,2026-08-19T22:17:30.000,2026-08-20T05:33:00.000,'
        '3658461866274873688,True\n'
        '2026-08-20,2026-08-20T13:00:00.000,2026-08-20T13:30:00.000,'
        '3658461866274873689,False\n'
    )
    monkeypatch.setattr(toggl_sources, 'SLEEP_CSV_FILE', csv_path)

    config = {'sources': {'googlehealth_sleep': {
        'enabled': True, 'project': 'Sleep', 'description': '睡眠', 'tags': ['auto'],
    }}}
    intervals = toggl_sources.googlehealth_sleep_intervals(
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


def test_googlehealth_sleep_intervals_disabled_returns_empty(tmp_path, monkeypatch):
    csv_path = tmp_path / 'sleep.csv'
    csv_path.write_text(
        'dateOfSleep,startTime,endTime,logId,isMainSleep\n'
        '2026-08-20,2026-08-19T22:17:30.000,2026-08-20T05:33:00.000,111,True\n'
    )
    monkeypatch.setattr(toggl_sources, 'SLEEP_CSV_FILE', csv_path)
    config = {'sources': {'googlehealth_sleep': {'enabled': False}}}
    intervals = toggl_sources.googlehealth_sleep_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), config, JST,
    )
    assert intervals == []


# =============================================================================
# googlehealth_exercise ソース
# =============================================================================

EXERCISE_CONFIG = {'sources': {'googlehealth_exercise': {
    'enabled': True,
    'categories': {
        'cycling': {'project': 'サイクリング', 'description': 'サイクリング',
                    'tags': ['auto'],
                    'exercise_types': ['OUTDOOR_BIKE', 'BIKING']},
        'workout': {'project': '筋トレ', 'description': '筋トレ', 'tags': ['auto'],
                    'exercise_types': ['WEIGHTS', 'STRENGTH_TRAINING']},
        'meditation': {'project': '瞑想', 'description': '瞑想', 'tags': ['auto'],
                       'exercise_types': ['MEDITATE']},
    },
}}}

EXERCISE_HEADER = (
    'id,start,end,duration_sec,exercise_type,display_name,platform,'
    'calories,distance_m,average_heart_rate\n'
)


def write_exercise_csv(tmp_path, monkeypatch, body):
    csv_path = tmp_path / 'exercise.csv'
    csv_path.write_text(EXERCISE_HEADER + body)
    monkeypatch.setattr(exercise_source, 'EXERCISE_CSV_FILE', csv_path)
    return csv_path


def test_exercise_maps_types_to_categories(tmp_path, monkeypatch):
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT\n'
        '2222222222222222222,2026-08-20 07:00:00+09:00,2026-08-20 07:30:00+09:00,'
        '1800,WEIGHTS,リフティング,FITBIT\n'
        '3333333333333333333,2026-08-20 08:00:00+09:00,2026-08-20 08:10:00+09:00,'
        '600,MEDITATE,瞑想,FITBIT\n'
    ))
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), EXERCISE_CONFIG, JST,
    )
    assert {i.project for i in intervals} == {'サイクリング', '筋トレ', '瞑想'}
    # 19桁のidがfloat化して精度が飛んでいないこと
    assert '1111111111111111111' in {i.source_id for i in intervals}
    bike = next(i for i in intervals if i.project == 'サイクリング')
    assert bike.start == dt.datetime(2026, 8, 20, 6, 0, tzinfo=JST)
    assert bike.tags == ('auto',)


def test_exercise_skips_types_outside_categories(tmp_path, monkeypatch):
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,WALKING,ウォーキング,FITBIT\n'
        '2222222222222222222,2026-08-20 07:00:00+09:00,2026-08-20 07:30:00+09:00,'
        '1800,YOGA,ヨガ,FITBIT\n'
    ))
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), EXERCISE_CONFIG, JST,
    )
    assert intervals == []


def test_exercise_drops_lower_priority_platform_on_overlap(tmp_path, monkeypatch):
    # 同じ筋トレが Fitbit と Health Connect(Hevy) の両方から届く
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:40:00+09:00,2026-08-20 07:13:00+09:00,'
        '1980,WEIGHTS,リフティング,FITBIT\n'
        '2222222222222222222,2026-08-20 06:45:00+09:00,2026-08-20 07:12:00+09:00,'
        '1620,STRENGTH_TRAINING,ウェイトトレーニング,HEALTH_CONNECT\n'
    ))
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), EXERCISE_CONFIG, JST,
    )
    assert [i.source_id for i in intervals] == ['1111111111111111111']


def test_exercise_keeps_non_overlapping_low_priority_platform(tmp_path, monkeypatch):
    # 重なっていなければ platform で捨てない（Fitbit を外しても穴が空かない）
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT\n'
        '2222222222222222222,2026-08-20 18:00:00+09:00,2026-08-20 18:30:00+09:00,'
        '1800,BIKING,サイクリング,HEALTH_CONNECT\n'
    ))
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), EXERCISE_CONFIG, JST,
    )
    assert len(intervals) == 2


def test_exercise_touching_sessions_are_both_kept(tmp_path, monkeypatch):
    # 終了と開始が接するだけ（重なり0秒）のセッションは別物として残す
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 05:51:00+09:00,2026-08-20 05:58:00+09:00,'
        '420,BIKING,サイクリング,HEALTH_CONNECT\n'
        '2222222222222222222,2026-08-20 05:58:00+09:00,2026-08-20 06:32:00+09:00,'
        '2040,OUTDOOR_BIKE,野外サイクリング,FITBIT\n'
    ))
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), EXERCISE_CONFIG, JST,
    )
    assert len(intervals) == 2


def test_exercise_filters_by_period(tmp_path, monkeypatch):
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-19 06:00:00+09:00,2026-08-19 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT\n'
        '2222222222222222222,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT\n'
    ))
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), EXERCISE_CONFIG, JST,
    )
    assert [i.source_id for i in intervals] == ['2222222222222222222']


def test_exercise_disabled_returns_empty(tmp_path, monkeypatch):
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:00:00+09:00,2026-08-20 06:30:00+09:00,'
        '1800,OUTDOOR_BIKE,野外サイクリング,FITBIT\n'
    ))
    config = {'sources': {'googlehealth_exercise': {'enabled': False}}}
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), config, JST,
    )
    assert intervals == []


# =============================================================================
# 回帰: fetch を挟まない再 push / 秒未満のタイムスタンプ
# =============================================================================

def test_entry_pushed_after_last_fetch_is_not_repushed():
    """回帰: fetch を挟まずに push を2回叩くと重複投入していた

    投入直後のエントリは、次の fetch までは CSV に居なくて当たり前。
    それを「手動削除された」と読むと、2回目の push が同じ運動をもう1本作る
    （2026-08-25 に実際に発生。サイクリング2件が Toggl 上で二重になった）。
    """
    intervals = [_interval('100', '2026-08-25T10:11:16', '2026-08-25T10:43:42')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-25T10:11:16+09:00', 'pushed_at': '2026-08-25T22:17:44+09:00',
    }])
    # CSV は 22:10 の fetch 時点のもの。その後 22:17 に投入した id=999 は
    # まだ一度も取りに行っていないので、居なくて当たり前
    entries = _entries_df([{'id': '111', 'start': '2026-08-25 09:00:00'}])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 25), dt.date(2026, 8, 25)),
        fetched_at=dt.datetime(2026, 8, 25, 22, 10, 0, tzinfo=JST))
    assert pending == []
    assert skipped == 1


def test_unknown_pushed_at_is_not_repushed():
    """pushed_at が読めないときは再投入しない側へ倒す"""
    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-08-20T22:00:00+09:00', 'pushed_at': None,
    }])
    entries = _entries_df([{'id': '111', 'start': '2026-08-20 08:00:00'}])
    pending, skipped = select_pending(
        intervals, ledger, entries, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 19), dt.date(2026, 8, 22)),
        fetched_at=dt.datetime(2026, 8, 23, 8, 0, tzinfo=JST))
    assert pending == []
    assert skipped == 1


def test_build_payload_truncates_subsecond():
    """回帰: Toggl は秒未満を含む RFC3339 を 400 で弾く

    Health Connect 由来のセッションはミリ秒付きで届く。
    """
    start = dt.datetime(2026, 8, 25, 19, 9, 17, 944000, tzinfo=JST)
    stop = dt.datetime(2026, 8, 25, 19, 21, 1, 168000, tzinfo=JST)
    interval = Interval(
        source='googlehealth_exercise', source_id='1', start=start, stop=stop,
        description='サイクリング', project='サイクリング', tags=('auto',),
    )
    payload = build_payload(interval, 88463, {'サイクリング': 222011943})
    assert payload['start'] == '2026-08-25T19:09:17+09:00'
    assert payload['stop'] == '2026-08-25T19:21:01+09:00'
    assert payload['duration'] == 704


# --- push が作成分を time_entries.csv に書く（Issue #130） ---

def _patch_push_targets(monkeypatch, tmp_path):
    """push_intervals の実書き込み経路を監視できるよう台帳・CSVをtmpに逃す"""
    ledger_path = tmp_path / 'pushed.csv'
    csv_path = tmp_path / 'time_entries.csv'
    monkeypatch.setattr('lib.toggl.push.LEDGER_FILE', ledger_path)
    monkeypatch.setattr(toggl_store, 'CSV_FILE', csv_path)
    return ledger_path, csv_path


def _fake_created_entry(entry_id: int, start_iso: str, stop_iso: str, project_id: int) -> dict:
    return {
        'id': entry_id,
        'workspace_id': 1,
        'project_id': project_id,
        'start': start_iso,
        'stop': stop_iso,
        'duration': 3600,
        'description': '睡眠',
        'tags': ['auto'],
    }


def test_push_writes_created_entries_to_csv(tmp_path, monkeypatch):
    ledger_path, csv_path = _patch_push_targets(monkeypatch, tmp_path)

    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]

    monkeypatch.setattr(toggl_client, 'fetch_me', lambda token: {'default_workspace_id': 1})
    monkeypatch.setattr(toggl_client, 'fetch_projects', lambda token, ws: {222: 'Sleep'})
    monkeypatch.setattr(
        toggl_client, 'create_time_entry',
        lambda token, ws, payload: _fake_created_entry(
            999, '2026-08-20T22:00:00+09:00', '2026-08-21T06:00:00+09:00', 222),
    )

    result = push_intervals(
        intervals=intervals, ledger_df=_ledger_df([]), entries_df=None,
        max_writes=10, dry_run=False, api_token='dummy-token',
        out=__import__('io').StringIO(),
    )

    assert result['pushed'] == 1
    assert ledger_path.exists()
    assert csv_path.exists()
    df_csv = pd.read_csv(csv_path)
    assert df_csv['id'].astype(str).tolist() == ['999']
    assert df_csv['start'].tolist() == ['2026-08-20 22:00:00']


def test_push_dry_run_does_not_write_csv(tmp_path, monkeypatch):
    _ledger_path, csv_path = _patch_push_targets(monkeypatch, tmp_path)

    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]

    # dry_run では API を呼ばないはず。呼ばれたら失敗させて検出する
    monkeypatch.setattr(toggl_client, 'fetch_me',
                         lambda token: (_ for _ in ()).throw(AssertionError('called in dry_run')))
    monkeypatch.setattr(toggl_client, 'create_time_entry',
                         lambda token, ws, payload: (_ for _ in ()).throw(
                             AssertionError('called in dry_run')))

    result = push_intervals(
        intervals=intervals, ledger_df=_ledger_df([]), entries_df=None,
        max_writes=10, dry_run=True, api_token=None,
        out=__import__('io').StringIO(),
    )

    assert result['pushed'] == 0
    assert not csv_path.exists()


def test_push_created_entry_reappears_as_pending_after_deletion_detected(tmp_path, monkeypatch):
    """1(pushがCSVへ書く)を入れたあとも、削除検出(select_pending)が生きていること

    push で書いた行が、次の fetch で API レスポンスに無くなり
    store.drop_stale_rows_in_window で消えたあと、select_pending が
    再び pending を返すことを確認する。
    """
    _ledger_path, csv_path = _patch_push_targets(monkeypatch, tmp_path)

    intervals = [_interval('100', '2026-08-20T22:00:00', '2026-08-21T06:00:00')]

    monkeypatch.setattr(toggl_client, 'fetch_me', lambda token: {'default_workspace_id': 1})
    monkeypatch.setattr(toggl_client, 'fetch_projects', lambda token, ws: {222: 'Sleep'})
    monkeypatch.setattr(
        toggl_client, 'create_time_entry',
        lambda token, ws, payload: _fake_created_entry(
            999, '2026-08-20T22:00:00+09:00', '2026-08-21T06:00:00+09:00', 222),
    )

    push_intervals(
        intervals=intervals, ledger_df=_ledger_df([]), entries_df=None,
        max_writes=10, dry_run=False, api_token='dummy-token',
        out=__import__('io').StringIO(),
    )
    ledger_df = pd.read_csv(csv_path.parent / 'pushed.csv',
                            dtype={'source_id': str, 'toggl_entry_id': str})

    # 次の fetch がこの窓を取り直したが、Toggl 側で手動削除されていた
    # （API レスポンスに id=999 が無い）
    df_new = pd.DataFrame(columns=toggl_store.CSV_COLUMNS)
    df_new.loc[0] = {
        'id': 1, 'start': '2026-08-19 08:00:00', 'stop': '2026-08-19 09:00:00',
        'duration_sec': 3600, 'description': 'unrelated', 'project_id': None,
        'project_name': '', 'workspace_id': 1, 'tags': '',
    }
    removed = toggl_store.drop_stale_rows_in_window(
        df_new, window=(dt.date(2026, 8, 20), dt.date(2026, 8, 21)))
    assert removed == 1

    entries_df = pd.read_csv(csv_path, usecols=['id', 'start'], dtype={'id': str}, parse_dates=['start'])
    # pushed_at には push_intervals 実行時刻(実時間)が記録されるので、
    # fetched_at はそれより確実に後にする
    fetched_at = dt.datetime.now(JST) + dt.timedelta(days=1)
    pending, skipped = select_pending(
        intervals, ledger_df, entries_df, check_deleted=True,
        fetch_window=(dt.date(2026, 8, 20), dt.date(2026, 8, 21)),
        fetched_at=fetched_at,
    )
    assert pending == intervals
    assert skipped == 0
