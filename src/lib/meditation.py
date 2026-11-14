"""
瞑想の回ごと・日ごと・週ごとの表（Grafana の meditation 画面と目標の一覧）

記録元は Toggl Focus（data/toggl/focus_entries.csv）の「瞑想」プロジェクト1本。機器で測った回
（Google Health の MEDITATE / YOGA）は toggl push が同じプロジェクトへ入れるので、手で入れた回と合わせて
Focus に集まる。push 由来も数える（lib.events と違い、元の exercise.csv は読まないので二重にならない）。

Track（time_entries.csv）は deprecated なので読まない。推移は Focus に瞑想が入り始めた 2026-10-29 から。
それより前の記録（Track・Muse・Fitbit・Google Health）はつながない（2026-11-14 に決めた）。
記録の無い日・週は0回として行を作る（瞑想は毎回記録を始める操作が要るので、記録が無い＝してない）。
最初の記録より前の日・週は作らない。

日ごと・週ごとの表は Grafana の時間範囲で期間を選ぶ（date / week_start を timestamp で読む）。
meditation_now（今週・先週）は週単位の一覧（goals）用。

Muse で測った回の結果（meditation_muse）は satoru の logs/session_log.csv を読む（データソースとしての satoru。
dailybuild からは書かない）。satoru の session-review が push し、vaio で pull したものを読む。
pipeline_version が空の行（2026-05 以前・旧定義）は横に比べられないので入れない。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

PROJECT = '瞑想'

SESSION_COLUMNS = ['start', 'date', 'week', 'duration_min']
DAILY_COLUMNS = ['date', 'sessions', 'total_min']
WEEK_COLUMNS = ['week_start', 'week', 'sessions', 'days', 'total_min']
NOW_COLUMNS = WEEK_COLUMNS + [f'prev_{c}' for c in WEEK_COLUMNS]
MUSE_COLUMNS = ['start', 'date', 'meditation_type', 'duration_min', 'focus_rating', 'drowsiness_rating',
                'tp_alpha_db_first', 'tp_alpha_db_last', 'tp_alpha_db_change',
                'tp_delta_db_first', 'tp_delta_db_last', 'tp_delta_db_change', 'artifact_reject_pct']


def _week_label(d: dt.date) -> str:
    iso = d.isocalendar()
    return f'{iso.year}-W{iso.week:02d}'


def build(focus_csv: Path, today: dt.date) -> dict[str, list[dict]]:
    """表の名前 → 行。today より後の回と、計測中（stop が空）の回は入れない"""
    df = pd.read_csv(focus_csv, usecols=['start', 'stop', 'project_name'], parse_dates=['start', 'stop'])
    df = df[(df['project_name'] == PROJECT) & df['stop'].notna()]
    df = df[df['start'].dt.date <= today]

    sessions = [{'start': r.start.strftime('%Y-%m-%d %H:%M'), 'date': r.start.date().isoformat(),
                 'week': _week_label(r.start.date()),
                 'duration_min': round((r.stop - r.start).total_seconds() / 60, 1)}
                for r in df.sort_values('start').itertuples()]

    daily, weeks = [], []
    if sessions:
        first = dt.date.fromisoformat(sessions[0]['date'])
        day = first
        while day <= today:
            rows = [s for s in sessions if s['date'] == day.isoformat()]
            daily.append({'date': day.isoformat(), 'sessions': len(rows),
                          'total_min': round(sum(s['duration_min'] for s in rows), 1)})
            day += dt.timedelta(days=1)
        monday = first - dt.timedelta(days=first.weekday())
        while monday <= today:
            label = _week_label(monday)
            rows = [s for s in sessions if s['week'] == label]
            weeks.append({'week_start': monday.isoformat(), 'week': label, 'sessions': len(rows),
                          'days': len({s['date'] for s in rows}),
                          'total_min': round(sum(s['duration_min'] for s in rows), 1)})
            monday += dt.timedelta(weeks=1)

    # 今週・先週の選択は Grafana の filter 式でなくここでやる（dashboard.py の current と同じ）
    now = []
    if weeks and weeks[-1]['week'] == _week_label(today):
        row = dict(weeks[-1])
        prev = weeks[-2] if len(weeks) > 1 else {k: None for k in WEEK_COLUMNS}
        row.update({f'prev_{k}': v for k, v in prev.items()})
        now.append(row)

    return {'meditation_sessions': sessions[::-1], 'meditation_daily': daily,
            'meditation_weeks': weeks, 'meditation_now': now}


def build_muse(session_log_csv: Path) -> list[dict]:
    """satoru の session_log から Muse の回の結果を新しい順に。change は終わり − 入り（dB）。欠測は空"""
    df = pd.read_csv(session_log_csv, dtype={'pipeline_version': str})
    df = df[df['pipeline_version'].notna()].copy()
    start = pd.to_datetime(df['timestamp'])
    df['start'] = start.dt.strftime('%Y-%m-%d %H:%M')
    df['date'] = start.dt.date.astype(str)
    df['tp_alpha_db_change'] = df['tp_alpha_db_last'] - df['tp_alpha_db_first']
    df['tp_delta_db_change'] = df['tp_delta_db_last'] - df['tp_delta_db_first']
    df = df.sort_values('start', ascending=False)[MUSE_COLUMNS].round(2).astype(object)
    return df.where(df.notna(), None).to_dict('records')
