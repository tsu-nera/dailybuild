"""
活動記録 CSV の読み込み

data/activity.csv（dailybuild-private への symlink）を対象に、show 側の
読み込みをまとめる。書き込みは scripts/activity.py の fetch が担う。
"""

from pathlib import Path

import pandas as pd

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'activity.csv')

COLUMNS = ['date', 'hour', 'activity', 'enjoyment', 'importance']

# 原典 Form 1 の22枠（5am 開始・翌 5am まで）を (開始時, 長さ) で持つ。
# 並びがそのままシートの行の並び。**最後だけが 2-5am の3時間枠**で、これは
# 原典どおり（睡眠中を1時間ずつ書かせない）。枠を勝手に丸めると、この帳票が
# 測ろうとしている「楽しくも重要でもない時間の長さ」が消える（docs/batdr.md）
SLOTS = [(h, 1) for h in list(range(5, 24)) + [0, 1]] + [(2, 3)]
SLOT_HOURS = dict(SLOTS)


def slot_label(hour: int) -> str:
    """開始時からシートの行見出しを作る（5-6, 23-0, 2-5 など）"""
    return f'{hour}-{(hour + SLOT_HOURS[hour]) % 24}'


LABEL_TO_HOUR = {slot_label(h): h for h, _ in SLOTS}


def load_entries() -> pd.DataFrame:
    """date 昇順・枠の並び順で読む。

    enjoyment / importance の空欄は「未評定」であって 0 ではないので、
    欠測を保てる nullable Int64 のまま扱う（0 に潰すと「まったく楽しくない」
    として集計に混ざる）。

    date は帳票上の1日（5am 始まり）。hour が 0,1,2 の枠は物理的には翌暦日の
    未明だが、原典の日の切り方に合わせて前日の date に属する。
    """
    df = pd.read_csv(CSV_FILE, parse_dates=['date'])
    if df.empty:
        return pd.DataFrame({c: pd.Series(
            dtype='datetime64[ns]' if c == 'date' else 'object')
            for c in COLUMNS})
    for col in ('hour', 'enjoyment', 'importance'):
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    df['activity'] = df['activity'].fillna('')
    df['hours'] = df['hour'].map(SLOT_HOURS).astype('Int64')
    order = {h: i for i, (h, _) in enumerate(SLOTS)}
    df['_o'] = df['hour'].map(order)
    return (df.sort_values(['date', '_o'])
              .drop(columns=['_o'])
              .reset_index(drop=True))
