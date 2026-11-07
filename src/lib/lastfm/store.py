"""
Last.fm scrobble CSV の読み書き

data/lastfm/scrobbles.csv（dailybuild-private への symlink）に1行=1 scrobble で積む。
マージのキーは (uts, artist, track)。

取り直しは置換でなく upsert にする。Last.fm 側で scrobble を消しても、API に無いことは
CSV から消す根拠にしない（消したい行は手で消す）。

再生中の曲（@attr.nowplaying）は date を持たず、まだ scrobble として確定していないので入れない。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'lastfm' / 'scrobbles.csv')
# 機械が書く認証状態なので .env でなくファイル（gitignore 済みの config/*.json）
SESSION_FILE = BASE_DIR / 'config' / 'lastfm_session.json'

TIMEZONE = 'Asia/Tokyo'

CSV_COLUMNS = [
    'played_at', 'uts', 'artist', 'track', 'album',
    'artist_mbid', 'track_mbid', 'album_mbid', 'url',
]

KEY_COLUMNS = ['uts', 'artist', 'track']

READ_CSV_KWARGS = {'dtype': str, 'keep_default_na': False}


def _text(value) -> str:
    if isinstance(value, dict):
        return str(value.get('#text') or '')
    return '' if value is None else str(value)


def _mbid(value) -> str:
    return str(value.get('mbid') or '') if isinstance(value, dict) else ''


def build_dataframe(tracks: list[dict]) -> pd.DataFrame:
    """user.getRecentTracks の track を CSV 用 DataFrame（全列 str）にする。再生中の曲は落とす"""
    rows = []
    for t in tracks:
        if (t.get('@attr') or {}).get('nowplaying') == 'true' or not t.get('date'):
            continue
        uts = str(t['date']['uts'])
        played_at = dt.datetime.fromtimestamp(int(uts), dt.timezone.utc)
        rows.append({
            'played_at': pd.Timestamp(played_at).tz_convert(TIMEZONE).isoformat(),
            'uts': uts,
            'artist': _text(t.get('artist')),
            'track': _text(t.get('name')),
            'album': _text(t.get('album')),
            'artist_mbid': _mbid(t.get('artist')),
            'track_mbid': str(t.get('mbid') or ''),
            'album_mbid': _mbid(t.get('album')),
            'url': str(t.get('url') or ''),
        })
    return pd.DataFrame(rows, columns=CSV_COLUMNS, dtype=str)


def load_scrobbles(csv_path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(csv_path or CSV_FILE, **READ_CSV_KWARGS)


def last_uts(csv_path: Path | None = None) -> int | None:
    """CSV の最新 scrobble の uts。CSV が無い・空なら None"""
    csv_path = csv_path or CSV_FILE
    if not csv_path.exists():
        return None
    df = load_scrobbles(csv_path)
    if df.empty:
        return None
    return int(df['uts'].astype(int).max())


def save_merged(df_new: pd.DataFrame, csv_path: Path | None = None) -> pd.DataFrame:
    """既存 CSV へ (uts, artist, track) で upsert して保存する。df_new が空なら既存行に触れない"""
    csv_path = csv_path or CSV_FILE
    ensure_dir(csv_path.parent)
    df_merged = csv_utils.merge_csv_by_columns(
        df_new, csv_path, key_columns=KEY_COLUMNS, sort_by=['played_at', 'artist', 'track'],
        read_csv_kwargs=READ_CSV_KWARGS,
    )
    df_merged = df_merged.reindex(columns=CSV_COLUMNS)
    df_merged.to_csv(csv_path, index=False)
    return df_merged
