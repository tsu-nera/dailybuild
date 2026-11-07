"""
Last.fm scrobble（Issue #204）のマージのテスト

取り直しで二重に入れない・再生中の曲を確定した scrobble として入れない・
API に無い行を消さない・uts を数値に化けさせないことを確認する。
"""

import pandas as pd

from lib.lastfm import store


def _track(uts, name='Song', artist='Artist', nowplaying=False):
    t = {
        'artist': {'mbid': '', '#text': artist},
        'album': {'mbid': 'a1', '#text': 'Album'},
        'mbid': '', 'name': name, 'url': f'https://www.last.fm/music/{artist}/_/{name}',
    }
    if nowplaying:
        t['@attr'] = {'nowplaying': 'true'}
    else:
        t['date'] = {'uts': str(uts), '#text': ''}
    return t


def _ingest(tracks, csv_path):
    return store.save_merged(store.build_dataframe(tracks), csv_path=csv_path)


def test_refetching_overlapping_window_does_not_add_rows(tmp_path):
    csv = tmp_path / 'scrobbles.csv'
    _ingest([_track(1762480000, 'A'), _track(1762480300, 'B')], csv)
    _ingest([_track(1762480300, 'B'), _track(1762480600, 'C')], csv)

    df = store.load_scrobbles(csv)
    assert list(df['track']) == ['A', 'B', 'C']


def test_nowplaying_is_not_written(tmp_path):
    csv = tmp_path / 'scrobbles.csv'
    _ingest([_track(None, 'Now', nowplaying=True), _track(1762480000, 'Done')], csv)

    assert list(store.load_scrobbles(csv)['track']) == ['Done']


def test_rows_missing_from_refetch_are_kept(tmp_path):
    csv = tmp_path / 'scrobbles.csv'
    _ingest([_track(1762480000, 'A'), _track(1762480300, 'B')], csv)
    _ingest([], csv)
    _ingest([_track(1762480300, 'B')], csv)

    assert len(store.load_scrobbles(csv)) == 2


def test_same_song_played_twice_is_two_rows(tmp_path):
    csv = tmp_path / 'scrobbles.csv'
    _ingest([_track(1762480000, 'A'), _track(1762480300, 'A')], csv)

    assert len(store.load_scrobbles(csv)) == 2


def test_uts_stays_integer_string_and_played_at_is_jst(tmp_path):
    csv = tmp_path / 'scrobbles.csv'
    _ingest([_track(1762480000, 'A')], csv)

    raw = pd.read_csv(csv, dtype=str)
    assert raw.loc[0, 'uts'] == '1762480000'
    assert raw.loc[0, 'played_at'].endswith('+09:00')
    assert store.last_uts(csv) == 1762480000


def test_last_uts_is_none_without_csv(tmp_path):
    assert store.last_uts(tmp_path / 'missing.csv') is None
