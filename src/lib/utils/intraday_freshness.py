"""
heart_rate_intraday.csv の鮮度チェック（Issue #128）

心拍 intraday は取得コストが高く（1日約8分）日次取得から外してあるため、
CSV がレポート期間に追いついていないことがある。読み手
（hr_zones / zone2 / sleep_intraday_analysis）は df が None / 空のとき
例外を出さず静かに空の結果を返すため、レポート上は「測ったが値が無い」
空欄になってしまい、CSV が古いことに気づけない。

このモジュールは「古い/不在」を検出して呼び出し側（各レポートの
generator）に返すだけで、レンダリングや取得は行わない。
"""

from datetime import date, datetime

import pandas as pd

# CSV が存在しない/空/壊れている場合の既定の取得窓（日）。
# 「不在」は最終取得日が分からないため、ひとまず直近1週間分を取り直す
# ことを促す既定値として 7 を選んだ（days_behind が判明する場合はそちらを使う）。
DEFAULT_FETCH_DAYS_WHEN_MISSING = 7

# 末尾を読むために遡って読み込むバイト数。1行あたり ~25バイト
# （"2026-09-05 10:40:00,74\n"）なので十分に余裕を持たせてある。
TAIL_READ_BYTES = 4096


def _to_date(value):
    """date / datetime / pd.Timestamp / 'YYYY-MM-DD' 文字列を date に正規化する"""
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NaT:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    # 文字列（'YYYY-MM-DD' や 'YYYY-MM-DD HH:MM:SS'）
    ts = pd.Timestamp(str(value))
    return ts.date()


def _read_last_line(csv_path):
    """CSVの末尾から最終行（ヘッダ以外）を読む。全読みしない。

    Returns
    -------
    str or None
        最終データ行の文字列。読めない/データ行が無い場合は None。
    """
    try:
        file_size = csv_path.stat().st_size
        if file_size == 0:
            return None

        with open(csv_path, 'rb') as f:
            read_size = min(TAIL_READ_BYTES, file_size)
            f.seek(file_size - read_size)
            tail = f.read()

        lines = tail.decode('utf-8', errors='ignore').splitlines()
        # 末尾が改行で終わっていれば最後の要素は空文字なので除く
        lines = [line for line in lines if line.strip()]
        if not lines:
            return None

        last_line = lines[-1]
        # 先頭から読んだのでなければヘッダ行そのものを最終行と誤認する
        # 可能性がある（データ0行のケース）。ヘッダらしき文字列は除外する。
        if last_line.startswith('datetime,'):
            return None

        return last_line
    except (OSError, IOError):
        return None


def hr_intraday_freshness(csv_path, period_end):
    """heart_rate_intraday.csv がレポート期間の終端に追いついているかを返す。

    Parameters
    ----------
    csv_path : Path
        heart_rate_intraday.csv のパス
    period_end : date, datetime, pd.Timestamp, or str
        レポート期間の終端（表に出る最後の日付）

    Returns
    -------
    dict or None
        追いついていれば None（レポートに何も出さない）。
        古い/不在/空のときは
        {'last_date': 'YYYY-MM-DD' or None, 'days_behind': int or None,
         'fetch_days': int}
    """
    try:
        period_end_date = _to_date(period_end)
    except (ValueError, TypeError):
        return None

    if period_end_date is None:
        return None

    last_line = _read_last_line(csv_path)
    if last_line is None:
        return {
            'last_date': None,
            'days_behind': None,
            'fetch_days': DEFAULT_FETCH_DAYS_WHEN_MISSING,
        }

    try:
        datetime_str = last_line.split(',')[0]
        last_date = pd.Timestamp(datetime_str).date()
    except (ValueError, TypeError, IndexError):
        return {
            'last_date': None,
            'days_behind': None,
            'fetch_days': DEFAULT_FETCH_DAYS_WHEN_MISSING,
        }

    if last_date >= period_end_date:
        return None

    days_behind = (period_end_date - last_date).days
    return {
        'last_date': last_date.strftime('%Y-%m-%d'),
        'days_behind': days_behind,
        'fetch_days': max(days_behind, 1),
    }
