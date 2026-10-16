"""
Google Calendar の写し（data/calendar/events.csv）の解析・マージ・判定

管理の正本は Google Calendar。CSV は読み取り専用の写しで、skeleton と
events.jsonl が共有する「その日にかかるか」の判定（covers）もここに置く。

保存しない列: description（予約番号が入る）・attendees。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from lib.utils.csv_utils import merge_csv_by_columns

JST = dt.timezone(dt.timedelta(hours=9))

COLUMNS = ['id', 'calendar_id', 'summary', 'location', 'start', 'end',
           'all_day', 'event_type', 'status', 'updated']


def _to_jst_iso(value: str) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(JST)
    else:
        ts = ts.tz_convert(JST)
    return ts.isoformat()


def to_rows(items: list[dict], calendar_id: str = 'primary') -> tuple[pd.DataFrame, set[str]]:
    """API の items を (取り込む行, cancelled の id 集合) に分ける

    終日予定は API の date をそのまま持つ（end は排他端）。
    cancelled の item は start / summary を欠くことがあるので id だけ採る。
    """
    rows = []
    cancelled: set[str] = set()
    for item in items:
        if item.get('status') == 'cancelled':
            cancelled.add(str(item['id']))
            continue
        start, end = item.get('start', {}), item.get('end', {})
        all_day = 'date' in start
        if all_day:
            start_s, end_s = start['date'], end.get('date', start['date'])
        else:
            start_s = _to_jst_iso(start['dateTime'])
            end_s = _to_jst_iso(end['dateTime']) if 'dateTime' in end else ''
        rows.append({
            'id': str(item['id']),
            'calendar_id': calendar_id,
            'summary': item.get('summary', ''),
            'location': item.get('location', ''),
            'start': start_s,
            'end': end_s,
            'all_day': str(all_day),
            'event_type': item.get('eventType', ''),
            'status': item.get('status', ''),
            'updated': item.get('updated', ''),
        })
    return pd.DataFrame(rows, columns=COLUMNS, dtype=str), cancelled


def merge(existing_csv: Path, new_rows: pd.DataFrame, cancelled_ids: set[str]) -> pd.DataFrame:
    """id でキーマージし、cancelled の id だけ消す。API が返さなかった既存行は残す"""
    merged = merge_csv_by_columns(
        new_rows, existing_csv, key_columns=['id'],
        read_csv_kwargs={'dtype': str, 'keep_default_na': False},
        sort_by=['start', 'id'],
    )
    merged = merged[~merged['id'].isin(cancelled_ids)]
    return merged[COLUMNS].reset_index(drop=True)


def load(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame(columns=COLUMNS, dtype=str)
    return pd.read_csv(csv_path, dtype=str, keep_default_na=False)


def _is_all_day(row) -> bool:
    return str(row['all_day']) == 'True'


def bounds(row) -> tuple[dt.datetime, dt.datetime]:
    """予定の [start, end) を tz-aware（JST）で返す。終日は日付の JST 00:00"""
    if _is_all_day(row):
        start = dt.datetime.combine(dt.date.fromisoformat(row['start']), dt.time(), JST)
        end = dt.datetime.combine(dt.date.fromisoformat(row['end']), dt.time(), JST)
        return start, end
    start = pd.Timestamp(row['start']).tz_convert(JST).to_pydatetime()
    end = (pd.Timestamp(row['end']).tz_convert(JST).to_pydatetime()
           if row['end'] else start)
    return start, end


def covers(row, day: dt.date) -> bool:
    """予定が day（JST の暦日）にかかるか。skeleton と events が共有する唯一の判定"""
    if _is_all_day(row):
        return dt.date.fromisoformat(row['start']) <= day < dt.date.fromisoformat(row['end'])
    start, end = bounds(row)
    day_start = dt.datetime.combine(day, dt.time(), JST)
    day_end = day_start + dt.timedelta(days=1)
    if end == start:  # 終了が無い予定は点として扱う
        return day_start <= start < day_end
    return start < day_end and end > day_start


def events_on(df: pd.DataFrame, day: dt.date) -> pd.DataFrame:
    """day にかかる予定。終日を先に、あとは start 順"""
    if df.empty:
        return df
    hit = df[[covers(row, day) for _, row in df.iterrows()]]
    hit = hit.sort_values(['start', 'id'], kind='stable')
    is_all_day = hit['all_day'] == 'True'
    return pd.concat([hit[is_all_day], hit[~is_all_day]])
