"""
lib.events（reports/events.jsonl の生成）のテスト（Issue #166）

テストするのは「欠測を捏造しない」「二重に入れない」だけ:
naive 時刻の JST 解釈、点イベントの end=null、push 由来 Toggl の除外、
platform 重複の解決、0件ソースでの失敗、data/ を書き換えないこと。
"""

import hashlib
import json

import pytest

from lib.events import build, sources

TOGGL_HEADER = 'id,start,stop,duration_sec,description,project_name,tags\n'
PUSHED_HEADER = 'source,source_id,toggl_entry_id,start,pushed_at\n'
EXERCISE_HEADER = (
    'id,start,end,duration_sec,exercise_type,display_name,platform,'
    'calories,distance_m,average_heart_rate\n'
)
SLEEP_HEADER = 'dateOfSleep,startTime,endTime,minutesAsleep,minutesAwake,efficiency,logId,isMainSleep\n'
HABITICA_HEADER = (
    'date,ts,task_id,task_type,task_name,value,is_due,completed,scored_up,scored_down\n'
)


@pytest.fixture
def paths(tmp_path):
    p = build.SourcePaths(
        toggl_entries=tmp_path / 'time_entries.csv',
        toggl_pushed=tmp_path / 'pushed.csv',
        exercise=tmp_path / 'exercise.csv',
        sleep=tmp_path / 'sleep.csv',
        habitica_history=tmp_path / 'history.csv',
    )
    p.toggl_entries.write_text(
        TOGGL_HEADER
        + '4509467120,2026-08-07 08:05:00,2026-08-07 08:20:47,947,,GTD,\n'
        # push 由来（exercise 側の 1697771750265919752 と同じ活動）
        + '4578749526,2026-10-07 08:04:00,2026-10-07 08:23:22,1162,サイクリング,サイクリング,auto\n'
    )
    p.toggl_pushed.write_text(
        PUSHED_HEADER
        + 'googlehealth_exercise,1697771750265919752,4578749526,'
          '2026-10-07T08:04:00+09:00,2026-10-07T08:56:48+09:00\n'
    )
    p.exercise.write_text(
        EXERCISE_HEADER
        + '1697771750265919752,2026-10-07 08:04:00+09:00,2026-10-07 08:23:22+09:00,'
          '1162,BIKING,サイクリング,HEALTH_CONNECT,,,\n'
        # 同じ運動の Fitbit 側。サイクリングは Fitbit 優先なのでこちらが残る
        + '5555555555555555555,2026-10-07 08:05:00+09:00,2026-10-07 08:23:00+09:00,'
          '1080,OUTDOOR_BIKE,野外サイクリング,FITBIT,100,5000,110\n'
    )
    p.sleep.write_text(
        SLEEP_HEADER
        + '2026-10-07,2026-10-07T00:53:00.000,2026-10-07T06:58:00.000,357,8,98,2903875957116713824,True\n'
        + '2026-10-07,2026-10-07T14:00:00.000,2026-10-07T14:30:00.000,30,0,100,1111,False\n'
    )
    p.habitica_history.write_text(
        HABITICA_HEADER
        # cron 行（未完了）は実行ではないので落ちる
        + '2026-10-05,2026-10-05T07:59:05,aaa,daily,片付け,-4.0,True,False,,\n'
        + '2026-10-05,2026-10-05T22:29:00,bbb,daily,日記,1.0,True,True,,\n'
        + '2026-10-05,2026-10-05T12:00:00,ccc,habit,散歩,1.0,,,2,0\n'
        + '2026-10-05,2026-10-05T12:00:00,ddd,habit,押してない,0.0,,,0,0\n'
        # completed を持たない古い行は実行の有無が分からないので入れない
        + '2023-02-12,2023-02-12T17:48:36,eee,daily,古い行,1.7,,,,\n'
    )
    return p


def build_lines(paths, tmp_path):
    out = tmp_path / 'events.jsonl'
    build.write_jsonl(build.merge(build.collect(paths)), out)
    return [json.loads(line) for line in out.read_text().splitlines()]


def test_toggl_naive_is_jst_not_utc(paths):
    events = sources.toggl_events(paths.toggl_entries, paths.toggl_pushed)
    # UTC と解釈すると 17:05+09:00 になる
    assert events[0]['start'].isoformat() == '2026-08-07T08:05:00+09:00'
    assert events[0]['end'].isoformat() == '2026-08-07T08:20:47+09:00'


def test_all_starts_are_aware_jst(paths, tmp_path):
    lines = build_lines(paths, tmp_path)
    assert lines
    for line in lines:
        assert line['start'].endswith('+09:00')
        assert line['end'] is None or line['end'].endswith('+09:00')


def test_point_events_have_null_end(paths, tmp_path):
    lines = build_lines(paths, tmp_path)
    habitica = [line for line in lines if line['source'] == 'habitica']
    assert habitica and all(line['end'] is None for line in habitica)
    assert not any(line['start'] == line['end'] for line in lines)


def test_pushed_toggl_entry_is_dropped(paths):
    events = sources.toggl_events(paths.toggl_entries, paths.toggl_pushed)
    assert [e['attrs']['id'] for e in events] == ['4509467120']


def test_exercise_platform_duplicate_resolves_to_one(paths):
    events = sources.exercise_events(paths.exercise)
    assert [e['attrs']['id'] for e in events] == ['5555555555555555555']


def test_same_cycling_appears_once(paths, tmp_path):
    lines = build_lines(paths, tmp_path)
    morning = [line for line in lines if line['start'].startswith('2026-10-07T08:0')]
    assert len(morning) == 1


def test_sleep_main_only(paths):
    events = sources.sleep_events(paths.sleep)
    assert [e['attrs']['log_id'] for e in events] == ['2903875957116713824']


def test_habitica_only_actual_actions(paths):
    events = sources.habitica_events(paths.habitica_history)
    assert sorted(e['name'] for e in events) == ['散歩', '日記']


def test_output_sorted_by_start(paths, tmp_path):
    lines = build_lines(paths, tmp_path)
    starts = [sources.to_jst(line['start']) for line in lines]
    assert starts == sorted(starts)


@pytest.mark.parametrize('field', ['toggl_entries', 'exercise', 'sleep', 'habitica_history'])
def test_missing_source_is_reported(paths, field):
    getattr(paths, field).unlink()
    empty = build.empty_sources(build.collect(paths))
    assert len(empty) == 1


def test_cli_fails_on_empty_source_and_keeps_output(paths, tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / 'scripts' / 'events.py'
    spec = importlib.util.spec_from_file_location('events_cli', script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    out = tmp_path / 'out' / 'events.jsonl'
    out.parent.mkdir()
    out.write_text('previous\n')
    paths.habitica_history.write_text(HABITICA_HEADER)
    monkeypatch.setattr(cli, 'require_private_path', lambda p: p)
    monkeypatch.setattr(cli, 'EVENTS_JSONL', out)
    monkeypatch.setattr(cli.build.SourcePaths, 'default', classmethod(lambda cls, root: paths))

    assert cli.main(['build']) != 0
    assert 'habitica' in capsys.readouterr().err
    assert out.read_text() == 'previous\n'


def test_build_does_not_modify_inputs(paths, tmp_path):
    inputs = [paths.toggl_entries, paths.toggl_pushed, paths.exercise,
              paths.sleep, paths.habitica_history]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    build_lines(paths, tmp_path)
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs} == before
