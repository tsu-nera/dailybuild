"""reports/habits_daily.csv の生成（Toggl Focus 起点）

習慣1つ = Toggl Focus のプロジェクト1つ。対象は設定（config/habits.yaml）の
クライアントに属するプロジェクトで、habits.yaml に習慣の一覧は持たない。

行を作る範囲は [max(created_at, CUTOVER_DATE), archived_at または today]（JST 暦日）。
範囲内でエントリがある日は completed=True、無い日は False。**範囲外は行を作らない**
（欠測と不生起を分ける。docs/habits.md）。

起点を CUTOVER_DATE で切るのは、移行済みプロジェクトの created_at が Track からの
移行時刻（2026-01-13）で、それより後・切替日より前の Focus は未観測だから。
"""

import datetime as dt

import pandas as pd

from lib.toggl import store

HABITS_DAILY_COLUMNS = ['date', 'habit', 'task_type', 'is_due', 'completed']
TASK_TYPE = 'toggl'


def to_jst_date(value) -> dt.date | None:
    """API の時刻（UTC の RFC 3339）を JST の暦日にする。空なら None"""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value == '':
        return None
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    return ts.tz_convert(store.JST).date()


def habit_projects(projects: pd.DataFrame, clients: dict) -> pd.DataFrame:
    """対象クライアント（good / bad）のプロジェクトに kind 列（good / bad）を付けて返す"""
    kind_by_client = {name: kind for kind, name in clients.items()}
    df = projects[projects['client_name'].isin(kind_by_client)].copy()
    df['kind'] = df['client_name'].map(kind_by_client)
    df['archived'] = df['archived_at'].fillna('').astype(str) != ''
    return df


def _entry_days(entries: pd.DataFrame) -> set[tuple[int, dt.date]]:
    """(project_id, start の JST 暦日)。focus_entries.csv の start は JST naive"""
    if entries.empty:
        return set()
    df = entries.dropna(subset=['project_id'])
    days = pd.to_datetime(df['start']).dt.date
    return set(zip(df['project_id'].astype(int), days))


def build_habits_daily(entries: pd.DataFrame, projects: pd.DataFrame, clients: dict,
                       today: dt.date) -> pd.DataFrame:
    """habits_daily.csv の中身。エントリとプロジェクトの対応は project_id（改名に強い）"""
    done = _entry_days(entries)
    rows = []
    for p in habit_projects(projects, clients).itertuples():
        created = to_jst_date(p.created_at)
        if created is None:
            continue
        start = max(created, store.CUTOVER_DATE)
        archived = to_jst_date(p.archived_at)
        end = min(archived, today) if archived else today
        project_id = int(p.id)
        day = start
        while day <= end:
            rows.append({
                'date': day.isoformat(),
                'habit': p.name,
                'task_type': TASK_TYPE,
                'is_due': None,
                'completed': (project_id, day) in done,
            })
            day += dt.timedelta(days=1)

    if not rows:
        return pd.DataFrame(columns=HABITS_DAILY_COLUMNS)
    return (pd.DataFrame(rows, columns=HABITS_DAILY_COLUMNS)
              .sort_values(['date', 'habit'])
              .reset_index(drop=True))
