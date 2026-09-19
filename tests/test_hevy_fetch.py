"""
scripts/hevy.py fetch のテスト（Issue #153）

Hevy の export は全件で、取得は単純置換になる。置換は取り返しがつかないので
「新しい export の方が行数が少ないときに黙って上書きしない」ことを守る。
Drive が同名ファイルを重複させる（上書きしない）点も、最新を選び損ねると
古い export で正本を巻き戻すため、並び順の指定を検査する。
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.clients import gdrive_client


def _load_script():
    path = BASE_DIR / 'scripts' / 'hevy.py'
    spec = importlib.util.spec_from_file_location('hevy_script', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['hevy_script'] = module
    spec.loader.exec_module(module)
    return module


hevy = _load_script()

WORKOUT_HEADER = (
    'title,start_time,end_time,description,exercise_title,superset_id,'
    'exercise_notes,set_index,set_type,weight_kg,reps,distance_km,'
    'duration_seconds,rpe\n'
)


def workout_rows(count):
    row = ('夜,"16 9月 2026, 18:48","16 9月 2026, 18:59",,ベンチプレス,,,'
           '{i},normal,30,10,,,\n')
    return WORKOUT_HEADER + ''.join(row.format(i=i) for i in range(count))


class FakeFilesApi:
    def __init__(self, files):
        self.files = files
        self.queries = []

    def list(self, **kwargs):
        self.queries.append(kwargs)
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


def test_latest_file_asks_drive_for_newest_first():
    # Drive は同名アップロードを別 ID で並べる。名前だけでは1件に決まらない
    service = FakeService([
        {'id': 'new', 'name': 'workout_data.csv',
         'createdTime': '2026-09-19T07:13:36.129Z', 'size': '143203'},
        {'id': 'old', 'name': 'workout_data.csv',
         'createdTime': '2026-09-06T10:08:03.744Z', 'size': '141857'},
    ])

    found = gdrive_client.latest_file(service, 'folder-id', 'workout_data.csv')

    assert found['id'] == 'new'
    assert service.files().queries[0]['orderBy'] == 'createdTime desc'


def test_latest_file_raises_when_nothing_matches():
    # 0件で正常終了すると、取得できていないことに気づけない
    service = FakeService([])
    with pytest.raises(gdrive_client.GoogleDriveError):
        gdrive_client.latest_file(service, 'folder-id', 'workout_data.csv')


def test_stale_export_warns(caplog):
    # export を忘れた週は、古い CSV のまま「今週0回」に見える
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=9)).isoformat()
    meta = {'name': 'workout_data.csv', 'createdTime': old.replace('+00:00', 'Z')}

    with caplog.at_level('WARNING'):
        age = hevy._warn_if_stale(meta)

    assert age == 9
    assert 'export' in caplog.text


def test_fresh_export_does_not_warn(caplog):
    fresh = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
    meta = {'name': 'workout_data.csv', 'createdTime': fresh.replace('+00:00', 'Z')}

    with caplog.at_level('WARNING'):
        hevy._warn_if_stale(meta)

    assert caplog.text == ''


@pytest.fixture
def fetch_env(tmp_path, monkeypatch):
    """Drive を叩かずに _fetch_one の置換判定だけを回す"""
    dest = tmp_path / 'workouts.csv'

    def fake_latest_file(service, folder_id, name):
        return {'id': 'file-id', 'name': name,
                'createdTime': '2026-09-19T07:13:36.129Z', 'size': '1'}

    monkeypatch.setattr(hevy.gdrive_client, 'latest_file', fake_latest_file)
    return dest


def run_fetch(dest, content, force=False):
    import lib.hevy_csv as hevy_csv

    def fake_download(service, file_id):
        return content.encode()

    original = hevy.gdrive_client.download_file
    hevy.gdrive_client.download_file = fake_download
    try:
        return hevy._fetch_one(
            service=None, folder_id='folder-id', drive_name='workout_data.csv',
            dest=dest, parse=hevy_csv.parse_hevy_csv,
            write=hevy._write_verbatim, force=force,
        )
    finally:
        hevy.gdrive_client.download_file = original


def test_fewer_rows_does_not_overwrite(fetch_env):
    dest = fetch_env
    dest.write_text(workout_rows(5))

    written = run_fetch(dest, workout_rows(3))

    assert written is False
    assert dest.read_text() == workout_rows(5)


def test_fewer_rows_overwrites_with_force(fetch_env):
    dest = fetch_env
    dest.write_text(workout_rows(5))

    written = run_fetch(dest, workout_rows(3), force=True)

    assert written is True
    assert dest.read_text() == workout_rows(3)


def test_more_rows_replaces_the_file(fetch_env):
    dest = fetch_env
    dest.write_text(workout_rows(5))

    written = run_fetch(dest, workout_rows(9))

    assert written is True
    assert dest.read_text() == workout_rows(9)


def test_broken_export_leaves_the_existing_file_untouched(fetch_env):
    # パースできない export で正本を潰さない（日付が壊れているケース）
    dest = fetch_env
    dest.write_text(workout_rows(5))
    broken = WORKOUT_HEADER + (
        '夜,"2026/09/16 18:48","2026/09/16 18:59",,ベンチプレス,,,0,normal,30,10,,,\n'
    )

    with pytest.raises(ValueError):
        run_fetch(dest, broken)

    assert dest.read_text() == workout_rows(5)
    assert not list(dest.parent.glob('.*.download'))
