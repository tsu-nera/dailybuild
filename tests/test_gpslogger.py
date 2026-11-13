"""
GPSLogger の GPX を写す対象のテスト

当日の書き途中のファイルを写さないこと（Dawarich は同じ名前を二度取り込まない）、
伸びたら写し直し、縮んでも写しを削らないことを確認する。
"""

import datetime as dt
import xml.etree.ElementTree as ET

from lib import gpslogger

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


# --- drop_jumps: 飛んだ点を除く。座標は架空（緯度 0.01 度 ≒ 1.1km） ---

GPX_NS = 'http://www.topografix.com/GPX/1/0'
T0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _gpx(*segs):
    """segs: [(秒, lat, lon, src), ...] のリスト。1つが1つの trkseg"""
    body = ''.join(
        '<trkseg>' + ''.join(
            f'<trkpt lat="{lat}" lon="{lon}"><time>{(T0 + dt.timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%SZ")}'
            f'</time><src>{src}</src></trkpt>'
            for s, lat, lon, src in seg) + '</trkseg>'
        for seg in segs)
    return (f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.0" xmlns="{GPX_NS}">'
            f'<trk><name>t</name>{body}</trk></gpx>').encode()


def test_drop_jumps_keeps_gps_points_even_if_far():
    gpx = _gpx([(0, 10.0, 20.0, 'gps'), (60, 10.1, 20.0, 'gps'), (120, 10.0, 20.0, 'gps')])
    _, dropped = gpslogger.drop_jumps(gpx)
    assert dropped == 0


def test_drop_jumps_drops_network_point_off_the_gps_line():
    gpx = _gpx([(0, 10.0, 20.0, 'gps'), (60, 10.01, 20.0, 'network'),
                (90, 10.0, 20.0002, 'fused'), (120, 10.0, 20.0005, 'gps')])
    _, dropped = gpslogger.drop_jumps(gpx)
    assert dropped == 1   # 1.1km 外れた network だけ。線上の fused は残す


def test_drop_jumps_keeps_train_without_gps():
    # gps の無い区間を 0.015 度/分 ≒ 時速100km で動く（電車）
    gpx = _gpx([(i * 60, 10.0 + i * 0.015, 20.0, 'network') for i in range(10)])
    _, dropped = gpslogger.drop_jumps(gpx)
    assert dropped == 0


def test_drop_jumps_output_is_same_gpx_with_fewer_trkpts():
    gpx = _gpx([(0, 10.0, 20.0, 'gps'), (60, 10.01, 20.0, 'network')],
               [(120, 10.0, 20.0005, 'gps'), (180, 10.0, 20.0007, 'gps')])
    out, dropped = gpslogger.drop_jumps(gpx)
    assert out.startswith(b'<?xml')
    root = ET.fromstring(out)
    assert root.tag == f'{{{GPX_NS}}}gpx'
    assert root.findtext(f'{{{GPX_NS}}}trk/{{{GPX_NS}}}name') == 't'
    segs = root.findall(f'.//{{{GPX_NS}}}trkseg')
    assert [len(s.findall(f'{{{GPX_NS}}}trkpt')) for s in segs] == [1, 2]
    assert dropped == 1
