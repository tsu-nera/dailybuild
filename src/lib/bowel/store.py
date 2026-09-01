"""
排便記録 CSV の読み込み

data/bowel.csv（dailybuild-private への symlink）を対象に、show 側の
読み込みをまとめる。書き込みは scripts/bowel.py の fetch が担う。
"""

from pathlib import Path

import pandas as pd

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'bowel.csv')


def load_entries() -> pd.DataFrame:
    """timestamp 昇順で読む。

    bristol は未回答・パース不能を 0 に潰さず nullable Int64 のまま扱う
    （0 は「コロコロ」の隣に来る値ではなく、単に測っていないことを示す
    ためのマーカーとして混ぜてはいけない）。
    """
    df = pd.read_csv(CSV_FILE, parse_dates=['timestamp'])
    df['bristol'] = pd.to_numeric(df['bristol'], errors='coerce').astype('Int64')
    # CSV の date 列は文字列。フィルタに使うので timestamp から引き直す
    # （日境界の補正はしない。深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.normalize()
    return df.sort_values('timestamp').reset_index(drop=True)
