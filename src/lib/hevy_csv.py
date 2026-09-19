#!/usr/bin/env python
# coding: utf-8
"""
Hevy App CSVパーサー

Hevy fitness tracking appからエクスポートされたCSVファイルを読み込み、
標準化されたDataFrameに変換する。

CSV Format (Hevy):
- start_time: "13 Dec 2025, 15:11" / "5 9月 2026, 20:39" 形式
- exercise_title: エクササイズ名
- weight_kg: 重量（kg、自重の場合は空）
- reps: 回数
- その他: set_index, set_type, rpe, etc.

**日時の月名はアプリの表示言語で変わる**。英語表記と日本語表記（`9月`）の
どちらも同じ列に入りうるので、月名を正規化してから1度だけパースする。
パースできない値は NaT にせず例外にする（日付が欠けた行を黙って落とすと
その週のセットが消え、欠測の捏造になる）。
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd

# 日本語ロケールの月名 → pandas が解釈できる英語の月名略記
_EN_MONTH_ABBR = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
_JP_MONTH_RE = re.compile(r'(?<!\d)(1[0-2]|[1-9])月')

_DATETIME_FORMAT = '%d %b %Y, %H:%M'


def _normalize_exercise(title):
    """種目名の表記ゆれを畳む（NFKC 正規化 → 連続空白を1つに → 前後 strip）

    全角括弧・全角スペースと半角の混在（`ベンチプレス (ダンベル)` /
    `ベンチプレス　（ダンベル）`）が同じ種目として集計されるようにする。
    正規化前の値は残さない（元データは data/hevy/workouts.csv に残る）。
    """
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', title)).strip()


def _to_datetime(series, column):
    """Hevy の日時列を datetime に変換する（英語表記・日本語表記の両対応）"""
    normalized = series.astype('string').str.replace(
        _JP_MONTH_RE,
        lambda m: _EN_MONTH_ABBR[int(m.group(1)) - 1],
        regex=True,
    )
    parsed = pd.to_datetime(normalized, format=_DATETIME_FORMAT, errors='coerce')

    failed = parsed.isna() & series.notna()
    if failed.any():
        samples = series[failed].unique()[:3].tolist()
        raise ValueError(
            f'{column} をパースできない値がある（{int(failed.sum())}件）: {samples}。'
            f'期待する形式は "{_DATETIME_FORMAT}"（月名は英語表記か日本語表記）'
        )
    return parsed


def parse_hevy_csv(csv_path):
    """
    Hevy appのCSVを読み込み、標準化されたDataFrameに変換

    Parameters
    ----------
    csv_path : str or Path
        workouts.csv (Hevy形式) のパス

    Returns
    -------
    DataFrame
        標準化されたDataFrame:
        - start_dt: datetime型
        - exercise_title: str
        - weight_kg: float (nullable)
        - reps: int
        - その他メタデータ (title, set_index, set_type, rpe, etc.)

    Examples
    --------
    >>> df = parse_hevy_csv('data/workouts.csv')
    >>> df.columns
    Index(['title', 'start_dt', 'end_dt', 'description', 'exercise_title',
           'superset_id', 'exercise_notes', 'set_index', 'set_type',
           'weight_kg', 'reps', 'distance_km', 'duration_seconds', 'rpe'],
          dtype='object')
    """
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    # CSVを読み込み
    df = pd.read_csv(csv_path)

    # Hevy特有の日時フォーマットを解析
    # 例: "13 Dec 2025, 15:11" / "5 9月 2026, 20:39" -> datetime
    df['start_dt'] = _to_datetime(df['start_time'], 'start_time')
    df['end_dt'] = _to_datetime(df['end_time'], 'end_time')

    # 種目名の表記ゆれ（全角/半角の括弧・スペース）を畳む
    df['exercise_title'] = df['exercise_title'].astype('string').map(_normalize_exercise)

    # データ型を適切に変換
    df['weight_kg'] = pd.to_numeric(df['weight_kg'], errors='coerce')
    df['reps'] = pd.to_numeric(df['reps'], errors='coerce').fillna(0).astype(int)
    df['set_index'] = pd.to_numeric(df['set_index'], errors='coerce').fillna(0).astype(int)

    # オプショナルカラムの処理
    if 'distance_km' in df.columns:
        df['distance_km'] = pd.to_numeric(df['distance_km'], errors='coerce')
    if 'duration_seconds' in df.columns:
        df['duration_seconds'] = pd.to_numeric(df['duration_seconds'], errors='coerce')
    if 'rpe' in df.columns:
        df['rpe'] = pd.to_numeric(df['rpe'], errors='coerce')

    return df


def parse_hevy_measurements(csv_path):
    """
    Hevy app の measurement CSV を読み込み、標準化された DataFrame に変換

    列は `date` と測定値（`weight_kg` / `fat_percent` / 周囲径17項目）。
    時刻は全行 00:00 なので日付だけを持つ。

    **空欄は 0 ではなく未測定。** Hevy は測っていない項目を空で返すため
    fillna しない（0 で埋めると「腹囲 0cm」を実測として集計する）。

    Parameters
    ----------
    csv_path : str or Path
        measurement_data.csv (Hevy形式) のパス

    Returns
    -------
    DataFrame
        - date: date 型（datetime の日付部分）
        - 残りの列は float（未測定は NaN）
    """
    csv_path = Path(csv_path)

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(csv_path)

    df['date'] = _to_datetime(df['date'], 'date').dt.date

    for column in df.columns:
        if column != 'date':
            df[column] = pd.to_numeric(df[column], errors='coerce')

    return df.sort_values('date').reset_index(drop=True)
