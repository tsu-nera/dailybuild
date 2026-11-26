"""habits.py show の計算（週ごとの実施日数と、設定とのずれ）

CLI は計算機で、判定しない（docs/habits.md「CLI とスキルの境界」）。
セルは「実施日数/行がある日数」。行が1件も無い週は `-`（欠測を 0/7 と書かない）。
"""

import datetime as dt

import pandas as pd

from lib.habits.daily import habit_projects

WEEK_FORMAT = '%G-W%V'


def week_keys(today: dt.date, count: int) -> list[str]:
    """古い順に ISO 週のキーを返す（進行中の週を含む）"""
    monday = today - dt.timedelta(days=today.weekday())
    return [(monday - dt.timedelta(weeks=i)).strftime(WEEK_FORMAT)
            for i in reversed(range(count))]


def is_partial(key: str, today: dt.date) -> bool:
    """進行中の週か（日曜が終わるまで）"""
    return key == today.strftime(WEEK_FORMAT) and today.weekday() != 6


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


def drift(projects: pd.DataFrame, clients: dict, roster: dict) -> tuple[list[str], list[str]]:
    """(a) target_per_week が無い良い習慣、(b) 良い習慣のアーカイブされていないプロジェクトに無い yaml の名前"""
    good = active_habits(projects, clients, 'good')
    no_target = [name for name in good
                 if (roster.get(name) or {}).get('target_per_week') is None]
    unknown = sorted(name for name in roster if name not in good)
    return no_target, unknown


def _cell(counts: dict, habit: str, week: str) -> str:
    hit = counts.get((habit, week))
    if hit is None:
        return '-'
    done, observed = hit
    return f'{done}/{observed}'


def good_table(daily: pd.DataFrame, names: list[str], roster: dict, weeks: list[str],
               today: dt.date) -> pd.DataFrame:
    """良い習慣: 週ごとの実施日数。target_per_week 以上の週に `*`。

    clear = target を満たした完了週 / 行がある完了週（進行中の週は数えない）。
    """
    counts = {(r.habit, r.week): (int(r.done), int(r.observed))
              for r in weekly_counts(daily, weeks).itertuples()}
    rows = []
    for name in names:
        target = (roster.get(name) or {}).get('target_per_week')
        row = {'habit': name, 'target': '-' if target is None else target}
        cleared = observed_weeks = 0
        for week in weeks:
            cell = _cell(counts, name, week)
            hit = counts.get((name, week))
            if hit is not None and target is not None and hit[0] >= target:
                cell += '*'
            if hit is not None and not is_partial(week, today):
                observed_weeks += 1
                cleared += int(target is not None and hit[0] >= target)
            row[week] = cell
        row['clear'] = f'{cleared}/{observed_weeks}' if target is not None and observed_weeks else '-'
        rows.append(row)
    return pd.DataFrame(rows, columns=['habit', 'target', *weeks, 'clear']).set_index('habit')


def bad_table(daily: pd.DataFrame, names: list[str], weeks: list[str]) -> pd.DataFrame:
    """悪い習慣: 週ごとに「7日中何日」（分母は行がある日数。完了週で行が揃えば7）"""
    counts = {(r.habit, r.week): (int(r.done), int(r.observed))
              for r in weekly_counts(daily, weeks).itertuples()}
    rows = [{'habit': name, **{week: _cell(counts, name, week) for week in weeks}}
            for name in names]
    return pd.DataFrame(rows, columns=['habit', *weeks]).set_index('habit')


def render_show(daily: pd.DataFrame, projects: pd.DataFrame, clients: dict, roster: dict,
                today: dt.date, count: int) -> str:
    weeks = week_keys(today, count)
    labels = {w: (f'{w} (partial)' if is_partial(w, today) else w) for w in weeks}
    out = [f'# Habits {today.strftime(WEEK_FORMAT)}', '']

    no_target, unknown = drift(projects, clients, roster)
    if no_target:
        out += ['> **No target_per_week**: ' + ' / '.join(no_target), '']
    if unknown:
        out += ['> **Not an active good habit in Toggl**: ' + ' / '.join(unknown), '']

    good = active_habits(projects, clients, 'good')
    if good:
        table = good_table(daily, good, roster, weeks, today)
        out += [f"## {clients['good']} (days per week)", '',
                table.rename(columns=labels).to_markdown(), '']
    bad = active_habits(projects, clients, 'bad')
    if bad:
        table = bad_table(daily, bad, weeks)
        out += [f"## {clients['bad']} (days per week)", '',
                table.rename(columns=labels).to_markdown(), '']
    return '\n'.join(out) + '\n'
