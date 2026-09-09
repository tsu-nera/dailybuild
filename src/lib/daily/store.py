"""
日次記録 CSV の読み込み（朝・夜）

朝は data/daily_morning.csv、夜は data/daily_evening.csv（どちらも
dailybuild-private への symlink）。1つの CSV にマージしない理由・スキーマの
差（夜に source が無い、satisfaction/achievement に _score 接尾辞が無い）は
docs/forms.md。書き込みは scripts/daily.py の fetch / migrate-manual が担う
（ここでは行わない）。

Issue #167 でスキーマの正本を config/daily_{morning,evening}_def.yaml の
questions（順序付きリスト）1本に統合した。SLOTS が持つのは csv_file /
grid_history_file / has_source / day_start_hour という朝夜共通実装の差分点
のみで、列名・型・グリッド行・表示ラベルはすべて load_def() が読む yaml から
このモジュールが導出する（コード側に複製を持たない）。
"""

import datetime as dt
from pathlib import Path

import pandas as pd
import yaml

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

DEF_FILES = {
    'morning': BASE_DIR / 'config' / 'daily_morning_def.yaml',
    'evening': BASE_DIR / 'config' / 'daily_evening_def.yaml',
}

SLOTS = {
    'morning': {
        'csv_file': require_private_path(BASE_DIR / 'data' / 'daily_morning.csv'),
        'grid_history_file': require_private_path(
            BASE_DIR / 'data' / 'daily_morning_grid_history.csv'),
        'has_source': True,
        # date は暦日のまま（境界補正なし）。data/wearable/sleep.csv の
        # dateOfSleep（起床日）と向きを揃えるため（docs/forms.md）
        'day_start_hour': 0,
    },
    'evening': {
        'csv_file': require_private_path(BASE_DIR / 'data' / 'daily_evening.csv'),
        'grid_history_file': require_private_path(
            BASE_DIR / 'data' / 'daily_evening_grid_history.csv'),
        'has_source': False,
        # 5:00 境界（00:00-04:59 の回答は前日）。夜更かしのチェックアウトが
        # 翌日に付かないようにする（docs/forms.md）
        'day_start_hour': 5,
    },
}


def load_def(slot: str) -> dict:
    """config/daily_{slot}_def.yaml を読む（スキーマの唯一の正本）"""
    with open(DEF_FILES[slot]) as f:
        return yaml.safe_load(f)


def active_questions(conf: dict) -> list:
    """active な設問だけを yaml の並び順で返す（生きたフォームの構成）"""
    return [q for q in conf['questions'] if q.get('active', True)]


def grid_rows(conf: dict) -> list:
    """active なグリッド行の設問（フォームのグリッド item になる行）"""
    return [q for q in active_questions(conf) if q['type'] == 'grid']


def columns(slot: str, conf: dict) -> list:
    """CSV の列順。active/inactive を問わず全設問の列を含む
    （退役した設問も過去データが読めるよう列は残す）
    """
    cols = ['date', 'updated_at']
    if SLOTS[slot]['has_source']:
        cols.append('source')
    cols += [q['column'] for q in conf['questions']]
    return cols


def score_columns(conf: dict) -> list:
    """グリッド（1〜5）の CSV 列。active/inactive を問わない
    （dtype 補正はどちらも Int64 に揃えるため）
    """
    return [q['column'] for q in conf['questions'] if q['type'] == 'grid']


def number_columns(conf: dict) -> list:
    """数値設問の CSV 列。active/inactive を問わない"""
    return [q['column'] for q in conf['questions'] if q['type'] == 'number']


def display_labels(conf: dict) -> list:
    """表示用の (列名, ラベル) リスト。comment（text）と inactive は除く

    ラベルは short があればそちら。label は設問文（フォームに出る文）で、
    表のヘッダとしては長すぎることがあるため分けている。
    """
    return [(q['column'], q.get('short', q['label']))
            for q in active_questions(conf) if q['type'] != 'text']


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

    グリッドのスコアは未回答・パース不能を 0 に潰さず nullable Int64 の
    まま扱う。数値設問（HRV / EDA responses）は小数もありうるため
    nullable Float64。どちらも Forms API の TextQuestion に数値バリデー
    ションが無いためパース不能値が入りうるが、それも 0 でなく NA にする。

    CSV が無ければ（夜フォーム未作成など）、正しい列・dtype の空
    DataFrame を返す（show が落ちないように。マウント忘れの検出は
    require_private_path 側が担っている）。

    列が無い CSV（スキーマ変更前）は backfill する。emotion/store.py の
    load_entries と同じ後方互換の考え方: 列ごと無いのは「未設問」であって
    「0件」ではないので、全欠測の列として補う。
    """
    conf = load_def(slot)
    csv_file = SLOTS[slot]['csv_file']
    cols = columns(slot, conf)
    score_cols = score_columns(conf)
    number_cols = number_columns(conf)

    if csv_file.exists():
        df = pd.read_csv(csv_file)
    else:
        df = pd.DataFrame(columns=cols)

    for col in cols:
        if col not in df.columns:
            df[col] = pd.NA
    for col in score_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    for col in number_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Float64')
    df['date'] = pd.to_datetime(df['date'], format='ISO8601')
    df['comment'] = df['comment'].fillna('')
    return df[cols].sort_values('date').reset_index(drop=True)
