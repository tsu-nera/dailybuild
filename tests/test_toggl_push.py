"""
Toggl push（Issue #58 → #240 で Toggl 2.0 / Focus へ）の冪等性判定・ソース抽出のテスト

Focus API はフェイク（focus の関数を monkeypatch）。台帳・CSV・タグ対応は tmp に逃す。
"""

import datetime as dt
import io
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from lib.toggl import focus
from lib.toggl import push as toggl_push
from lib.toggl import sources as toggl_sources
from lib.toggl import store as toggl_store
from lib.toggl.push import Interval, build_payload, push_intervals, select_pending
from lib import exercise_source

JST = ZoneInfo('Asia/Tokyo')
WS = focus.Workspace('tok', 'org', '42')
TAGS = {'auto': 908186}
PROJECT_IDS = {'Sleep': 222, 'サイクリング': 333}


def _interval(source_id: str, start_str: str, stop_str: str,
              project: str = 'Sleep', tags=('auto',)) -> Interval:
    start = dt.datetime.fromisoformat(start_str).replace(tzinfo=JST)
    stop = dt.datetime.fromisoformat(stop_str).replace(tzinfo=JST)
    return Interval(
        source='googlehealth_sleep', source_id=source_id, start=start, stop=stop,
        description='睡眠', project=project, tags=tuple(tags),
    )


def _ledger_df(rows: list[dict]) -> pd.DataFrame:
    cols = ['source', 'source_id', 'toggl_entry_id', 'start', 'pushed_at']
    return pd.DataFrame(rows, columns=cols)


def _focus_df(rows: list[tuple[str, str]]) -> pd.DataFrame:
    """(project_name, start) の行から focus_entries.csv 相当"""
    df = pd.DataFrame(rows, columns=['project_name', 'start'])
    df['start'] = pd.to_datetime(df['start'])
    return df


class FakeFocus:
    """focus の書き込み API のフェイク。作成した内容を記録し、応答は最小限のエントリ"""

    def __init__(self, monkeypatch, tmp_path, fail_on_call: bool = False):
        self.created = []
        self.fail_on_call = fail_on_call
        monkeypatch.setattr(toggl_push, 'LEDGER_FILE', tmp_path / 'focus_pushed.csv')
        monkeypatch.setattr(focus, 'CSV_FILE', tmp_path / 'focus_entries.csv')
        monkeypatch.setattr(focus, 'fetch_projects', self.fetch_projects)
        monkeypatch.setattr(focus, 'create_time_entry', self.create_time_entry)
        self.ledger_path = tmp_path / 'focus_pushed.csv'
        self.csv_path = tmp_path / 'focus_entries.csv'

    def fetch_projects(self, ws):
        if self.fail_on_call:
            raise AssertionError('API called')
        return {pid: name for name, pid in PROJECT_IDS.items()}

    def create_time_entry(self, ws, payload):
        if self.fail_on_call:
            raise AssertionError('API called')
        self.created.append(payload)
        return {'id': 9000 + len(self.created), 'workspace_id': 42,
                'project_id': payload['project_id'], 'start': payload['start'],
                'duration': payload['duration'], 'description': payload['description'],
                'type': 'activity'}


def run_push(intervals, fake, max_writes=10, dry_run=False, tags=TAGS):
    """台帳と focus_entries.csv を毎回ディスクから読み直して push する（実運用と同じ）"""
    ledger = toggl_push.load_ledger() if fake.ledger_path.exists() else _ledger_df([])
    focus_df = toggl_push.load_focus_entries_for_match(fake.csv_path)
    out = io.StringIO()
    result = push_intervals(
        intervals=intervals, ledger_df=ledger, focus_df=focus_df, max_writes=max_writes,
        dry_run=dry_run, workspace=None if dry_run else WS, out=out, tag_map=tags,
    )
    return result, out.getvalue()


SLEEP = ('2026-10-28T22:00:00', '2026-10-29T06:00:00')


# --- select_pending: 台帳と focus_entries.csv の照合 ---

def test_not_in_ledger_nor_csv_is_pending():
    intervals = [_interval('100', *SLEEP)]
    pending, skipped = select_pending(intervals, _ledger_df([]), None)
    assert pending == intervals and skipped == 0


def test_in_ledger_is_skipped():
    intervals = [_interval('100', *SLEEP)]
    ledger = _ledger_df([{
        'source': 'googlehealth_sleep', 'source_id': '100', 'toggl_entry_id': '999',
        'start': '2026-10-28T22:00:00+09:00', 'pushed_at': '2026-10-29T07:00:00+09:00',
    }])
    pending, skipped = select_pending(intervals, ledger, _focus_df([]))
    assert pending == [] and skipped == 1


def test_matching_focus_row_within_60s_is_not_pending():
    """migrate 済み・手入力のエントリ（同じプロジェクト・start 60秒以内）は投入しない"""
    intervals = [_interval('100', *SLEEP)]
    for start in ('2026-10-28 22:00:00', '2026-10-28 22:01:00', '2026-10-28 21:59:00'):
        pending, skipped = select_pending(intervals, _ledger_df([]), _focus_df([('Sleep', start)]))
        assert pending == [] and skipped == 1, start


def test_focus_row_with_other_project_or_far_start_does_not_match():
    intervals = [_interval('100', *SLEEP)]
    other_project = _focus_df([('サイクリング', '2026-10-28 22:00:00')])
    too_far = _focus_df([('Sleep', '2026-10-28 22:01:01')])
    for df in (other_project, too_far):
        pending, skipped = select_pending(intervals, _ledger_df([]), df)
        assert pending == intervals and skipped == 0


# --- push_intervals ---

def test_dry_run_lists_pending_and_makes_no_api_call(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path, fail_on_call=True)
    intervals = [_interval('100', *SLEEP), _interval('101', '2026-10-29T22:00:00', '2026-10-30T06:00:00')]
    fake.csv_path.write_text('project_name,start\nSleep,2026-10-28 22:00:00\n')

    result, _ = run_push(intervals, fake, dry_run=True)

    assert [i.source_id for i in result['to_push']] == ['101']
    assert result['skipped'] == 1
    assert not fake.ledger_path.exists()


def test_push_twice_does_not_create_twice(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    intervals = [_interval('100', *SLEEP)]

    first, _ = run_push(intervals, fake)
    second, _ = run_push(intervals, fake)

    assert first['pushed'] == 1 and second['pushed'] == 0
    assert len(fake.created) == 1


def test_created_entries_land_in_focus_csv_immediately(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    intervals = [_interval('100', *SLEEP)]

    run_push(intervals, fake)

    df = pd.read_csv(fake.csv_path)
    assert df['project_name'].tolist() == ['Sleep']
    assert df['start'].tolist() == ['2026-10-28 22:00:00']
    assert df['tags'].tolist() == ['auto']
    # CSV の照合だけでも 0 件になる（台帳を消しても二重投入しない）
    fake.ledger_path.unlink()
    again, _ = run_push(intervals, fake)
    assert again['pushed'] == 0 and len(fake.created) == 1


def test_over_max_writes_carries_over(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    intervals = [
        _interval('1', '2026-10-28T22:00:00', '2026-10-29T06:00:00'),
        _interval('2', '2026-10-29T22:00:00', '2026-10-30T06:00:00'),
        _interval('3', '2026-10-30T22:00:00', '2026-10-31T06:00:00'),
    ]

    first, _ = run_push(intervals, fake, max_writes=2)
    assert first['pushed'] == 2
    assert [i.source_id for i in first['carried_over']] == ['3']

    second, _ = run_push(intervals, fake, max_writes=2)
    assert second['pushed'] == 1 and len(fake.created) == 3


def test_unresolvable_tag_is_not_pushed_nor_ledgered(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    intervals = [_interval('100', *SLEEP, tags=('auto', 'mystery'))]

    result, out = run_push(intervals, fake)

    assert result['pushed'] == 0 and fake.created == []
    assert 'タグ mystery' in out
    assert not fake.ledger_path.exists() and not fake.csv_path.exists()


def test_unresolvable_project_is_not_pushed_nor_ledgered(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    intervals = [_interval('100', *SLEEP, project='存在しない')]

    result, out = run_push(intervals, fake)

    assert result['pushed'] == 0 and fake.created == []
    assert 'プロジェクト 存在しない' in out
    assert not fake.ledger_path.exists()


def test_unresolvable_does_not_consume_write_slots(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    intervals = [
        _interval('1', '2026-10-28T22:00:00', '2026-10-29T06:00:00', project='存在しない'),
        _interval('2', '2026-10-29T22:00:00', '2026-10-30T06:00:00'),
    ]
    result, _ = run_push(intervals, fake, max_writes=1)
    assert result['pushed'] == 1 and fake.created[0]['project_id'] == 222


def test_interval_before_cutover_is_not_pushed(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    before = _interval('1', '2026-10-25T22:00:00', '2026-10-26T06:00:00')
    on_cutover = _interval('2', '2026-10-27T00:30:00', '2026-10-27T06:00:00')

    result, out = run_push([before, on_cutover], fake)

    assert result['before_cutover'] == 1 and '1 件' in out
    assert [c['start'] for c in fake.created] == ['2026-10-26T15:30:00Z']


def test_partial_failure_still_ledgers_created_entries(tmp_path, monkeypatch):
    fake = FakeFocus(monkeypatch, tmp_path)
    original = fake.create_time_entry
    calls = []

    def flaky(ws, payload):
        calls.append(payload)
        if len(calls) == 2:
            raise RuntimeError('402')
        return original(ws, payload)

    monkeypatch.setattr(focus, 'create_time_entry', flaky)
    intervals = [_interval('1', '2026-10-28T22:00:00', '2026-10-29T06:00:00'),
                 _interval('2', '2026-10-29T22:00:00', '2026-10-30T06:00:00')]

    with pytest.raises(RuntimeError):
        run_push(intervals, fake)

    assert toggl_push.load_ledger()['source_id'].tolist() == ['1']
    assert len(pd.read_csv(fake.csv_path)) == 1


# --- ペイロード（Focus API の実測） ---

def test_build_payload_shape():
    """type: "activity" 必須、タグは tag_ids のみ、start は UTC の RFC3339 で秒未満なし"""
    start = dt.datetime(2026, 10, 25, 19, 9, 17, 944000, tzinfo=JST)
    stop = dt.datetime(2026, 10, 25, 19, 21, 1, 168000, tzinfo=JST)
    interval = Interval(
        source='googlehealth_exercise', source_id='1', start=start, stop=stop,
        description='サイクリング', project='サイクリング', tags=('auto',),
    )
    assert build_payload(interval, PROJECT_IDS, TAGS) == {
        'type': 'activity',
        'description': 'サイクリング',
        'start': '2026-10-25T10:09:17Z',
        'duration': 704,
        'project_id': 333,
        'tag_ids': [908186],
    }


# =============================================================================
# ソース抽出（Google Health → Interval）
# =============================================================================

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
    # 同じ筋トレが Fitbit と Health Connect(Hevy) の両方から届く。
    # 筋トレは Hevy 側を残す（Fitbit は停止し忘れで伸びる）
    write_exercise_csv(tmp_path, monkeypatch, (
        '1111111111111111111,2026-08-20 06:40:00+09:00,2026-08-20 07:13:00+09:00,'
        '1980,WEIGHTS,リフティング,FITBIT\n'
        '2222222222222222222,2026-08-20 06:45:00+09:00,2026-08-20 07:12:00+09:00,'
        '1620,STRENGTH_TRAINING,ウェイトトレーニング,HEALTH_CONNECT\n'
    ))
    intervals = toggl_sources.googlehealth_exercise_intervals(
        dt.date(2026, 8, 20), dt.date(2026, 8, 20), EXERCISE_CONFIG, JST,
    )
    assert [i.source_id for i in intervals] == ['2222222222222222222']


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
