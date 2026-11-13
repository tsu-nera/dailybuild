"""
XOSS サイコンの FIT から session の要約を取り出す

session メッセージだけを読む（record の1秒ごとの点は軌跡用で、要約には使わない）。
session がちょうど1つでない FIT は行を作らず警告する（0 km の行を捏造しない）。

入れない値: 心拍は計測器が無いと 0 が入る（実測の 0 ではない）。avg_altitude は -500.0 の無効値。
"""

import datetime as dt
import logging
from pathlib import Path
from typing import Iterable

import fitdecode

log = logging.getLogger('xoss')

JST = dt.timezone(dt.timedelta(hours=9))

COLUMNS = [
    'file', 'start', 'end', 'elapsed_s', 'timer_s', 'distance_m',
    'ascent_m', 'descent_m', 'avg_speed_mps', 'max_speed_mps', 'sport', 'sub_sport',
]

# CSV の列 -> session のフィールド名
_NUMERIC = {
    'elapsed_s': 'total_elapsed_time',
    'timer_s': 'total_timer_time',
    'distance_m': 'total_distance',
    'ascent_m': 'total_ascent',
    'descent_m': 'total_descent',
    'avg_speed_mps': 'avg_speed',
    'max_speed_mps': 'max_speed',
}


def _jst_iso(value) -> str:
    """FIT の時刻（UTC。naive なら UTC とみなす）を JST の tz-aware ISO 文字列にする。無ければ空"""
    if not isinstance(value, dt.datetime):
        return ''
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(JST).isoformat()


def _number(value):
    """数値でなければ空（0 に潰さない）"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ''
    return value


def summarize(name: str, messages: Iterable[tuple[str, dict]]) -> dict | None:
    """(メッセージ名, {フィールド: 値}) の列から1行を作る。session が1つでなければ None"""
    sessions = [fields for msg_name, fields in messages if msg_name == 'session']
    if len(sessions) != 1:
        log.warning('%s: session が %d 個なので行を作らない', name, len(sessions))
        return None
    s = sessions[0]
    row = {
        'file': name,
        'start': _jst_iso(s.get('start_time')),
        'end': _jst_iso(s.get('timestamp')),
        'sport': s.get('sport') or '',
        'sub_sport': s.get('sub_sport') or '',
    }
    for column, field in _NUMERIC.items():
        row[column] = _number(s.get(field))
    return {c: row[c] for c in COLUMNS}


def _iter_session_messages(path: Path):
    with fitdecode.FitReader(str(path)) as reader:
        for frame in reader:
            if isinstance(frame, fitdecode.FitDataMessage) and frame.name == 'session':
                yield frame.name, {f.name: f.value for f in frame.fields}


def summarize_file(path: Path) -> dict | None:
    """FIT ファイルを読んで要約1行にする。壊れていて読めないものは警告して None"""
    path = Path(path)
    try:
        return summarize(path.name, list(_iter_session_messages(path)))
    except Exception as exc:  # fitdecode は壊れた FIT で複数種の例外を投げる
        log.warning('%s: FIT を読めないので行を作らない (%s)', path.name, exc)
        return None
