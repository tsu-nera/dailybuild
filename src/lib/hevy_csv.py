#!/usr/bin/env python
# coding: utf-8
"""
Hevy App CSVパーサー

Hevy fitness tracking appからエクスポートされたCSVファイルを読み込み、
標準化されたDataFrameに変換する。

CSV Format (Hevy):
- start_time: "5 9月 2026, 20:39"（日本語ロケール）または
  "13 Dec 2025, 15:11"（英語ロケール）形式。export はアプリのロケールに従う
- exercise_title: エクササイズ名
- weight_kg: 重量（kg、自重の場合は空）
- reps: 回数
- その他: set_index, set_type, rpe, etc.
"""

import re

import pandas as pd
from pathlib import Path


# Hevy の export はアプリのロケールに従う。日本語ロケールは "5 9月 2026, 20:39"、
# 英語ロケールは "13 Dec 2025, 15:11"。前者を "5 9 2026, 20:39" に均してから
# 英語月名・数値月の順に試す。
_JP_MONTH_RE = re.compile(r'(\d{1,2})月')

_DATE_FORMATS = (
    '%d %b %Y, %H:%M',  # 英語ロケール: "13 Dec 2025, 15:11"
    '%d %m %Y, %H:%M',  # 日本語ロケール正規化後: "5 9 2026, 20:39"
)


def _parse_hevy_datetime(series: pd.Series, column: str) -> pd.Series:
    """Hevy の日時文字列列を英語・日本語の両ロケールで解釈する

    NaT への素通し（errors='coerce'）はしない。解釈できない行が残ったら
    例外で落とし、壊れた日時が黙って CSV に書かれるのを防ぐ。
    """
    normalized = series.astype(str).str.replace(_JP_MONTH_RE, r'\1', regex=True)

    parsed = pd.Series(pd.NaT, index=series.index, dtype='datetime64[ns]')
    remaining = normalized

    for fmt in _DATE_FORMATS:
        if remaining.empty:
            break
        candidate = pd.to_datetime(remaining, format=fmt, errors='coerce')
        filled = candidate.notna()
        parsed.loc[filled.index[filled]] = candidate[filled]
        remaining = remaining[~filled]

    if not remaining.empty:
        sample = series.loc[remaining.index].unique()[:5]
        raise ValueError(
            f"{column} 列に解釈できない日時が {len(remaining)}件あります。"
            f"サンプル: {list(sample)}"
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

    # Hevy特有の日時フォーマットを解析（英語・日本語ロケールの両対応）
    # 例: "13 Dec 2025, 15:11" / "5 9月 2026, 20:39" -> datetime
    df['start_dt'] = _parse_hevy_datetime(df['start_time'], 'start_time')
    df['end_dt'] = _parse_hevy_datetime(df['end_time'], 'end_time')

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
