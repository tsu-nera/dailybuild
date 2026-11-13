"""
運動の軌跡（TCX）を取りに行く対象と、Dawarich へ上げる対象のテスト

TCX は取り直さないこと、軌跡の無い運動を取りに行かないこと、
Dawarich に同名の import があるファイルを上げ直さないこと（Dawarich は同名を別名で受け付ける）を確認する。
"""

import pandas as pd

from lib import exercise_route
from lib.clients import dawarich_client
from lib.clients.dawarich_client import DawarichClient, not_imported


def _exercise_csv(tmp_path, rows):
    path = tmp_path / 'exercise.csv'
    pd.DataFrame(rows, columns=['id', 'start', 'has_gps']).to_csv(path, index=False)
    return path


def test_pending_skips_no_gps_and_already_fetched(tmp_path):
    csv = _exercise_csv(tmp_path, [
        ('9219443015719916624', '2026-11-12 21:16:07+09:00', 'True'),
        ('6568143225818121640', '2026-11-12 18:16:53+09:00', 'True'),
        ('6720973959551718080', '2026-11-12 07:50:17+09:00', ''),      # 自動検出
        ('3127012252622520776', '2026-11-12 18:13:51+09:00', 'False'),
    ])
    tcx_dir = tmp_path / 'tcx'
    tcx_dir.mkdir()
    (tcx_dir / '2026-11-12_6568143225818121640.tcx').write_text('<x/>')

    assert exercise_route.pending(csv, tcx_dir) == [
        ('9219443015719916624', '2026-11-12_9219443015719916624.tcx')]


def test_pending_keeps_19_digit_id_exact(tmp_path):
    # float に落ちると末尾が丸まり、別の運動の TCX を取りに行く
    csv = _exercise_csv(tmp_path, [('9219443015719916624', '2026-11-12 21:16:07+09:00', 'True')])
    assert exercise_route.pending(csv, tmp_path / 'tcx')[0][0] == '9219443015719916624'


def test_not_imported_skips_names_already_in_dawarich(tmp_path):
    a, b = tmp_path / '2026-11-12_1.tcx', tmp_path / '2026-11-12_2.tcx'
    assert not_imported([b, a], {'2026-11-12_1.tcx', 'Timeline.json'}) == [b]


class _Resp:
    def __init__(self, body, pages):
        self._body, self.headers = body, {'X-Total-Pages': str(pages)}

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


def test_import_names_reads_every_page(monkeypatch):
    # 1ページ目だけ見ると、古い import を未投入と誤って二重に上げる
    pages = {1: [{'name': 'a.tcx'}], 2: [{'name': 'b.tcx'}]}
    monkeypatch.setattr(dawarich_client.requests, 'get',
                        lambda url, headers, params, timeout: _Resp(pages[params['page']], 2))
    assert DawarichClient('http://x', 'k').import_names() == {'a.tcx', 'b.tcx'}


def test_import_names_with_no_imports(monkeypatch):
    monkeypatch.setattr(dawarich_client.requests, 'get',
                        lambda url, headers, params, timeout: _Resp([], 0))
    assert DawarichClient('http://x', 'k').import_names() == set()


def test_precise_imports_skips_gpx_and_unfinished():
    # GPX は1日分を覆うので基準にすると1日中の他の点が消える
    imports = [{'name': 'a.tcx', 'status': 'completed'}, {'name': 'b.tcx', 'status': 'processing'},
               {'name': '2026-11-12.gpx', 'status': 'completed'}, {'name': 'Timeline.json', 'status': 'completed'}]
    assert [i['name'] for i in dawarich_client.precise_imports(imports, ('.tcx',))] == ['a.tcx']


def test_overlapping_others_keeps_every_base_point():
    # 時間の重なる2本の軌跡（Fitbit とサイコン）が互いの点を消し合わないこと
    window = [{'id': 1}, {'id': 2}, {'id': 3}, {'id': 4}]
    assert dawarich_client.overlapping_others(window, keep_ids={1, 3}) == [{'id': 2}, {'id': 4}]
