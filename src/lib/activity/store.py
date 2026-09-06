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

COLUMNS = ['timestamp', 'date', 'activity', 'enjoyment', 'importance', 'note']


def load_entries() -> pd.DataFrame:
    """timestamp 昇順で読む。

    enjoyment / importance の空欄は「未評定」であって 0 ではないので、
    欠測を保てる nullable Int64 のまま扱う（0 に潰すと「まったく楽しくない」
    として集計に混ざる）。
    """
    df = pd.read_csv(CSV_FILE, parse_dates=['timestamp'])
    if df.empty:
        # 空でも列と dtype を保つ。0行を「記録なし」として扱えるようにする
        return pd.DataFrame({c: pd.Series(dtype='datetime64[ns]' if c in
                             ('timestamp', 'date') else 'object')
                             for c in COLUMNS})
    for col in ('enjoyment', 'importance'):
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    df['activity'] = df['activity'].fillna('')
    df['note'] = df['note'].fillna('')
    df['date'] = df['timestamp'].dt.normalize()
    return df.sort_values('timestamp').reset_index(drop=True)
