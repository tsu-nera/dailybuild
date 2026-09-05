"""
日次記録 CSV の読み込み

data/daily_summary.csv（dailybuild-private への symlink）を対象に、show 側の
読み込みをまとめる。書き込みは scripts/daily_summary.py の fetch /
migrate-manual が担う（ここでは行わない）。
"""

from pathlib import Path

import pandas as pd

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'daily_summary.csv')

COLUMNS = ['date', 'updated_at', 'source', 'mind_score', 'body_score',
          'head_score', 'sleep_score', 'comment']
SCORE_COLUMNS = ['mind_score', 'body_score', 'head_score', 'sleep_score']


def load_entries() -> pd.DataFrame:
    """date 昇順で読む。

    スコアは未回答・パース不能を 0 に潰さず nullable Int64 のまま扱う
    （manual.csv からの移行期・グリッド未回答の行が混在するため、欠測を
    0 として捏造しない）。

    列が無い CSV（スキーマ変更前）は backfill する。emotion/store.py の
    load_entries と同じ後方互換の考え方: 列ごと無いのは「未設問」であって
    「0件」ではないので、全欠測の列として補う。
    """
    df = pd.read_csv(CSV_FILE)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    for col in SCORE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    df['date'] = pd.to_datetime(df['date'], format='ISO8601')
    df['comment'] = df['comment'].fillna('')
    return df[COLUMNS].sort_values('date').reset_index(drop=True)
