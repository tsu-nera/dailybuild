# coding: utf-8
"""Google マップ Timeline の端末 export → 訪問の DataFrame と期間集計

集計は純粋関数。Drive の取得と visits.csv の読み書きは scripts/timeline.py、
place ID → 名前の辞書 places.csv の読み書きだけはここに置く。
仕様と落とし穴は docs/timeline.md。
"""

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from lib.utils.private_data import ensure_dir

VISIT_COLUMNS = [
    'start_time', 'end_time', 'duration_min', 'place_id',
    'semantic_type', 'probability', 'lat', 'lon',
]

PLACE_COLUMNS = ['place_id', 'display_name', 'primary_type', 'status', 'resolved_at']

# 自宅と推定された場所。place_id のまま出すより「自宅」と分かる方が読み手に要る
HOME_TYPES = {'HOME', 'INFERRED_HOME'}


def _parse_latlng(text):
    """`"12.34°, 56.78°"` → (12.34, 56.78)。度記号付きの文字列で届く"""
    lat, lon = (float(part.strip().rstrip('°').strip()) for part in text.split(','))
    return lat, lon


def parse_export(content):
    """export の JSON から hierarchyLevel 0 の visit だけを DataFrame にする

    同じ時間帯の visit が hierarchyLevel 違いで重複して出るため level 0 だけを
    残す。想定の形でなければ ValueError（呼び出し側は既存 CSV に触れない）。
    start_time / end_time は export の offset 付き ISO 文字列のまま持つ。
    """
    data = json.loads(content)
    if not isinstance(data, dict) or 'semanticSegments' not in data:
        raise ValueError('semanticSegments が無い。Timeline の export ではない可能性がある')

    rows = []
    for seg in data['semanticSegments']:
        visit = seg.get('visit')
        if visit is None:
            continue
        try:
            if visit['hierarchyLevel'] != 0:
                continue
            top = visit['topCandidate']
            start, end = seg['startTime'], seg['endTime']
            lat, lon = _parse_latlng(top['placeLocation']['latLng'])
            duration = round(
                (pd.Timestamp(end) - pd.Timestamp(start)).total_seconds() / 60, 1)
            rows.append({
                'start_time': start,
                'end_time': end,
                'duration_min': duration,
                'place_id': top['placeId'],
                'semantic_type': top['semanticType'],
                # 場所の同定の確度（topCandidate のもの）。visit 自体の確度ではない
                'probability': top['probability'],
                'lat': lat,
                'lon': lon,
            })
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f'visit の必須項目が読めない: {exc!r}') from exc

    df = pd.DataFrame(rows, columns=VISIT_COLUMNS)
    df = df.drop_duplicates()
    return df.sort_values('start_time', kind='stable').reset_index(drop=True)


def read_places(path):
    """places.csv を読む。無ければ列だけの空 DataFrame。空欄は NaN にせず '' のまま"""
    if not Path(path).exists():
        return pd.DataFrame(columns=PLACE_COLUMNS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def append_places(path, new_rows):
    """places.csv に新しい place_id の行だけを足す。既存行は消さない・書き換えない"""
    if not new_rows:
        return
    existing = read_places(path)
    fresh = pd.DataFrame(new_rows, columns=PLACE_COLUMNS)
    fresh = fresh[~fresh['place_id'].isin(set(existing['place_id']))]
    if fresh.empty:
        return
    ensure_dir(Path(path).parent)
    pd.concat([existing, fresh], ignore_index=True).to_csv(path, index=False)


def places_to_resolve(visits, places, limit):
    """名前を引く place_id。未取得（not_found も含む）・HOME 無し・訪問日数2日以上、多い順

    訪問日数は全期間の start_time の日付（現地）の distinct 数。同数は place_id 昇順。
    """
    home_ids = set(visits.loc[visits['semantic_type'].isin(HOME_TYPES), 'place_id'])
    skip = home_ids | set(places['place_id'])
    day = visits['start_time'].astype(str).str[:10]
    days = visits.assign(day=day).groupby('place_id')['day'].nunique()
    days = days[(days >= 2) & ~days.index.isin(skip)]
    ordered = days.reset_index().sort_values(
        ['day', 'place_id'], ascending=[False, True], kind='stable')
    return list(ordered['place_id'].head(limit))


def place_labels(visits, places=None):
    """place_id → 表示名。HOME / INFERRED_HOME があれば `HOME`、次に辞書の名前、無ければ place_id"""
    home_ids = set(visits.loc[visits['semantic_type'].isin(HOME_TYPES), 'place_id'])
    names = {}
    if places is not None and not places.empty:
        ok = places[(places['status'] == 'ok') & (places['display_name'] != '')]
        names = dict(zip(ok['place_id'], ok['display_name']))
    return {pid: ('HOME' if pid in home_ids else names.get(pid, pid))
            for pid in visits['place_id'].unique()}


def _period_table(visits, start, end, top_n):
    """期間内の place_id 別 訪問日数・滞在時間。訪問日は start_time の日付（現地）"""
    day = visits['start_time'].astype(str).str[:10]
    sel = visits[(day >= str(start)) & (day <= str(end))].assign(day=day)
    if sel.empty:
        return pd.DataFrame(columns=['place_id', 'visit_days', 'duration_min'])
    table = sel.groupby('place_id').agg(
        visit_days=('day', 'nunique'),
        duration_min=('duration_min', 'sum'),
    ).reset_index()
    table = table.sort_values(
        ['visit_days', 'duration_min', 'place_id'],
        ascending=[False, False, True], kind='stable')
    return table.head(top_n).reset_index(drop=True)


def summarize(visits, start: dt.date, end: dt.date, top_n=20, places=None):
    """期間の上位 top_n と、直前の同日数の期間との入れ替わりを返す

    first_date / last_date は期間に限らず全 visits での初回・最終訪問日。
    entered = 今期の上位にあって前期の上位に無い place_id、dropped = その逆。
    """
    days = (end - start).days + 1
    prev_end = start - dt.timedelta(days=1)
    prev_start = start - dt.timedelta(days=days)

    current = _period_table(visits, start, end, top_n)
    previous = _period_table(visits, prev_start, prev_end, top_n)

    day = visits['start_time'].astype(str).str[:10]
    span = visits.assign(day=day).groupby('place_id')['day'].agg(
        first_date='min', last_date='max')
    current = current.join(span, on='place_id')

    cur_ids, prev_ids = list(current['place_id']), list(previous['place_id'])
    return {
        'start': start, 'end': end,
        'prev_start': prev_start, 'prev_end': prev_end,
        'current': current,
        'previous': previous,
        'entered': [p for p in cur_ids if p not in set(prev_ids)],
        'dropped': [p for p in prev_ids if p not in set(cur_ids)],
        'labels': place_labels(visits, places),
    }
