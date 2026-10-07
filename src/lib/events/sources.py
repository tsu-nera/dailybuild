"""
ソース別アダプタ。各 CSV を読み、イベント dict のリストに変換する

イベントは {start, end, source, kind, name, attrs}。start / end は tz-aware の
datetime（JST）で、end は点イベントなら None。時刻の正規化は to_jst() の
一箇所だけで行い、アダプタごとに tz を解釈しない。

data/ は読むだけで書き換えない（取得の正本）。
"""

import datetime as dt
import math
from pathlib import Path

import pandas as pd

from lib import exercise_source

JST = dt.timezone(dt.timedelta(hours=9))


def to_jst(value) -> dt.datetime | None:
    """時刻を tz-aware（JST）の datetime にする。naive な入力は JST として解釈する

    Toggl の裸の 'YYYY-MM-DD HH:MM:SS' を UTC と解釈して9時間ずらした事故が
    過去にあるため、naive を UTC 扱いする経路をここ以外に作らない。
    欠測（空・NaN）は None を返す（0 埋めや start での代用はしない）。
    """
    if value is None or (isinstance(value, float) and math.isnan(value)) or value == '':
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize(JST)
    else:
        ts = ts.tz_convert(JST)
    return ts.to_pydatetime()


def _clean(attrs: dict) -> dict:
    """欠測（NaN / None / 空文字）のキーを落とし、numpy 型を素の Python 型にする"""
    out = {}
    for key, value in attrs.items():
        if value is None or value == '':
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        if hasattr(value, 'item'):
            value = value.item()
        out[key] = value
    return out


def _event(start, end, source, kind, name, attrs) -> dict:
    return {
        'start': to_jst(start),
        'end': to_jst(end),
        'source': source,
        'kind': kind,
        'name': name if isinstance(name, str) else '',
        'attrs': _clean(attrs),
    }


def toggl_events(entries_csv: Path, pushed_csv: Path) -> list[dict]:
    """Toggl のタイムエントリ。toggl push で投入したもの（睡眠・運動）は落とす

    push 由来のエントリは元ソース（exercise / sleep）側の行を採るので、
    残すと同じ活動が2行になる。
    """
    if not entries_csv.exists():
        return []
    df = pd.read_csv(entries_csv, dtype={'id': str, 'project_id': str})
    if pushed_csv.exists():
        pushed = pd.read_csv(pushed_csv, dtype={'toggl_entry_id': str})
        pushed_ids = set(pushed['toggl_entry_id'].dropna())
        df = df[~df['id'].isin(pushed_ids)]

    return [
        _event(row['start'], row['stop'], 'toggl', 'time_entry', row['project_name'], {
            'id': row['id'],
            'description': row['description'],
            'tags': row['tags'],
            'duration_sec': row['duration_sec'],
        })
        for row in df.to_dict('records')
    ]


def exercise_events(exercise_csv: Path) -> list[dict]:
    """Google Health の運動セッション。platform 重複は exercise_source の規則で解決する"""
    df = exercise_source.load_sessions(csv_path=exercise_csv)
    if df is None:
        return []
    return [
        _event(row['start'], row['end'], 'googlehealth_exercise', 'exercise',
               row['display_name'], {
                   'id': row['id'],
                   'exercise_type': row['exercise_type'],
                   'platform': row['platform'],
                   'duration_min': row['duration_min'],
                   'calories': row['calories'],
                   'distance_km': row['distance_km'],
                   'hr_avg': row['average_heart_rate'],
               })
        for row in df.to_dict('records')
    ]


def sleep_events(sleep_csv: Path) -> list[dict]:
    """メイン睡眠のみ。昼寝（isMainSleep=False）は v1 では入れない"""
    if not sleep_csv.exists():
        return []
    df = pd.read_csv(sleep_csv, dtype={'logId': str, 'isMainSleep': str})
    df = df[df['isMainSleep'] == 'True']
    return [
        _event(row['startTime'], row['endTime'], 'wearable_sleep', 'sleep', 'sleep', {
            'log_id': row['logId'],
            'date_of_sleep': row['dateOfSleep'],
            'minutes_asleep': row['minutesAsleep'],
            'minutes_awake': row['minutesAwake'],
            'efficiency': row['efficiency'],
        })
        for row in df.to_dict('records')
    ]


def habitica_events(history_csv: Path) -> list[dict]:
    """Habitica の実行記録（点イベント）

    history には「やったこと」以外の行も入る。Daily は cron 時に
    completed=False の行が入るので、completed=True の行だけを採る。Habit は
    1日1行に押下回数が畳まれており、ts はその日の最後の押下。押下が無い行
    （scored_up / scored_down がともに 0 か欠測）は落とす。completed /
    scored_* を持たない古い行は実行の有無が分からないので入れない
    （欠測を実行として捏造しない）。
    """
    if not history_csv.exists():
        return []
    df = pd.read_csv(history_csv, dtype={'task_id': str, 'completed': str})
    is_daily_done = (df['task_type'] == 'daily') & (df['completed'] == 'True')
    is_habit_pressed = (df['task_type'] == 'habit') & (
        (df['scored_up'].fillna(0) > 0) | (df['scored_down'].fillna(0) > 0)
    )
    df = df[is_daily_done | is_habit_pressed]
    return [
        _event(row['ts'], None, 'habitica', row['task_type'], row['task_name'], {
            'task_id': row['task_id'],
            'scored_up': row['scored_up'],
            'scored_down': row['scored_down'],
        })
        for row in df.to_dict('records')
    ]
