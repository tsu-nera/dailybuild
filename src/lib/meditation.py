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

サマタ評価（satoru の memory samatha-evaluation-plan）の比較用に、種類ごとのまとめ（meditation_eval）を作る。除外率が ARTIFACT_MAX_PCT 以上の回は変化の値を使わない
（回数には数え、まとめの n_dropped に出す）。目安の回数（サマタ20・対照6）は satoru の scripts/eval_progress.py と同じ。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

PROJECT = '瞑想'

# satoru（PUBLIC）。vaio で pull して読む。dashboard（meditation_muse）と toggl push（satoru_meditation）が読む
SATORU_SESSION_LOG = Path.home() / 'repo/satoru/logs/session_log.csv'

DAILY_COLUMNS = ['date', 'sessions', 'total_min']
WEEK_COLUMNS = ['week_start', 'week', 'sessions', 'days', 'total_min']
NOW_COLUMNS = WEEK_COLUMNS + [f'prev_{c}' for c in WEEK_COLUMNS]
MUSE_COLUMNS = ['start', 'date', 'meditation_type', 'duration_min', 'focus_rating', 'drowsiness_rating', 'sleep_hours',
                'tp_alpha_db_first', 'tp_alpha_db_last', 'tp_alpha_db_change',
                'tp_delta_db_first', 'tp_delta_db_last', 'tp_delta_db_change', 'artifact_reject_pct',
                # レポートの要約の数字（回をまたいで並べる用）。HRV・呼吸は SelfLoops を着けた日だけ値がある
                'alpha_osc_db', 'iaf_mean', 'fm_theta_rel_mean', 'theta_alpha_mean',
                'hrv_mean', 'breathing_rate_bpm', 'rsa_amplitude_ms']
EVAL_COLUMNS = ['meditation_type', 'label', 'n', 'target', 'n_rated', 'n_dropped', 'focus_median',
                'drowsiness_median', 'tp_alpha_db_change_median', 'tp_delta_db_change_median']
EVAL_TYPES = {'samatha': ('サマタ', 20), 'control': ('対照', 6)}
ARTIFACT_MAX_PCT = 30.0


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

    return {'meditation_daily': daily,
            'meditation_weeks': weeks, 'meditation_now': now}


def build_muse(session_log_csv: Path, metrics_daily_csv: Path) -> list[dict]:
    """satoru の session_log から Muse の回の結果を新しい順に。change は終わり − 入り（dB）。欠測は空

    sleep_hours は metrics_daily の同じ日付の値。metrics_daily の日付は起床日（Fitbit の dateOfSleep）なので、
    朝の回ならその朝に明けた夜の睡眠になる（夕方の回も同じ夜を指す）
    """
    df = pd.read_csv(session_log_csv, dtype={'pipeline_version': str})
    df = df[df['pipeline_version'].notna()].copy()
    start = pd.to_datetime(df['timestamp'])
    df['start'] = start.dt.strftime('%Y-%m-%d %H:%M')
    df['date'] = start.dt.date.astype(str)
    sleep = pd.read_csv(metrics_daily_csv, usecols=['date', 'sleep_hours'], dtype={'date': str})
    df = df.merge(sleep, on='date', how='left')
    df['tp_alpha_db_change'] = df['tp_alpha_db_last'] - df['tp_alpha_db_first']
    df['tp_delta_db_change'] = df['tp_delta_db_last'] - df['tp_delta_db_first']
    df = df.sort_values('start', ascending=False)[MUSE_COLUMNS].round(2).astype(object)
    return df.where(df.notna(), None).to_dict('records')


def _usable(row: dict) -> bool:
    pct = row['artifact_reject_pct']
    return pct is not None and pct < ARTIFACT_MAX_PCT


def _median(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return round(float(pd.Series(values).median()), 2) if values else None


def build_eval(muse: list[dict]) -> list[dict]:
    """種類ごとの回数・主観と TP の変化の中央値。変化は除外率が ARTIFACT_MAX_PCT 未満の回だけ"""
    rows = []
    for kind, (label, target) in EVAL_TYPES.items():
        typed = [r for r in muse if r['meditation_type'] == kind]
        usable = [r for r in typed if _usable(r)]
        rows.append({'meditation_type': kind, 'label': label, 'n': len(typed), 'target': target,
                     'n_rated': sum(r['focus_rating'] is not None for r in typed),
                     'n_dropped': len(typed) - len(usable),
                     'focus_median': _median([r['focus_rating'] for r in typed]),
                     'drowsiness_median': _median([r['drowsiness_rating'] for r in typed]),
                     'tp_alpha_db_change_median': _median([r['tp_alpha_db_change'] for r in usable]),
                     'tp_delta_db_change_median': _median([r['tp_delta_db_change'] for r in usable])})
    return rows

