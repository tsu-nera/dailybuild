"""
気分記録 CSV の読み込み

data/emotion.csv（dailybuild-private への symlink）を対象に、show 側の
読み込みをまとめる。書き込みは scripts/emotion.py の fetch が担う。
"""

from pathlib import Path

import pandas as pd

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'emotion.csv')

# 複数選択は 1 セルに ';' 区切りで入る（fetch 側の都合）
LABEL_SEP = ';'


def split_labels(emotions) -> list[str]:
    """';' 区切りのラベル列を分解する。空・欠測は空リスト"""
    if pd.isna(emotions):
        return []
    return [x for x in str(emotions).split(LABEL_SEP) if x]


def load_entries() -> pd.DataFrame:
    """timestamp 昇順で読む。

    score はフォームに設問を足した 2026-08-26 より前の回答が空になる。
    0 に潰すと「最悪の気分」として集計に混ざるため、欠測を保てる
    nullable Int64 のまま扱う。
    """
    df = pd.read_csv(CSV_FILE, parse_dates=['timestamp'])
    df['score'] = pd.to_numeric(df['score'], errors='coerce').astype('Int64')
    df['emotions'] = df['emotions'].fillna('')
    df['note'] = df['note'].fillna('')
    # CSV の date 列は文字列。フィルタに使うので timestamp から引き直す
    # （fetch と同じく日境界の補正はしない。深夜の記録もその日付のまま）
    df['date'] = df['timestamp'].dt.normalize()
    return df.sort_values('timestamp').reset_index(drop=True)
