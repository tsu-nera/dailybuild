"""習慣の週ごとの日数と、設定とのずれ

習慣の数え方はここに1本だけ置く。Grafana の「目標」画面（dashboard.py）も
この関数を呼ぶだけで、自前で数えない（docs/habits.md）。

- 週は ISO 週（%G-W%V）
- 日数は habits_daily.csv の completed=True の行の数。行が無い日（観測していない日）は数えない
- その週に行が1件も無ければ None（欠測を 0 日と書かない）
- アーカイブ済みの習慣は返さない
"""

import datetime as dt

import pandas as pd

from lib.habits.daily import habit_projects

WEEK_FORMAT = '%G-W%V'


def week_key(day: dt.date) -> str:
    return day.strftime(WEEK_FORMAT)


def weekly_counts(daily: pd.DataFrame, weeks: list[str]) -> pd.DataFrame:
    """(habit, week) → done（completed の日数）と observed（行がある日数）"""
    if daily.empty:
        return pd.DataFrame(columns=['habit', 'week', 'done', 'observed'])
    df = daily.assign(
        week=pd.to_datetime(daily['date']).dt.strftime(WEEK_FORMAT),
        done=daily['completed'].astype(str) == 'True',
    )
    df = df[df['week'].isin(weeks)]
    return (df.groupby(['habit', 'week'])
              .agg(done=('done', 'sum'), observed=('done', 'size'))
              .reset_index())


def active_habits(projects: pd.DataFrame, clients: dict, kind: str) -> list[str]:
    """アーカイブされていない kind（good / bad）の習慣名（名前順）"""
    df = habit_projects(projects, clients)
    return sorted(df.loc[(df['kind'] == kind) & ~df['archived'], 'name'].tolist())


def weekly_days(daily: pd.DataFrame, projects: pd.DataFrame, clients: dict, roster: dict,
                weeks: list[str]) -> list[dict]:
    """アーカイブされていない習慣ごとに {habit, kind, target, days: {week: 日数 | None}}

    並びは良い習慣 → 悪い習慣、それぞれ名前順。target は良い習慣の target_per_week
    （悪い習慣は常に None）。
    """
    counts = {(r.habit, r.week): int(r.done) for r in weekly_counts(daily, weeks).itertuples()}
    rows = []
    for kind in ('good', 'bad'):
        for name in active_habits(projects, clients, kind):
            target = (roster.get(name) or {}).get('target_per_week') if kind == 'good' else None
            rows.append({'habit': name, 'kind': kind, 'target': target,
                         'days': {week: counts.get((name, week)) for week in weeks}})
    return rows


def drift(projects: pd.DataFrame, clients: dict, roster: dict) -> tuple[list[str], list[str]]:
    """(a) target_per_week が無い良い習慣、(b) 良い習慣のアーカイブされていないプロジェクトに無い yaml の名前"""
    good = active_habits(projects, clients, 'good')
    no_target = [name for name in good
                 if (roster.get(name) or {}).get('target_per_week') is None]
    unknown = sorted(name for name in roster if name not in good)
    return no_target, unknown
