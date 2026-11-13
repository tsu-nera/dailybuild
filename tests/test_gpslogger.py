"""
GPSLogger の GPX を写す対象と、Dawarich アプリの点の写しのテスト

当日の書き途中のファイルを写さないこと（Dawarich は同じ名前を二度取り込まない）、
伸びたら写し直し、縮んでも写しを削らないこと、アプリの点を二重に入れず古い行を消さないことを確認する。
"""

import datetime as dt

import pandas as pd

from lib import gpslogger
from lib.dawarich import app_points

TODAY = dt.date(2026, 11, 14)


def _write(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x' * size)


def test_skips_today_and_foreign_names(tmp_path):
    src, dest = tmp_path / 'src', tmp_path / 'dest'
    _write(src / '20261113.gpx', 10)
    _write(src / '20261114.gpx', 10)        # 当日（書き途中）
    _write(src / 'notes.gpx', 10)
    assert [d.name for _, d in gpslogger.to_copy(src, dest, TODAY)] == ['2026-11-13.gpx']


def test_recopies_only_when_source_grew(tmp_path):
    src, dest = tmp_path / 'src', tmp_path / 'dest'
    _write(src / '20261111.gpx', 10); _write(dest / '2026-11-11.gpx', 10)   # 同じ
    _write(src / '20261112.gpx', 20); _write(dest / '2026-11-12.gpx', 10)   # 同期の遅れで伸びた
    _write(src / '20261113.gpx', 5);  _write(dest / '2026-11-13.gpx', 10)   # 縮んだ（写しを削らない）
    assert [d.name for _, d in gpslogger.to_copy(src, dest, TODAY)] == ['2026-11-12.gpx']


def test_app_points_merge_keeps_old_rows_without_duplicates(tmp_path):
    path = tmp_path / 'app_points.csv'
    old = pd.DataFrame([{'timestamp': '2026-11-12T19:18:32+09:00', 'latitude': '35.5982832',
                         'longitude': '139.6114954', 'accuracy': '30'}])
    old.to_csv(path, index=False)
    # DB を作り直して古い点が消えた後に、同じ点＋新しい点が届く
    new = pd.DataFrame([{'timestamp': '2026-11-12T19:18:32+09:00', 'latitude': '35.5982832',
                         'longitude': '139.6114954', 'accuracy': '30'},
                        {'timestamp': '2026-11-13T07:21:46+09:00', 'latitude': '35.6',
                         'longitude': '139.6', 'accuracy': '100'}])
    app_points.merge(new.iloc[1:].to_dict('records'), path).to_csv(path, index=False)
    merged = app_points.merge(new.to_dict('records'), path)
    assert len(merged) == 2
    assert merged['latitude'].tolist() == ['35.5982832', '35.6']
