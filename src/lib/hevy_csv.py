#!/usr/bin/env python
# coding: utf-8
"""
Hevy App CSVパーサー

Hevy fitness tracking appからエクスポートされたCSVファイルを読み込み、
標準化されたDataFrameに変換する。

CSV Format (Hevy):
- start_time: "13 Dec 2025, 15:11" 形式
- exercise_title: エクササイズ名
- weight_kg: 重量（kg、自重の場合は空）
- reps: 回数
- その他: set_index, set_type, rpe, etc.
"""

import pandas as pd
from pathlib import Path


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
    # 例: "13 Dec 2025, 15:11" -> datetime
    df['start_dt'] = pd.to_datetime(df['start_time'], format='%d %b %Y, %H:%M')
    df['end_dt'] = pd.to_datetime(df['end_time'], format='%d %b %Y, %H:%M')

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
