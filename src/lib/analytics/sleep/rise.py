"""
離床（布団から出た時刻）と目標時刻との差

Fitbit の睡眠記録の終了（endTime）は離床ではない。末尾の覚醒ステージを含むので、
目は覚めたまま布団にいた時間がまるごと抜ける（10-19 は終了 07:29、離床 08:30 ごろ）。
離床は起床後に歩数が出始めた分で取る。歩数の記録が無い朝は None にし、endTime で埋めない
（埋めると目標の達成を実際より多く数える）。
"""

import pandas as pd

RISE_STEPS = 40          # この歩数を RISE_WINDOW_MIN 分以内に歩いた最初の分を離床とする
RISE_WINDOW_MIN = 10
RISE_WITHIN_HOURS = 8    # 起床からこの時間内に見つからなければ不明


def load_steps(csv_path) -> pd.Series:
    """steps_intraday.csv を分単位の Series（index は naive な JST）で返す"""
    df = pd.read_csv(csv_path, parse_dates=['datetime'])
    return df.set_index('datetime')['steps'].sort_index()


def rise_time(steps: pd.Series, wakeup: pd.Timestamp):
    """起床（wakeup）後に歩き出した最初の分。歩数の記録が無ければ None"""
    end = wakeup + pd.Timedelta(hours=RISE_WITHIN_HOURS)
    window = steps[(steps.index >= wakeup) & (steps.index < end)]
    if window.empty:
        return None
    per_min = window.resample('1min').sum()
    ahead = per_min[::-1].rolling(RISE_WINDOW_MIN, min_periods=1).sum()[::-1]
    hit = ahead[(ahead >= RISE_STEPS) & (per_min > 0)]   # 窓の先頭は歩いた分にする
    return hit.index[0] if len(hit) else None


def minutes_late(actual: pd.Timestamp, target_hhmm: str, evening: bool = False) -> int:
    """目標時刻からの遅れ（分、早ければ負）

    evening=True は就寝用。正午より前の時刻を翌日側（24時以降）として比べる。
    """
    h, m = map(int, target_hhmm.split(':'))
    target = h * 60 + m
    t = actual.hour * 60 + actual.minute
    if evening:
        target += 24 * 60 if h < 12 else 0
        t += 24 * 60 if actual.hour < 12 else 0
    return t - target
