"""
CSV追記・マージユーティリティ
"""

from pathlib import Path
import pandas as pd


def merge_csv(df_new: pd.DataFrame, csv_path: Path, index_col: str) -> pd.DataFrame:
    """
    既存CSVとマージ（インデックス列で重複判定）

    Args:
        df_new: 新しいデータ（index設定済み）
        csv_path: 既存CSVのパス
        index_col: インデックス列名

    Returns:
        マージ済みDataFrame（重複は新しいデータを優先）
    """
    if not csv_path.exists():
        return df_new

    df_old = pd.read_csv(csv_path, parse_dates=[index_col], index_col=index_col)
    df_merged = pd.concat([df_old, df_new])
    df_merged = df_merged[~df_merged.index.duplicated(keep='last')]
    df_merged.sort_index(inplace=True)
    return df_merged


def merge_csv_by_columns(df_new: pd.DataFrame, csv_path: Path,
                         key_columns: list[str],
                         parse_dates: list[str] | None = None,
                         sort_by: list[str] | None = None) -> pd.DataFrame:
    """
    既存CSVとマージ（複数列で重複判定）

    Args:
        df_new: 新しいデータ
        csv_path: 既存CSVのパス
        key_columns: 重複判定に使う列名リスト
        parse_dates: 日付としてパースする列名リスト
        sort_by: ソートに使う列名リスト

    Returns:
        マージ済みDataFrame（重複は新しいデータを優先）
    """
    if not csv_path.exists():
        return df_new

    df_old = pd.read_csv(csv_path, parse_dates=parse_dates or [])

    # df_newもparse_datesで指定された列をdatetime型に変換して型を統一
    df_new_copy = df_new.copy()
    if parse_dates:
        for col in parse_dates:
            if col in df_new_copy.columns:
                df_new_copy[col] = pd.to_datetime(df_new_copy[col])

    df_merged = pd.concat([df_old, df_new_copy])
    df_merged = df_merged.drop_duplicates(subset=key_columns, keep='last')

    if sort_by:
        df_merged.sort_values(sort_by, inplace=True)

    return df_merged
