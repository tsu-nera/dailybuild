"""Hevy CSV パース・保存のテスト（Issue #153）

Hevy の export はアプリのロケールに従い日付フォーマットが変わる。
NaT への素通し（欠測の捏造）を防ぐこと、export の行数減少を
書き込み前に検出することの2点だけを検証する。実 API・実 Drive は
叩かない。
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib import hevy_csv
from lib.hevy import store
from lib.clients import gdrive_client


HEADER = (
    '"title","start_time","end_time","description","exercise_title",'
    '"superset_id","exercise_notes","set_index","set_type","weight_kg",'
    '"reps","distance_km","duration_seconds","rpe"\n'
)


def _row(start_time, end_time, exercise='ベンチプレス (ダンベル)', set_index=0):
    return (
        f'"夜のトレーニング","{start_time}","{end_time}","","{exercise}",,"",'
        f'{set_index},"normal",30,10,,,\n'
    )


def test_parse_hevy_csv_english_locale(tmp_path):
    csv_path = tmp_path / 'workouts.csv'
    csv_path.write_text(
        HEADER + _row('13 Dec 2025, 15:11', '13 Dec 2025, 15:41'))

    df = hevy_csv.parse_hevy_csv(csv_path)

    assert len(df) == 1
    assert df.loc[0, 'start_dt'] == pd.Timestamp('2025-12-13 15:11:00')
    assert df.loc[0, 'end_dt'] == pd.Timestamp('2025-12-13 15:41:00')


def test_parse_hevy_csv_japanese_locale(tmp_path):
    csv_path = tmp_path / 'workouts.csv'
    csv_path.write_text(
        HEADER + _row('5 9月 2026, 20:39', '5 9月 2026, 20:43'))

    df = hevy_csv.parse_hevy_csv(csv_path)

    assert len(df) == 1
    assert df.loc[0, 'start_dt'] == pd.Timestamp('2026-09-05 20:39:00')
    assert df.loc[0, 'end_dt'] == pd.Timestamp('2026-09-05 20:43:00')


def test_parse_hevy_csv_mixed_locale(tmp_path):
    """既存CSV（英語）と新export（日本語）が混在していても両方解釈できる"""
    csv_path = tmp_path / 'workouts.csv'
    csv_path.write_text(
        HEADER
        + _row('13 Dec 2025, 15:11', '13 Dec 2025, 15:41', set_index=0)
        + _row('5 9月 2026, 20:39', '5 9月 2026, 20:43', set_index=1)
    )

    df = hevy_csv.parse_hevy_csv(csv_path)

    assert len(df) == 2
    assert df.loc[0, 'start_dt'] == pd.Timestamp('2025-12-13 15:11:00')
    assert df.loc[1, 'start_dt'] == pd.Timestamp('2026-09-05 20:39:00')


def test_parse_hevy_csv_unparseable_date_raises(tmp_path):
    """NaT へ素通しせず例外で落ちる"""
    csv_path = tmp_path / 'workouts.csv'
    csv_path.write_text(
        HEADER + _row('not a date', '13 Dec 2025, 15:41'))

    with pytest.raises(ValueError, match='start_time'):
        hevy_csv.parse_hevy_csv(csv_path)


def test_save_workouts_no_existing_file_writes_through(tmp_path):
    out_path = tmp_path / 'workouts.csv'
    new_csv = (HEADER + _row('5 9月 2026, 20:39', '5 9月 2026, 20:43')).encode()

    existing_rows, new_rows = store.save_workouts(new_csv, out_path=out_path)

    assert existing_rows == 0
    assert new_rows == 1
    assert out_path.exists()
    assert out_path.read_bytes() == new_csv


def test_save_workouts_shrink_raises_and_does_not_write(tmp_path):
    out_path = tmp_path / 'workouts.csv'
    existing_csv = (
        HEADER
        + _row('13 Dec 2025, 15:11', '13 Dec 2025, 15:41', set_index=0)
        + _row('14 Dec 2025, 15:11', '14 Dec 2025, 15:41', set_index=1)
    )
    out_path.write_text(existing_csv)

    smaller_csv = (HEADER + _row('5 9月 2026, 20:39', '5 9月 2026, 20:43')).encode()

    with pytest.raises(store.WorkoutsShrankError):
        store.save_workouts(smaller_csv, out_path=out_path)

    # 書き込まれておらず、既存ファイルが変化していないこと
    assert out_path.read_text() == existing_csv


def test_save_workouts_force_overwrites_even_when_shrinking(tmp_path):
    out_path = tmp_path / 'workouts.csv'
    existing_csv = (
        HEADER
        + _row('13 Dec 2025, 15:11', '13 Dec 2025, 15:41', set_index=0)
        + _row('14 Dec 2025, 15:11', '14 Dec 2025, 15:41', set_index=1)
    )
    out_path.write_text(existing_csv)

    smaller_csv = (HEADER + _row('5 9月 2026, 20:39', '5 9月 2026, 20:43')).encode()

    existing_rows, new_rows = store.save_workouts(
        smaller_csv, out_path=out_path, force=True)

    assert existing_rows == 2
    assert new_rows == 1
    assert out_path.read_bytes() == smaller_csv


class _FakeFilesList:
    def __init__(self, files):
        self._files = files

    def execute(self):
        return {'files': self._files}


class _FakeFilesRequest:
    def __init__(self, content):
        self._content = content

    def execute(self):
        return self._content


class _FakeFiles:
    def __init__(self, files, content_by_id):
        self._files = files
        self._content_by_id = content_by_id

    def list(self, q=None, orderBy=None, fields=None):
        # createdTime desc を模してソート済みで返す（実 API と同じ契約）
        files = sorted(self._files, key=lambda f: f['createdTime'], reverse=True)
        return _FakeFilesList(files)

    def get_media(self, fileId):
        return _FakeFilesRequest(self._content_by_id[fileId])


class _FakeDriveService:
    def __init__(self, files, content_by_id):
        self._files = files
        self._content_by_id = content_by_id

    def files(self):
        return _FakeFiles(self._files, self._content_by_id)


def test_download_latest_picks_newest_created_time(monkeypatch):
    # Drive は同名ファイルを上書きせず重複作成するため、createdTime が
    # 一番新しいものを採る必要がある
    files = [
        {'id': 'old-id', 'name': 'workout_data.csv', 'createdTime': '2026-09-01T10:00:00Z'},
        {'id': 'new-id', 'name': 'workout_data.csv', 'createdTime': '2026-09-05T10:00:00Z'},
    ]
    content_by_id = {'old-id': b'old content', 'new-id': b'new content'}
    service = _FakeDriveService(files, content_by_id)

    class _FakeDownloader:
        def __init__(self, buf, request):
            self._buf = buf
            self._request = request

        def next_chunk(self):
            self._buf.write(self._request.execute())
            return None, True

    monkeypatch.setattr(gdrive_client, 'MediaIoBaseDownload', _FakeDownloader)

    result = gdrive_client.download_latest(service, 'folder-id', 'workout_data.csv')

    assert result == b'new content'


def test_download_latest_raises_when_not_found():
    service = _FakeDriveService([], {})

    with pytest.raises(FileNotFoundError):
        gdrive_client.download_latest(service, 'folder-id', 'workout_data.csv')
