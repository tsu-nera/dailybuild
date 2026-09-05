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
                         sort_by: list[str] | None = None,
                         preserve_existing_on_nan: bool = False) -> pd.DataFrame:
    """
    既存CSVとマージ（複数列で重複判定）

    既定（preserve_existing_on_nan=False）は行単位の置換: キーが重なった行は
    df_new の行でまるごと上書きする（従来通りの挙動、全呼び出し元の後方互換）。

    preserve_existing_on_nan=True にすると `merge_csv`（index版）と同じセル単位
    のマージに切り替わる。df_new を優先しつつ、df_new でNaN、または列ごと
    存在しないセルは df_old の値で埋める。combine_first ではなく object dtype
    経由の reindex + where でマージする（`merge_csv` と同じ理由: combine_first は
    union index への reindex 過程で int64 列を float64 に昇格させ、19桁の logId
    のような大きな整数が丸められて壊れる）。

    代償: 有効にした経路では既存値を NaN へ戻せなくなる（新データの NaN が
    既存値で埋まるため）。Google Forms の回答のように実質追記のみのデータ
    源では問題にならないが、値を意図的に空へ更新したい経路では使わないこと。

    Args:
        df_new: 新しいデータ
        csv_path: 既存CSVのパス
        key_columns: 重複判定に使う列名リスト
        parse_dates: 日付としてパースする列名リスト
        sort_by: ソートに使う列名リスト
        preserve_existing_on_nan: True でセル単位マージ（opt-in）。既定 False は
            従来通りの行単位置換

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

    if preserve_existing_on_nan:
        df_merged = _merge_by_columns_preserve_existing(df_old, df_new_copy, key_columns)
    else:
        df_merged = pd.concat([df_old, df_new_copy])
        df_merged = df_merged.drop_duplicates(subset=key_columns, keep='last')

    if sort_by:
        df_merged.sort_values(sort_by, inplace=True)

    return df_merged


def _merge_by_columns_preserve_existing(df_old: pd.DataFrame, df_new: pd.DataFrame,
                                        key_columns: list[str]) -> pd.DataFrame:
    """merge_csv_by_columns の preserve_existing_on_nan=True 用セル単位マージ

    key_columns を index にした上で merge_csv と同じ astype(object) ->
    reindex -> where の手順を適用し、最後に reset_index で列順を戻す。
    """
    old_indexed = df_old.set_index(key_columns)
    new_indexed = df_new.set_index(key_columns)

    # reindex は重複indexがあると例外になるため先に排除する
    old_indexed = old_indexed[~old_indexed.index.duplicated(keep='last')]
    new_indexed = new_indexed[~new_indexed.index.duplicated(keep='last')]

    all_index = new_indexed.index.union(old_indexed.index)
    columns = (list(old_indexed.columns)
               + [c for c in new_indexed.columns if c not in old_indexed.columns])

    # astype(object) を reindex より先に行う。順序を逆にすると欠損補完の過程で
    # int64 が float64 に昇格し、19桁の logId 等が丸められる
    old_aligned = old_indexed.astype(object).reindex(index=all_index, columns=columns)
    new_aligned = new_indexed.astype(object).reindex(index=all_index, columns=columns)

    df_merged = new_aligned.where(new_aligned.notna(), old_aligned)

    return df_merged.reset_index()


def replace_csv_period(df_new: pd.DataFrame, csv_path: Path, date_column: str,
                       start_date, end_date,
                       sort_by: list[str] | None = None,
                       label: str | None = None) -> pd.DataFrame:
    """
    既存CSVのうち、df_new に日付が存在する行だけを削除し、df_new に置き換える
    （キーマージしない）

    merge_csv / merge_csv_by_columns はどちらも「キー（index や logId 等）が
    一致した行を上書きする」設計だが、それが成立しない移行元切り替え
    （Fitbit -> Google Health の sleep / temperature_core 等）では使えない:

    - キー空間が別物: logId は取得元ごとに独立した採番で、同じ夜でも
      Fitbit と Google で一致しない。キーにすると同じ夜が2行として
      積み上がり、レポートが二重計上する
    - 時刻も一致しない: 開始時刻が取得元間で最大30分ずれることがあり、
      時刻をキーにしても一致しない

    「期間内の既存行をすべて削除」ではなく「新データに存在する日付の既存行
    だけを削除」する。取得期間を渡しても、Google 側にその日のデータが
    無ければ何も削除しない。**Google にデータが無いことは既存行を消してよい
    理由にならない**（このリポジトリの規約「黙って欠測を捏造しない」の裏返し
    で、取り替えられない行を黙って消すのも同じ問題）。
    例: temperature_core は Google 側の実測日が既存 CSV の日付集合の
    サブセットで、期間内すべて削除する実装だと 2026-01 〜 05 の Fitbit 由来の
    日次行が丸ごと消えていた（Issue #75 PR #84 レビューで発覚）。

    1日に複数セッション（昼寝、複数回の体温測定等）があってもキー衝突が
    起きず、取得元混在によるレポートの二重計上も起きない。

    この関数は sleep と temperature_core の両方から呼ばれる
    （src/lib/googlehealth_fetcher.py の _save_period_replace 経由）。

    Args:
        df_new: 新しいデータ（date_column を含む）
        csv_path: 既存CSVのパス
        date_column: 期間判定に使う日付列名。日時（"YYYY-MM-DD HH:MM:SS"）でもよい
        start_date: 削除・置換の対象となりうる期間の開始日（この日を含む）
        end_date: 削除・置換の対象となりうる期間の終了日（この日を含む）
        sort_by: ソートに使う列名リスト
        label: 警告メッセージに出す名前（省略時は date_column を使う）

    Returns:
        置換後のDataFrame（df_new に無い日付の既存行 + df_new）
    """
    if not csv_path.exists():
        df_merged = df_new.copy()
    else:
        df_old = pd.read_csv(csv_path)
        # date_column が日時（"YYYY-MM-DD HH:MM:SS"）だと、素の文字列比較では
        # end_date 当日で時刻付きの値が end_s（時刻無し）より辞書順で大きくなり
        # 「期間内」から漏れる（例: "2026-08-23 05:49:21" > "2026-08-23"）。
        # 先頭10文字（日付部分）だけで比較する
        old_dates = df_old[date_column].astype(str).str[:10]
        new_dates = set(df_new[date_column].astype(str).str[:10]) if len(df_new) else set()

        to_replace = old_dates.isin(new_dates)
        df_merged = pd.concat([df_old[~to_replace], df_new], ignore_index=True)

        # 期間内だが新データに1件も無い日付は、黙って残さず警告する
        start_s, end_s = str(start_date), str(end_date)
        in_period = old_dates.between(start_s, end_s)
        preserved = sorted(set(old_dates[in_period & ~to_replace]))
        if preserved:
            shown = ', '.join(preserved[:5])
            more = f' 他{len(preserved) - 5}件' if len(preserved) > 5 else ''
            name = label or date_column
            print(f'  ⚠️ {name}: 期間内で Google にデータが無い{len(preserved)}日は'
                  f'既存行を残した（{shown}{more}）')

    # df_new が空（例: 昼寝なしでshortAwakeningsが1件も無い日のsleep_levels）だと
    # 列が無く sort_values が KeyError になるため、その場合はソートを飛ばす
    if sort_by and all(c in df_merged.columns for c in sort_by):
        df_merged.sort_values(sort_by, inplace=True)

    return df_merged
