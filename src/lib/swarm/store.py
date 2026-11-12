"""
Swarm チェックインの保存

- data/swarm/checkins.jsonl: API が返した checkin をそのまま1行1件（id で upsert）。
  CSV に落とさない項目（写真・同行者・イベント等）と、Dawarich へ渡す元データを残すため
- data/swarm/checkins.csv: 分析用に平らにした写し。jsonl から毎回作り直す

キーは checkin の id（24桁の16進）。数字だけの id や "5e..." で始まる id は pandas が
数値に読むので、CSV は必ず dtype=str で読み戻す。

Swarm 側で消したチェックインも消さない（API に無いことを消す根拠にしない）。
"""

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = BASE_DIR / 'data' / 'swarm'
RAW_FILE = require_private_path(DATA_DIR / 'checkins.jsonl')
CSV_FILE = require_private_path(DATA_DIR / 'checkins.csv')
# 機械が書く認証状態なので .env でなくファイル（gitignore 済みの config/*.json）
TOKEN_FILE = BASE_DIR / 'config' / 'swarm_token.json'

CSV_COLUMNS = [
    'id', 'created_at', 'created_at_uts', 'tz_offset_min',
    'venue_id', 'venue_name', 'category', 'lat', 'lng',
    'address', 'city', 'state', 'country',
    'shout', 'photo_count', 'with_count', 'is_private', 'source',
]

READ_CSV_KWARGS = {'dtype': str, 'keep_default_na': False}


def load_raw(raw_path: Path | None = None) -> dict[str, dict]:
    raw_path = raw_path or RAW_FILE
    if not raw_path.exists():
        return {}
    with raw_path.open(encoding='utf-8') as f:
        return {item['id']: item for item in map(json.loads, filter(str.strip, f))}


def last_created_at(raw_path: Path | None = None) -> int | None:
    raw = load_raw(raw_path)
    return max((int(c['createdAt']) for c in raw.values()), default=None)


def merge_raw(items: list[dict], raw_path: Path | None = None) -> dict[str, dict]:
    """id で upsert して createdAt 順に書く。items が空なら既存に触れない"""
    raw_path = raw_path or RAW_FILE
    merged = load_raw(raw_path)
    if not items:
        return merged
    merged.update({item['id']: item for item in items})
    ordered = sorted(merged.values(), key=lambda c: (int(c['createdAt']), c['id']))
    ensure_dir(raw_path.parent)
    tmp = raw_path.with_suffix('.jsonl.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        for item in ordered:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n')
    tmp.replace(raw_path)
    return {c['id']: c for c in ordered}


def _primary_category(venue: dict) -> str:
    cats = venue.get('categories') or []
    primary = next((c for c in cats if c.get('primary')), cats[0] if cats else None)
    return (primary or {}).get('name', '')


def _row(c: dict) -> dict:
    venue = c.get('venue') or {}
    loc = venue.get('location') or {}
    offset = int(c.get('timeZoneOffset') or 0)
    created = dt.datetime.fromtimestamp(int(c['createdAt']), dt.timezone(dt.timedelta(minutes=offset)))
    return {
        'id': c['id'],
        'created_at': created.isoformat(),
        'created_at_uts': str(c['createdAt']),
        'tz_offset_min': str(offset),
        'venue_id': venue.get('id', ''),
        'venue_name': venue.get('name', ''),
        'category': _primary_category(venue),
        'lat': '' if loc.get('lat') is None else str(loc['lat']),
        'lng': '' if loc.get('lng') is None else str(loc['lng']),
        'address': loc.get('address', ''),
        'city': loc.get('city', ''),
        'state': loc.get('state', ''),
        'country': loc.get('country', ''),
        'shout': c.get('shout', ''),
        'photo_count': str((c.get('photos') or {}).get('count', 0)),
        'with_count': str(len(c.get('with') or [])),
        'is_private': str(bool(c.get('private'))),
        'source': (c.get('source') or {}).get('name', ''),
    }


def build_dataframe(raw: dict[str, dict]) -> pd.DataFrame:
    rows = [_row(c) for c in sorted(raw.values(), key=lambda c: (int(c['createdAt']), c['id']))]
    return pd.DataFrame(rows, columns=CSV_COLUMNS, dtype=str)


def write_csv(raw: dict[str, dict], csv_path: Path | None = None) -> pd.DataFrame:
    csv_path = csv_path or CSV_FILE
    df = build_dataframe(raw)
    ensure_dir(csv_path.parent)
    df.to_csv(csv_path, index=False)
    return df


def load_checkins(csv_path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(csv_path or CSV_FILE, **READ_CSV_KWARGS)
