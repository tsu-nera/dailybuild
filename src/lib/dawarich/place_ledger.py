"""Dawarich の Place に本人が UI で下した判断（名前・merge・アーカイブ）の写し

Place の編集は Dawarich の UI でする。Dawarich の DB は作り直せる派生物なので、その判断を
data/dawarich/places.csv に外部 ID（Google の place ID・Swarm の venue）ごとに写しておき、
取り込み直しや作り直しのあとに name-places が当て直す。

merge すると統合された側の Place は消え、その外部 ID も DB から消える（Places::Merge は survivor の
geodata を優先する）。そこで前回の写しに残した Visit が今どの Place にあるかで統合先を推定する。
"""

from pathlib import Path

import pandas as pd

COLUMNS = ['external_place_id', 'name', 'archived', 'merged_into', 'note', 'place_id', 'visit_id', 'updated_at']
# 判断の列。変わった日を updated_at に残す
DECISION = ['name', 'archived', 'merged_into', 'note']
UNKNOWN = 'Unknown'


def read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _s(value) -> str:
    return '' if value is None else str(value)


def update(prev: pd.DataFrame, dump: dict, today: str) -> pd.DataFrame:
    """前回の写し prev と dump_places.rb の出力から新しい写しを作る

    - 前回と同じ Place（place_id が同じ）: 今の DB の状態を写す（UI で直した結果）。ただし Unknown に戻った名前は採らない
    - 外部 ID は同じで place_id が変わった: 取り込み直しで作り直された。前回の判断を残す（name-places が当て直す）
    - DB から消えた外部 ID: 行は消さない。前回の Visit が別の外部 ID の Place へ移っていれば merged_into に書く
    """
    old_rows = {r['external_place_id']: r for r in prev.to_dict('records')}
    place_ext = {p['place_id']: p['external_place_id'] for p in dump['places']}
    visit_place = {int(k): v for k, v in dump['visit_place'].items()}

    rows = []
    for p in dump['places']:
        ext = p['external_place_id']
        old = old_rows.pop(ext, None)
        visit_id = _s(p.get('visit_id')) or (old['visit_id'] if old else '')
        if old and old['place_id'] and old['place_id'] != _s(p['place_id']):
            row = {**old, 'place_id': _s(p['place_id']), 'visit_id': visit_id}
        else:
            name = p['name']
            if name == UNKNOWN and old and old['name']:
                name = old['name']
            row = {'external_place_id': ext, 'name': name, 'archived': str(bool(p['archived'])).lower(),
                   'merged_into': '', 'note': p.get('note') or '', 'place_id': _s(p['place_id']),
                   'visit_id': visit_id, 'updated_at': old['updated_at'] if old else today}
        rows.append(_stamp(row, old, today))

    for ext, old in old_rows.items():
        row = dict(old)
        if not old['merged_into'] and old['visit_id']:
            survivor = place_ext.get(visit_place.get(int(old['visit_id'])))
            if survivor and survivor != ext:
                row['merged_into'] = survivor
        rows.append(_stamp(row, old, today))

    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.sort_values('external_place_id', ignore_index=True)


def _stamp(row: dict, old: dict | None, today: str) -> dict:
    if old is None or any(row[c] != old[c] for c in DECISION):
        row['updated_at'] = today
    return row


def decisions(ledger: pd.DataFrame) -> list[dict]:
    """name-places が当て直す行（apply_place_ledger.rb の入力）"""
    cols = ['external_place_id', 'name', 'archived', 'merged_into', 'note']
    return ledger[cols].to_dict('records')
