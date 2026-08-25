"""
CSV追記・マージユーティリティ
"""

from pathlib import Path
import pandas as pd


def merge_csv(df_new: pd.DataFrame, csv_path: Path, index_col: str) -> pd.DataFrame:
    """
    既存CSVとセル単位でマージ（インデックス列で重複判定）

    df_new を優先しつつ、df_new でNaN、または列ごと存在しないセルは
    df_old の値で埋める。行単位の上書きではないため、取得しなかった
    列（非アクティブ指標など）の既存値が消えない。

    combine_first ではなく object dtype 経由の reindex + where でマージする。
    combine_first は union index への reindex 過程で int64 列を float64 に
    昇格させるため、19桁の logId のような大きな整数が丸められて壊れる。

    Args:
        df_new: 新しいデータ（index設定済み）
        csv_path: 既存CSVのパス
        index_col: インデックス列名

    Returns:
        マージ済みDataFrame（セルごとにdf_newを優先、df_newがNaNならdf_oldで補完）
    """
    if not csv_path.exists():
        return df_new

    df_old = pd.read_csv(csv_path, parse_dates=[index_col], index_col=index_col)

    # インデックスの型を統一（datetimeに変換）
    df_new = df_new.copy()
    df_new.index = pd.to_datetime(df_new.index, format='mixed')
    df_old.index = pd.to_datetime(df_old.index, format='mixed')

    # reindex は重複indexがあると例外になるため先に排除する
    df_new = df_new[~df_new.index.duplicated(keep='last')]
    df_old = df_old[~df_old.index.duplicated(keep='last')]

    all_index = df_new.index.union(df_old.index)
    columns = list(df_old.columns) + [c for c in df_new.columns if c not in df_old.columns]

    # astype(object) を reindex より先に行う。順序を逆にすると欠損補完の過程で
    # int64 が float64 に昇格し、19桁の logId 等が丸められる
    old_aligned = df_old.astype(object).reindex(index=all_index, columns=columns)
    new_aligned = df_new.astype(object).reindex(index=all_index, columns=columns)

    df_merged = new_aligned.where(new_aligned.notna(), old_aligned)

    return df_merged.sort_index()


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
        # 初回もソートする。ここを素通りすると取得順のまま書かれ、
        # 次回マージまで並びが直らない
        return df_new.sort_values(sort_by) if sort_by else df_new

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


def replace_csv_period(df_new: pd.DataFrame, csv_path: Path, date_column: str,
                       start_date, end_date,
                       sort_by: list[str] | None = None) -> pd.DataFrame:
    """
    既存CSVの指定期間の行を丸ごと削除し、df_new に置き換える（キーマージしない）

    merge_csv / merge_csv_by_columns はどちらも「キー（index や logId 等）が
    一致した行を上書きする」設計だが、それが成立しない移行元切り替え
    （Fitbit -> Google Health の sleep 等）では使えない:

    - キー空間が別物: logId は取得元ごとに独立した採番で、同じ夜でも
      Fitbit と Google で一致しない。キーにすると同じ夜が2行として
      積み上がり、レポートが二重計上する
    - 時刻も一致しない: 開始時刻が取得元間で最大30分ずれることがあり、
      時刻をキーにしても一致しない

    そこで「取得元を切り替えた期間は、その期間の既存行を無条件に捨てて
    新データで置き換える」戦略を取る。1日に複数セッション（昼寝等）が
    あってもキー衝突が起きず、取得元混在によるレポートの二重計上も
    起きない。

    Args:
        df_new: 新しいデータ（date_column を含む）
        csv_path: 既存CSVのパス
        date_column: 期間判定に使う日付列名
        start_date: 削除・置換する期間の開始日（この日を含む）
        end_date: 削除・置換する期間の終了日（この日を含む）
        sort_by: ソートに使う列名リスト

    Returns:
        置換後のDataFrame（期間外の既存行 + df_new）
    """
    if not csv_path.exists():
        df_merged = df_new.copy()
    else:
        df_old = pd.read_csv(csv_path)
        start_s, end_s = str(start_date), str(end_date)
        outside_period = ~df_old[date_column].astype(str).between(start_s, end_s)
        df_merged = pd.concat([df_old[outside_period], df_new], ignore_index=True)

    # df_new が空（例: 昼寝なしでshortAwakeningsが1件も無い日のsleep_levels）だと
    # 列が無く sort_values が KeyError になるため、その場合はソートを飛ばす
    if sort_by and all(c in df_merged.columns for c in sort_by):
        df_merged.sort_values(sort_by, inplace=True)

    return df_merged
