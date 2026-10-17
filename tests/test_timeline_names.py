"""
Timeline の場所の名前（places.csv / names サブコマンド / place_labels）のテスト（Issue #214）

壊れる場所は「引いた ID を二度引く」「自宅や一度きりの場所に課金する」「途中の失敗で
引けた分を捨てる」「キー無しで日次を落とす」「辞書が無いとき表示が変わる」。
HTTP はフェイク（実 API は叩かない）。place ID と名前はすべて架空の値。
"""

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest
import requests

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib import timeline as tl
from lib.clients import places_client


def _load_script():
    path = BASE_DIR / 'scripts' / 'timeline.py'
    spec = importlib.util.spec_from_file_location('timeline_script_names', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['timeline_script_names'] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def make_visits(spec):
    """spec: [(place_id, 訪問日リスト, semantic_type)]"""
    rows = []
    for place_id, days, sem in spec:
        for day in days:
            rows.append({
                'start_time': f'{day}T10:00:00.000+09:00',
                'end_time': f'{day}T11:00:00.000+09:00',
                'duration_min': 60.0, 'place_id': place_id,
                'semantic_type': sem, 'probability': 0.5,
                'lat': 35.0, 'lon': 139.0,
            })
    return pd.DataFrame(rows, columns=tl.VISIT_COLUMNS)


def place_row(place_id, name='', status='ok', ptype=''):
    return {'place_id': place_id, 'display_name': name, 'primary_type': ptype,
            'status': status, 'resolved_at': '2026-10-17T00:00:00+09:00'}


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'{self.status_code}')


class FakeSession:
    """place_id → FakeResponse。呼び出しを記録する"""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({'url': url, 'headers': headers, 'params': params})
        return self.responses[url.rsplit('/', 1)[1]]


D = ['2026-09-01', '2026-09-02', '2026-09-03']


class TestPlacesToResolve:
    def test_exclusions_ordering_and_limit(self):
        visits = make_visits([
            ('p-many', D + ['2026-09-04'], 'UNKNOWN'),
            ('p-three-b', D, 'UNKNOWN'),
            ('p-three-a', D, 'UNKNOWN'),
            ('p-two', D[:2], 'UNKNOWN'),
            ('p-once', D[:1], 'UNKNOWN'),
            ('p-home', D, 'HOME'),
            ('p-inferred-home', D, 'INFERRED_HOME'),
            ('p-known', D, 'UNKNOWN'),
            ('p-missing', D, 'UNKNOWN'),
        ])
        places = pd.DataFrame([place_row('p-known', 'x'),
                               place_row('p-missing', status='not_found')])
        assert tl.places_to_resolve(visits, places, 10) == [
            'p-many', 'p-three-a', 'p-three-b', 'p-two']
        assert tl.places_to_resolve(visits, places, 2) == ['p-many', 'p-three-a']

    def test_same_day_visits_count_once(self):
        visits = make_visits([('p-a', ['2026-09-01', '2026-09-01'], 'UNKNOWN')])
        assert tl.places_to_resolve(visits, tl.read_places('/nonexistent'), 10) == []

    def test_home_in_any_row_excludes(self):
        visits = pd.concat([make_visits([('p-a', D, 'UNKNOWN')]),
                            make_visits([('p-a', D[:1], 'HOME')])])
        assert tl.places_to_resolve(visits, tl.read_places('/nonexistent'), 10) == []


class TestPlacesCsv:
    def test_read_missing_returns_empty_with_columns(self, tmp_path):
        df = tl.read_places(tmp_path / 'places.csv')
        assert df.empty and list(df.columns) == tl.PLACE_COLUMNS

    def test_append_keeps_existing_and_skips_duplicates(self, tmp_path):
        path = tmp_path / 'sub' / 'places.csv'
        tl.append_places(path, [place_row('p-a', 'A')])
        tl.append_places(path, [place_row('p-a', 'CHANGED'), place_row('p-b', '')])
        df = tl.read_places(path)
        assert list(df['place_id']) == ['p-a', 'p-b']
        assert df.loc[0, 'display_name'] == 'A'
        assert df.loc[1, 'primary_type'] == ''  # 空欄が NaN にならない

    def test_append_empty_does_not_create_file(self, tmp_path):
        path = tmp_path / 'places.csv'
        tl.append_places(path, [])
        assert not path.exists()


class TestPlaceLabels:
    def test_precedence_home_name_id(self):
        visits = make_visits([
            ('p-home', D, 'HOME'),
            ('p-named', D, 'UNKNOWN'),
            ('p-plain', D, 'UNKNOWN'),
            ('p-notfound', D, 'UNKNOWN'),
            ('p-blank', D, 'UNKNOWN'),
        ])
        places = pd.DataFrame([
            place_row('p-home', 'Fake Home Name'),
            place_row('p-named', 'Fake Cafe'),
            place_row('p-notfound', status='not_found'),
            place_row('p-blank', ''),
        ])
        assert tl.place_labels(visits, places) == {
            'p-home': 'HOME', 'p-named': 'Fake Cafe', 'p-plain': 'p-plain',
            'p-notfound': 'p-notfound', 'p-blank': 'p-blank'}

    def test_without_places_unchanged(self):
        visits = make_visits([('p-home', D, 'HOME'), ('p-a', D, 'UNKNOWN')])
        expected = {'p-home': 'HOME', 'p-a': 'p-a'}
        assert tl.place_labels(visits) == expected
        assert tl.place_labels(visits, tl.read_places('/nonexistent')) == expected

    def test_summarize_passes_places(self):
        visits = make_visits([('p-a', D, 'UNKNOWN')])
        places = pd.DataFrame([place_row('p-a', 'Fake Cafe')])
        result = tl.summarize(visits, dt.date(2026, 9, 1), dt.date(2026, 9, 7), places=places)
        assert result['labels'] == {'p-a': 'Fake Cafe'}


class TestGetPlace:
    def test_sends_field_mask_and_language(self):
        session = FakeSession({'ChIJ_fake_a': FakeResponse(
            body={'id': 'ChIJ_fake_a', 'displayName': {'text': 'Fake Cafe'},
                  'primaryType': 'cafe'})})
        got = places_client.get_place('ChIJ_fake_a', 'key-1', session=session)
        call = session.calls[0]
        assert call['url'] == 'https://places.googleapis.com/v1/places/ChIJ_fake_a'
        assert call['headers']['X-Goog-FieldMask'] == 'id,displayName,primaryType'
        assert call['headers']['X-Goog-Api-Key'] == 'key-1'
        assert call['params']['languageCode'] == 'ja'
        assert got == {'display_name': 'Fake Cafe', 'primary_type': 'cafe'}

    def test_missing_primary_type_is_blank(self):
        session = FakeSession({'ChIJ_fake_a': FakeResponse(
            body={'displayName': {'text': 'Fake Spot'}})})
        got = places_client.get_place('ChIJ_fake_a', 'k', session=session)
        assert got == {'display_name': 'Fake Spot', 'primary_type': ''}

    def test_404_raises_not_found(self):
        session = FakeSession({'ChIJ_fake_a': FakeResponse(404)})
        with pytest.raises(places_client.PlaceNotFound):
            places_client.get_place('ChIJ_fake_a', 'k', session=session)

    def test_other_error_raises_http_error(self):
        session = FakeSession({'ChIJ_fake_a': FakeResponse(403)})
        with pytest.raises(requests.HTTPError):
            places_client.get_place('ChIJ_fake_a', 'k', session=session)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """VISITS_CSV / PLACES_CSV を tmp に向け、キーを設定する"""
    visits_csv = tmp_path / 'visits.csv'
    places_csv = tmp_path / 'places.csv'
    monkeypatch.setattr(script, 'VISITS_CSV', visits_csv)
    monkeypatch.setattr(script, 'PLACES_CSV', places_csv)
    monkeypatch.setattr(script, 'require_private_path', lambda p: p)
    monkeypatch.setattr(script, '_api_key', lambda: 'key-1')
    make_visits([
        ('ChIJ_fake_a', D, 'UNKNOWN'),
        ('ChIJ_fake_b', D[:2], 'UNKNOWN'),
        ('ChIJ_fake_c', D[:2], 'UNKNOWN'),
    ]).to_csv(visits_csv, index=False)
    return places_csv


def ok(name, ptype=None):
    body = {'displayName': {'text': name}}
    if ptype:
        body['primaryType'] = ptype
    return FakeResponse(body=body)


class TestNamesCommand:
    def test_writes_rows_and_missing_primary_type_is_blank(self, env):
        session = FakeSession({'ChIJ_fake_a': ok('Fake Cafe', 'cafe'),
                               'ChIJ_fake_b': ok('Fake Spot'),
                               'ChIJ_fake_c': ok('Fake Park', 'park')})
        assert script.names(limit=10, session=session) == 0
        df = tl.read_places(env)
        assert list(df['place_id']) == ['ChIJ_fake_a', 'ChIJ_fake_b', 'ChIJ_fake_c']
        assert set(df['status']) == {'ok'}
        assert df.set_index('place_id').loc['ChIJ_fake_b', 'primary_type'] == ''
        assert (df['resolved_at'] != '').all()

    def test_limit(self, env):
        session = FakeSession({'ChIJ_fake_a': ok('Fake Cafe')})
        assert script.names(limit=1, session=session) == 0
        assert len(session.calls) == 1

    def test_not_found_recorded_and_not_retried(self, env):
        session = FakeSession({'ChIJ_fake_a': FakeResponse(404),
                               'ChIJ_fake_b': ok('Fake Spot'),
                               'ChIJ_fake_c': ok('Fake Park')})
        assert script.names(limit=10, session=session) == 0
        df = tl.read_places(env).set_index('place_id')
        assert df.loc['ChIJ_fake_a', 'status'] == 'not_found'
        assert df.loc['ChIJ_fake_a', 'display_name'] == ''

        again = FakeSession({})
        assert script.names(limit=10, session=again) == 0
        assert again.calls == []

    def test_midway_error_keeps_earlier_rows_and_fails(self, env):
        session = FakeSession({'ChIJ_fake_a': ok('Fake Cafe'),
                               'ChIJ_fake_b': FakeResponse(403)})
        assert script.names(limit=10, session=session) != 0
        df = tl.read_places(env)
        assert list(df['place_id']) == ['ChIJ_fake_a']

    def test_missing_key_makes_no_http_call(self, env, monkeypatch):
        monkeypatch.setattr(script, '_api_key', lambda: None)
        session = FakeSession({})
        assert script.names(limit=10, session=session) == 0
        assert session.calls == []
        assert not env.exists()

    def test_missing_visits_csv_is_error(self, env):
        script.VISITS_CSV.unlink()
        assert script.names(limit=10, session=FakeSession({})) == 1
