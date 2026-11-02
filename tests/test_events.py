"""
lib.events（reports/events.jsonl の生成）のテスト（Issue #166）

テストするのは「欠測を捏造しない」「二重に入れない」だけ:
naive 時刻の JST 解釈、点イベントの end=null、push 由来 Toggl の除外、Toggl の区切り日（Track/Focus）、
platform 重複の解決、0件ソースでの失敗、data/ を書き換えないこと。
"""

import hashlib
import json

import pytest

from lib.events import build, sources

TOGGL_HEADER = 'id,start,stop,duration_sec,description,project_name,tags\n'
FOCUS_HEADER = TOGGL_HEADER
PUSHED_HEADER = 'source,source_id,toggl_entry_id,start,pushed_at\n'
EXERCISE_HEADER = (
    'id,start,end,duration_sec,exercise_type,display_name,platform,'
    'calories,distance_m,average_heart_rate\n'
)
SLEEP_HEADER = 'dateOfSleep,startTime,endTime,minutesAsleep,minutesAwake,efficiency,logId,isMainSleep\n'
CALENDAR_HEADER = 'id,calendar_id,summary,location,start,end,all_day,event_type,status,updated\n'
HABITICA_HEADER = (
    'date,ts,task_id,task_type,task_name,value,is_due,completed,scored_up,scored_down\n'
)


@pytest.fixture
def paths(tmp_path):
    p = build.SourcePaths(
        toggl_entries=tmp_path / 'time_entries.csv',
        toggl_pushed=tmp_path / 'pushed.csv',
        toggl_focus_entries=tmp_path / 'focus_entries.csv',
        toggl_focus_pushed=tmp_path / 'focus_pushed.csv',
        exercise=tmp_path / 'exercise.csv',
        sleep=tmp_path / 'sleep.csv',
        habitica_history=tmp_path / 'history.csv',
        calendar=tmp_path / 'calendar.csv',
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
    # 区切り日（2026-10-27）以降は Focus。10-27 の migrate 分は Track にも別 ID で居る
    p.toggl_entries.write_text(
        p.toggl_entries.read_text()
        + '4600000001,2026-10-27 05:51:00,2026-10-27 06:10:00,1140,サイクリング,サイクリング,auto\n'
        + '4600000002,2026-10-27 09:00:00,2026-10-27 10:00:00,3600,読書,読書,\n'
    )
    p.toggl_focus_entries.write_text(
        FOCUS_HEADER
        + 'f1,2026-10-27 05:51:00,2026-10-27 06:10:00,1140,サイクリング,サイクリング,auto\n'
        + 'f2,2026-10-27 09:00:00,2026-10-27 10:00:00,3600,読書,読書,\n'
        + 'f3,2026-10-29 07:00:00,2026-10-29 07:30:00,1800,筋トレ,筋トレ,auto\n'
        + 'f4,2026-10-30 07:00:00,2026-10-30 08:00:00,3600,日記,日記,"deep,auto"\n'
        + 'f5,2026-10-30 09:00:00,2026-10-30 09:30:00,1800,運動,運動,\n'
        + 'f6,2026-10-31 09:00:00,2026-10-31 09:30:00,1800,運動,運動,\n'
    )
    p.toggl_focus_pushed.write_text(
        PUSHED_HEADER
        + 'googlehealth_exercise,9,f5,2026-10-30T09:00:00+09:00,2026-10-30T10:00:00+09:00\n'
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
    p.calendar.write_text(
        CALENDAR_HEADER
        + 'a1,primary,宿泊,,2026-10-13,2026-10-16,True,default,confirmed,2026-10-01T00:00:00Z\n'
        + 'a2,primary,会食,渋谷,2026-10-11T19:00:00+09:00,2026-10-11T21:30:00+09:00,'
          'False,default,confirmed,2026-10-01T00:00:00Z\n'
    )
    return p


def build_lines(paths, tmp_path):
    out = tmp_path / 'events.jsonl'
    build.write_jsonl(build.merge(build.collect(paths)), out)
    return [json.loads(line) for line in out.read_text().splitlines()]


def test_toggl_naive_is_jst_not_utc(paths):
    events = toggl_events(paths)
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


def toggl_events(paths):
    return sources.toggl_events(paths.toggl_entries, paths.toggl_pushed,
                                paths.toggl_focus_entries, paths.toggl_focus_pushed)


def test_pushed_toggl_entry_is_dropped(paths):
    ids = [e['attrs']['id'] for e in toggl_events(paths)]
    assert '4578749526' not in ids
    assert 'f5' not in ids  # Focus 台帳の ID


def test_toggl_switches_source_at_cutover_without_duplicates(paths):
    ids = [e['attrs']['id'] for e in toggl_events(paths)]
    # 区切り前は Track、以降は Focus。10-27 の読書は両ファイルにあるが Focus 側の1本だけ
    assert '4509467120' in ids
    assert '4600000002' not in ids
    assert ids.count('f2') == 1
    assert 'f6' in ids
    starts = [(e['start'], e['name']) for e in toggl_events(paths)]
    assert len(starts) == len(set(starts))


def test_auto_tagged_focus_rows_are_dropped(paths):
    ids = [e['attrs']['id'] for e in toggl_events(paths)]
    assert not {'f1', 'f3', 'f4'} & set(ids)
    assert '4600000001' not in ids  # Track 側の区切り後の行も出さない


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
    if field == 'toggl_entries':
        paths.toggl_focus_entries.unlink()
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
    inputs = [paths.toggl_entries, paths.toggl_pushed, paths.toggl_focus_entries,
              paths.toggl_focus_pushed, paths.exercise,
              paths.sleep, paths.habitica_history]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    build_lines(paths, tmp_path)
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs} == before


def test_calendar_events_are_aware_with_kinds(paths, tmp_path):
    lines = [line for line in build_lines(paths, tmp_path) if line['source'] == 'calendar']
    by_name = {line['name']: line for line in lines}
    assert by_name['宿泊']['kind'] == 'all_day'
    assert by_name['宿泊']['start'] == '2026-10-13T00:00:00+09:00'
    assert by_name['宿泊']['end'] == '2026-10-16T00:00:00+09:00'
    assert by_name['会食']['kind'] == 'timed'
    assert by_name['会食']['start'] == '2026-10-11T19:00:00+09:00'
    assert by_name['会食']['attrs'] == {'location': '渋谷', 'event_type': 'default'}


def test_empty_calendar_is_reported_as_empty_source(paths):
    paths.calendar.write_text(CALENDAR_HEADER)
    assert 'calendar' in build.empty_sources(build.collect(paths))
