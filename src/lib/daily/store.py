"""
日次記録 CSV の読み込み（朝・夜）

朝は data/daily_morning.csv、夜は data/daily_evening.csv（どちらも
dailybuild-private への symlink）。1つの CSV にマージしない理由・スキーマの
差（夜に source が無い、satisfaction/achievement に _score 接尾辞が無い）は
docs/forms.md。書き込みは scripts/daily.py の fetch / migrate-manual が担う
（ここでは行わない）。

SLOTS が朝夜共通実装の唯一の差分点。fetch/show/setup-form の本体
（scripts/daily.py）はここを見て振る舞いを変える。grid_column_map は
フォームのグリッド行キー（questions/grid_rows で使うキー）から CSV 列名への
対応。朝は mind/body/head/sleep が f'{k}_score' に一致するが、夜の
satisfaction/achievement は接尾辞が無いため、f'{k}_score' の決め打ちにせず
ここで明示する。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

SLOTS = {
    'morning': {
        'csv_file': require_private_path(BASE_DIR / 'data' / 'daily_morning.csv'),
        'grid_history_file': require_private_path(
            BASE_DIR / 'data' / 'daily_morning_grid_history.csv'),
        'columns': ['date', 'updated_at', 'source', 'mind_score', 'body_score',
                    'head_score', 'sleep_score', 'comment'],
        'score_columns': ['mind_score', 'body_score', 'head_score', 'sleep_score'],
        'grid_rows': ['mind', 'body', 'head', 'sleep'],
        'grid_column_map': {'mind': 'mind_score', 'body': 'body_score',
                            'head': 'head_score', 'sleep': 'sleep_score'},
        'display_labels': [('mind_score', '気分'), ('body_score', '身体'),
                           ('head_score', '頭'), ('sleep_score', '睡眠')],
        'has_source': True,
        # date は暦日のまま（境界補正なし）。data/wearable/sleep.csv の
        # dateOfSleep（起床日）と向きを揃えるため（docs/forms.md）
        'day_start_hour': 0,
    },
    'evening': {
        'csv_file': require_private_path(BASE_DIR / 'data' / 'daily_evening.csv'),
        'grid_history_file': require_private_path(
            BASE_DIR / 'data' / 'daily_evening_grid_history.csv'),
        'columns': ['date', 'updated_at', 'mind_score', 'body_score', 'head_score',
                    'satisfaction', 'achievement', 'comment'],
        'score_columns': ['mind_score', 'body_score', 'head_score',
                          'satisfaction', 'achievement'],
        'grid_rows': ['mind', 'body', 'head', 'satisfaction', 'achievement'],
        'grid_column_map': {'mind': 'mind_score', 'body': 'body_score',
                            'head': 'head_score', 'satisfaction': 'satisfaction',
                            'achievement': 'achievement'},
        'display_labels': [('mind_score', '気分'), ('body_score', '身体'),
                           ('head_score', '頭'), ('satisfaction', '満足感'),
                           ('achievement', '達成感')],
        'has_source': False,
        # 5:00 境界（00:00-04:59 の回答は前日）。夜更かしのチェックアウトが
        # 翌日に付かないようにする（docs/forms.md）
        'day_start_hour': 5,
    },
}


def response_date(ts: pd.Timestamp, day_start_hour: int) -> dt.date:
    """回答時刻（JST naive）から帳票上の date を作る

    day_start_hour 時より前の回答は前日に帰属する。day_start_hour=0（朝）は
    補正なし。day_start_hour=5（夜）は 00:00-04:59 の回答が前日になる。
    """
    d = ts.date()
    if ts.hour < day_start_hour:
        d = d - dt.timedelta(days=1)
    return d


def load_entries(slot: str) -> pd.DataFrame:
    """slot（'morning'/'evening'）の記録を date 昇順で読む。

    スコアは未回答・パース不能を 0 に潰さず nullable Int64 のまま扱う。

    CSV が無ければ（夜フォーム未作成など）、正しい列・dtype の空
    DataFrame を返す（show が落ちないように。マウント忘れの検出は
    require_private_path 側が担っている）。

    列が無い CSV（スキーマ変更前）は backfill する。emotion/store.py の
    load_entries と同じ後方互換の考え方: 列ごと無いのは「未設問」であって
    「0件」ではないので、全欠測の列として補う。
    """
    conf = SLOTS[slot]
    csv_file = conf['csv_file']
    columns = conf['columns']
    score_columns = conf['score_columns']

    if csv_file.exists():
        df = pd.read_csv(csv_file)
    else:
        df = pd.DataFrame(columns=columns)

    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    for col in score_columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    df['date'] = pd.to_datetime(df['date'], format='ISO8601')
    df['comment'] = df['comment'].fillna('')
    return df[columns].sort_values('date').reset_index(drop=True)
