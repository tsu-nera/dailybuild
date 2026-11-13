"""Dawarich の名前の無い Place（Unknown）に付ける名前を決める

Dawarich は Google Timeline の取り込みで、place ID だけを持つ Place を `Unknown` という名前で作る。
取り込み直すたびに作り直されるので、DB を手で直さず、取り込みのたびにこの名前を流し直す。

本人が UI で付けた名前は data/dawarich/places.csv（lib.dawarich.place_ledger）が先に当て直す。
ここが付けるのは、それでも Unknown のまま残った Place の名前。出どころ（上ほど優先）:
1. Timeline で自宅と推定された place ID → `自宅`
2. Timeline の名前の辞書 data/timeline/places.csv（vaio の日次が書く。ここからは書かない）
3. Dawarich のホストだけが持つキャッシュ（下の CACHE_FILE）。places.csv に無い分を
   Places API で引いた結果。places.csv を2台で書くと merge が壊れるので別にしてある

どれにも無い place ID だけが Places API を呼ぶ対象になる。
"""

from pathlib import Path

import pandas as pd

from lib.timeline import PLACE_COLUMNS, read_places

HOME_NAME = '自宅'

# git の外。消えても Places API を引き直すだけ
CACHE_FILE = Path.home() / '.cache' / 'dailybuild' / 'dawarich_place_names.csv'


def _dictionary(places: pd.DataFrame) -> tuple[dict[str, str], set[str]]:
    """(名前のある place ID → 名前, 引いたが名前が無かった place ID)"""
    named = places[(places['status'] == 'ok') & (places['display_name'] != '')]
    tried = set(places['place_id'])
    names = dict(zip(named['place_id'], named['display_name']))
    return names, tried - set(names)


def resolve(place_ids: list[str], home_ids: set[str],
            places: pd.DataFrame, cache: pd.DataFrame) -> tuple[dict[str, dict], list[str]]:
    """(place ID → {'name', 'note'}, Places API で引く place ID)

    places.csv かキャッシュで not_found だった ID は引き直さない（名前の無いまま残す）。
    """
    dict_names, dict_empty = _dictionary(places)
    cache_names, cache_empty = _dictionary(cache)
    resolved: dict[str, dict] = {}
    misses: list[str] = []
    for pid in dict.fromkeys(place_ids):
        if pid in home_ids:
            resolved[pid] = {'name': HOME_NAME, 'note': ''}
        elif pid in dict_names:
            resolved[pid] = {'name': dict_names[pid], 'note': ''}
        elif pid in cache_names:
            resolved[pid] = {'name': cache_names[pid], 'note': ''}
        elif pid not in dict_empty and pid not in cache_empty:
            misses.append(pid)
    return resolved, misses


def read_cache(path: Path = CACHE_FILE) -> pd.DataFrame:
    return read_places(path)


def append_cache(rows: list[dict], path: Path = CACHE_FILE) -> None:
    """新しい place ID の行だけを足す。既存行は書き換えない"""
    if not rows:
        return
    existing = read_cache(path)
    fresh = pd.DataFrame(rows, columns=PLACE_COLUMNS)
    fresh = fresh[~fresh['place_id'].isin(set(existing['place_id']))]
    if fresh.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat([existing, fresh], ignore_index=True).to_csv(path, index=False)
