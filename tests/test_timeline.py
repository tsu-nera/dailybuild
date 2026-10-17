"""
Timeline の取り込み（lib/timeline.py と scripts/timeline.py fetch）のテスト（Issue #213）

export は毎回全期間で、同じ時間帯の visit が hierarchyLevel 違いで重複して出る。
壊れる場所は「重複を二重に数える」「再取り込みで行が増える」「新しい export に
無い日付の古い訪問を消す」「変わっていない export を毎日落とす」の4つ。
place ID と座標はすべて架空の値。
"""

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib import timeline as tl


def _load_script():
    path = BASE_DIR / 'scripts' / 'timeline.py'
    spec = importlib.util.spec_from_file_location('timeline_script', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['timeline_script'] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def visit(start, end, place='place-a', level=0, sem='UNKNOWN', prob=0.5,
          latlng='35.0001°, 139.0002°'):
    return {
        'startTime': start, 'endTime': end,
        'startTimeTimezoneUtcOffsetMinutes': 540,
        'endTimeTimezoneUtcOffsetMinutes': 540,
        'visit': {
            'hierarchyLevel': level, 'probability': 0.9,
            'topCandidate': {
                'placeId': place, 'semanticType': sem, 'probability': prob,
                'placeLocation': {'latLng': latlng},
            },
        },
    }


def export(*segments):
    return json.dumps({
        'semanticSegments': list(segments),
        'rawSignals': [], 'userLocationProfile': {},
    }).encode()


def ts(day, hh='10:00:00', mm_end='11:00:00'):
    return (f'{day}T{hh}.000+09:00', f'{day}T{mm_end}.000+09:00')


# ---- parse_export -------------------------------------------------------

def test_only_hierarchy_level_0_is_kept():
    s, e = ts('2026-10-01')
    df = tl.parse_export(export(
        visit(s, e, level=0),
        visit(s, e, place='place-b', level=1),
        {'startTime': s, 'endTime': e, 'activity': {}},
    ))

    assert len(df) == 1
    assert df.iloc[0]['place_id'] == 'place-a'


def test_degree_string_coordinates_become_floats():
    s, e = ts('2026-10-01')
    df = tl.parse_export(export(visit(s, e, latlng='35.6812°, -139.7671°')))

    assert df.iloc[0]['lat'] == pytest.approx(35.6812)
    assert df.iloc[0]['lon'] == pytest.approx(-139.7671)
    assert list(df.columns) == tl.VISIT_COLUMNS


def test_offset_iso_and_duration_are_kept():
    df = tl.parse_export(export(visit(
        '2026-10-01T10:00:00.000+09:00', '2026-10-01T10:30:30.000+09:00', prob=0.275)))

    row = df.iloc[0]
    assert row['start_time'] == '2026-10-01T10:00:00.000+09:00'
    assert row['duration_min'] == 30.5
    assert row['probability'] == 0.275


def test_missing_semantic_segments_raises():
    with pytest.raises(ValueError):
        tl.parse_export(b'{"rawSignals": []}')


def test_visit_without_required_field_raises():
    s, e = ts('2026-10-01')
    broken = visit(s, e)
    del broken['visit']['topCandidate']['placeLocation']
    with pytest.raises(ValueError):
        tl.parse_export(export(broken))


# ---- fetch --------------------------------------------------------------

class FakeFilesApi:
    def __init__(self, files):
        self.files = files

    def list(self, **kwargs):
        return FakeRequest({'files': self.files})


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeService:
    def __init__(self, files):
        self._files = FakeFilesApi(files)

    def files(self):
        return self._files


def drive_file(modified='2026-10-10T00:00:00.000Z', file_id='file-1'):
    return {'id': file_id, 'name': script.DRIVE_NAME, 'size': '1',
            'createdTime': modified, 'modifiedTime': modified}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(script, 'VISITS_CSV', tmp_path / 'timeline' / 'visits.csv')
    monkeypatch.setattr(script, 'STATE_JSON', tmp_path / 'timeline' / 'fetch_state.json')
    monkeypatch.setattr(script, '_load_folder_id', lambda: 'folder-id')
    # tmp は dailybuild-private 配下ではないので、private 検証は素通りさせる
    monkeypatch.setattr(script, 'require_private_path', lambda p: p)
    monkeypatch.setattr(script, 'ensure_dir', lambda p: p.mkdir(parents=True, exist_ok=True))
    downloads = []

    def run(content, modified='2026-10-10T00:00:00.000Z', file_id='file-1'):
        def fake_download(service, fid):
            downloads.append(fid)
            return content

        monkeypatch.setattr(script.gdrive_client, 'download_file', fake_download)
        return script.fetch(service=FakeService([drive_file(modified, file_id)]))

    run.downloads = downloads
    return run


def test_existing_dates_missing_from_new_export_are_preserved(env):
    s1, e1 = ts('2026-09-01')
    s2, e2 = ts('2026-10-01')
    s3, e3 = ts('2026-10-02')
    env(export(visit(s1, e1, place='old-place'), visit(s2, e2)))
    # 新しい export は 09-01 を持たない。古い訪問を消してはいけない
    env(export(visit(s2, e2), visit(s3, e3)), modified='2026-11-10T00:00:00.000Z')

    df = pd.read_csv(script.VISITS_CSV, dtype={'place_id': str})
    assert sorted(df['start_time'].str[:10]) == ['2026-09-01', '2026-10-01', '2026-10-02']
    assert 'old-place' in set(df['place_id'])


def test_importing_same_export_twice_is_idempotent(env):
    s1, e1 = ts('2026-10-01')
    s2, e2 = ts('2026-10-02')
    content = export(visit(s1, e1), visit(s1, e1, place='place-b', level=1),
                     visit(s2, e2, place='place-c'))

    env(content)
    first = script.VISITS_CSV.read_text()
    # 別の modifiedTime で届いた同じ中身（スキップされず実際に再取り込みされる）
    env(content, modified='2026-10-20T00:00:00.000Z')

    assert len(pd.read_csv(script.VISITS_CSV)) == 2
    assert script.VISITS_CSV.read_text() == first


def test_unchanged_modified_time_skips_download(env):
    s, e = ts('2026-10-01')
    content = export(visit(s, e))

    env(content)
    assert env.downloads == ['file-1']
    env(content)

    assert env.downloads == ['file-1']  # 2回目は落としていない


def test_changed_modified_time_downloads_again(env):
    s, e = ts('2026-10-01')
    content = export(visit(s, e))

    env(content)
    env(content, modified='2026-10-20T00:00:00.000Z')

    assert env.downloads == ['file-1', 'file-1']
    state = json.loads(script.STATE_JSON.read_text())
    assert state == {'id': 'file-1', 'modifiedTime': '2026-10-20T00:00:00.000Z'}


def test_broken_export_leaves_csv_and_state_untouched(env):
    s, e = ts('2026-10-01')
    env(export(visit(s, e)))
    csv_before = script.VISITS_CSV.read_text()
    state_before = script.STATE_JSON.read_text()

    with pytest.raises(ValueError):
        env(b'{"nothing": 1}', modified='2026-10-20T00:00:00.000Z')

    assert script.VISITS_CSV.read_text() == csv_before
    assert script.STATE_JSON.read_text() == state_before


def test_stale_export_warns(caplog):
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=script.STALE_DAYS + 5))
    meta = {'name': script.DRIVE_NAME,
            'modifiedTime': old.isoformat().replace('+00:00', 'Z')}

    with caplog.at_level('WARNING'):
        script._warn_if_stale(meta)

    assert 'export' in caplog.text


# ---- summarize ----------------------------------------------------------

def make_visits(*items):
    """items: (date, place_id, duration_min, semantic_type)"""
    return pd.DataFrame([{
        'start_time': f'{d}T10:00:00.000+09:00',
        'end_time': f'{d}T11:00:00.000+09:00',
        'duration_min': dur, 'place_id': pid, 'semantic_type': sem,
        'probability': 0.5, 'lat': 35.0, 'lon': 139.0,
    } for d, pid, dur, sem in items])


def test_place_leaving_top_is_dropped_and_new_place_is_entered():
    visits = make_visits(
        ('2026-09-28', 'old', 60, 'UNKNOWN'),   # 前期間 (09-24〜09-30) のみ
        ('2026-09-29', 'old', 60, 'UNKNOWN'),
        ('2026-10-02', 'new', 60, 'UNKNOWN'),   # 今期 (10-01〜10-07) のみ
        ('2026-10-03', 'both', 30, 'UNKNOWN'),
        ('2026-09-26', 'both', 30, 'UNKNOWN'),
    )

    result = tl.summarize(visits, dt.date(2026, 10, 1), dt.date(2026, 10, 7))

    assert result['prev_start'] == dt.date(2026, 9, 24)
    assert result['prev_end'] == dt.date(2026, 9, 30)
    assert result['entered'] == ['new']
    assert result['dropped'] == ['old']


def test_ranking_and_first_last_span_all_history():
    visits = make_visits(
        ('2026-01-05', 'a', 10, 'UNKNOWN'),      # 期間外。first_date に効く
        ('2026-10-01', 'a', 10, 'UNKNOWN'),
        ('2026-10-02', 'a', 10, 'UNKNOWN'),
        ('2026-10-01', 'b', 500, 'UNKNOWN'),     # 日数は少ないが長い
        ('2026-10-05', 'a', 10, 'UNKNOWN'),
        ('2026-11-20', 'a', 10, 'UNKNOWN'),      # 期間外。last_date に効く
    )

    cur = tl.summarize(visits, dt.date(2026, 10, 1), dt.date(2026, 10, 7))['current']

    assert list(cur['place_id']) == ['a', 'b']  # 訪問日数が先
    row = cur.iloc[0]
    assert row['visit_days'] == 3
    assert row['duration_min'] == 30
    assert row['first_date'] == '2026-01-05'
    assert row['last_date'] == '2026-11-20'


def test_same_day_visits_count_once_and_ties_break_by_duration_then_id():
    visits = make_visits(
        ('2026-10-01', 'b', 10, 'UNKNOWN'),
        ('2026-10-01', 'b', 10, 'UNKNOWN'),   # 同じ日の2回目は日数に足さない
        ('2026-10-01', 'c', 40, 'UNKNOWN'),
        ('2026-10-01', 'a', 40, 'UNKNOWN'),
    )

    cur = tl.summarize(visits, dt.date(2026, 10, 1), dt.date(2026, 10, 1))['current']

    assert list(cur['visit_days']) == [1, 1, 1]
    assert list(cur['place_id']) == ['a', 'c', 'b']  # 滞在長い順、同着は id 昇順


def test_home_semantic_type_labels_place_as_home():
    visits = make_visits(
        ('2026-10-01', 'h', 60, 'UNKNOWN'),
        ('2026-10-02', 'h', 60, 'INFERRED_HOME'),
        ('2026-10-01', 'w', 60, 'INFERRED_WORK'),
    )

    labels = tl.summarize(visits, dt.date(2026, 10, 1), dt.date(2026, 10, 7))['labels']

    assert labels['h'] == 'HOME'
    assert labels['w'] == 'w'
