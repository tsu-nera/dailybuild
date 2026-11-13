"""
GPSLogger の GPX（スマホ → Syncthing → vaio の GPSLOGGER_DIR）を private へ写す対象を決める

GPSLogger は1日1ファイル `YYYYMMDD.gpx` を書き足していく。当日のファイルは書き途中で、
Dawarich は同じ名前を二度取り込まないので、写すのは前日までに限る。
同期の遅れで前日のファイルが後から伸びることがあるので、元が大きくなったら写し直す。
元が小さくなった・消えたときは写しを残す（スマホ側の削除を正本の欠落にしない）。
写し直したファイルは Dawarich には上げ直されない（import 名が同じなので）。伸びた分を入れるときは
Dawarich 側でその import を消してから import-routes を流す。
"""

import datetime as dt
import re
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
