"""
GPSLogger の GPX（スマホ → Syncthing → vaio の GPSLOGGER_DIR）を private へ写す対象を決める

GPSLogger は1日1ファイル `YYYYMMDD.gpx` を書き足していく。当日のファイルは書き途中で、
Dawarich は同じ名前を二度取り込まないので、写すのは前日までに限る。
同期の遅れで前日のファイルが後から伸びることがあるので、元が大きくなったら写し直す。
元が小さくなった・消えたときは写しを残す（スマホ側の削除を正本の欠落にしない）。
写し直したファイルは Dawarich には上げ直されない（import 名が同じなので）。伸びた分を入れるときは
Dawarich 側でその import を消してから import-routes を流す。

src が network / fused の点は数百m〜数km 飛ぶので、Dawarich へ上げるときだけ drop_jumps で除く。
data/ の写し（正本）は生のまま持つ。
"""

import bisect
import datetime as dt
import io
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

_NAME_RE = re.compile(r'^(\d{4})(\d{2})(\d{2})\.gpx$')


def dest_name(src: Path) -> str | None:
    m = _NAME_RE.match(src.name)
    return f'{m[1]}-{m[2]}-{m[3]}.gpx' if m else None


def to_copy(src_dir: Path, dest_dir: Path, today: dt.date) -> list[tuple[Path, Path]]:
    pairs = []
    for src in sorted(src_dir.glob('*.gpx')):
        name = dest_name(src)
        if name is None or dt.date.fromisoformat(name[:10]) >= today:
            continue
        dest = dest_dir / name
        if not dest.exists() or src.stat().st_size > dest.stat().st_size:
            pairs.append((src, dest))
    return pairs


# 前後の gps 点を探す範囲。180秒では数分続く network の飛びの間に gps 点が入らず見逃した
WINDOW_SEC = 300
# 前後の gps 点を結ぶ線からの許容のずれ。network の飛びは中央値188m で、歩行の線のぶれはこれより小さい
MAX_DEVIATION_M = 150
# 前後に gps 点が無いときの許容速度。電車の区間（gps が取れない）を消さないよう緩く取る
MAX_SPEED_KMH = 150

_EARTH_RADIUS_M = 6371000


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def drop_jumps(gpx: bytes) -> tuple[bytes, int]:
    """gps 以外の点のうち、前後の gps 点や直前の点から飛んだものを除いた GPX と除いた点数を返す

    gps の点は落とさない。trkseg の構造と他の要素はそのまま残す。時刻の無い点は判定しない。
    """
    root = ET.fromstring(gpx)
    ns = root.tag[1:].split('}')[0] if root.tag.startswith('{') else ''
    q = (lambda tag: f'{{{ns}}}{tag}') if ns else (lambda tag: tag)

    pts = []
    for seg in root.iter(q('trkseg')):
        for el in seg.findall(q('trkpt')):
            time = el.findtext(q('time'))
            if not time:
                continue
            t = dt.datetime.fromisoformat(time.replace('Z', '+00:00')).timestamp()
            pts.append((t, len(pts), seg, el, float(el.get('lat')), float(el.get('lon')),
                        el.findtext(q('src'))))
    pts.sort(key=lambda r: (r[0], r[1]))

    gps = [r for r in pts if r[6] == 'gps']
    gps_t = [r[0] for r in gps]
    dropped, last = 0, None
    for r in pts:
        t, _, seg, el, lat, lon, src = r
        bad = False
        if src != 'gps':
            i = bisect.bisect_right(gps_t, t)
            g0 = gps[i - 1] if i > 0 and t - gps_t[i - 1] <= WINDOW_SEC else None
            j = bisect.bisect_left(gps_t, t)
            g1 = gps[j] if j < len(gps) and gps_t[j] - t <= WINDOW_SEC else None
            if g0 and g1:
                span = g1[0] - g0[0]
                f = 0 if span == 0 else (t - g0[0]) / span
                ilat = g0[4] + (g1[4] - g0[4]) * f
                ilon = g0[5] + (g1[5] - g0[5]) * f
                bad = _haversine_m(ilat, ilon, lat, lon) > MAX_DEVIATION_M
            elif last is not None:
                speed = _haversine_m(last[4], last[5], lat, lon) / max(t - last[0], 1) * 3.6
                bad = speed > MAX_SPEED_KMH
        if bad:
            seg.remove(el)
            dropped += 1
        else:
            last = r

    if ns:
        ET.register_namespace('', ns)
    out = io.BytesIO()
    ET.ElementTree(root).write(out, xml_declaration=True, encoding='UTF-8')
    return out.getvalue(), dropped
