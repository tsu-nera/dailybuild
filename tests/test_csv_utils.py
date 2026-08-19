"""merge_csv() のテスト（Issue #43: セル単位マージへの回帰防止）"""

from pathlib import Path

import pandas as pd

from lib.utils.csv_utils import merge_csv


def _write_csv(path: Path, df: pd.DataFrame) -> None:
    df.to_csv(path)


def test_missing_column_in_new_data_is_preserved(tmp_path: Path):
    """df_new に存在しない列（非アクティブ指標）の既存値が保持されること（本件の再現テスト）"""
    csv_path = tmp_path / "manual.csv"
    df_old = pd.DataFrame(
        {
            "core_temperature": [36.4, 36.3],
            "mind_score": [2, 3],
            "comment": ["a", "b"],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    df_old.index.name = "date"
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame(
        {
            "mind_score": [9, 8],
            "comment": ["x", "y"],
        },
        index=pd.to_datetime(["2026-01-02", "2026-01-03"]),
    )
    df_new.index.name = "date"

    df_merged = merge_csv(df_new, csv_path, "date")

    assert df_merged.loc["2026-01-01", "core_temperature"] == 36.4
    assert df_merged.loc["2026-01-02", "core_temperature"] == 36.3
    assert pd.isna(df_merged.loc["2026-01-03", "core_temperature"])


def test_new_date_row_is_added(tmp_path: Path):
    """新規日付の行が追加されること"""
    csv_path = tmp_path / "manual.csv"
    df_old = pd.DataFrame(
        {"mind_score": [2]}, index=pd.to_datetime(["2026-01-01"])
    )
    df_old.index.name = "date"
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame(
        {"mind_score": [5]}, index=pd.to_datetime(["2026-01-02"])
    )
    df_new.index.name = "date"

    df_merged = merge_csv(df_new, csv_path, "date")

    assert list(df_merged.index.strftime("%Y-%m-%d")) == ["2026-01-01", "2026-01-02"]
    assert df_merged.loc["2026-01-02", "mind_score"] == 5


def test_existing_value_overwritten_by_new_value(tmp_path: Path):
    """既存日付の値が df_new の値で上書きされること"""
    csv_path = tmp_path / "manual.csv"
    df_old = pd.DataFrame(
        {"mind_score": [2]}, index=pd.to_datetime(["2026-01-01"])
    )
    df_old.index.name = "date"
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame(
        {"mind_score": [9]}, index=pd.to_datetime(["2026-01-01"])
    )
    df_new.index.name = "date"

    df_merged = merge_csv(df_new, csv_path, "date")

    assert df_merged.loc["2026-01-01", "mind_score"] == 9


def test_column_order_preserved_from_existing_csv(tmp_path: Path):
    """列順が既存CSVの順序で保たれること"""
    csv_path = tmp_path / "manual.csv"
    df_old = pd.DataFrame(
        {
            "core_temperature": [36.4],
            "mind_score": [2],
            "comment": ["a"],
        },
        index=pd.to_datetime(["2026-01-01"]),
    )
    df_old.index.name = "date"
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame(
        {
            "mind_score": [9],
            "comment": ["x"],
        },
        index=pd.to_datetime(["2026-01-02"]),
    )
    df_new.index.name = "date"

    df_merged = merge_csv(df_new, csv_path, "date")

    assert list(df_merged.columns) == ["core_temperature", "mind_score", "comment"]


def test_new_column_in_new_data_appended_at_end(tmp_path: Path):
    """df_new に新規列がある場合、末尾に追加されること"""
    csv_path = tmp_path / "manual.csv"
    df_old = pd.DataFrame(
        {"mind_score": [2]}, index=pd.to_datetime(["2026-01-01"])
    )
    df_old.index.name = "date"
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame(
        {"mind_score": [9], "sickness_score": [1]},
        index=pd.to_datetime(["2026-01-02"]),
    )
    df_new.index.name = "date"

    df_merged = merge_csv(df_new, csv_path, "date")

    assert list(df_merged.columns) == ["mind_score", "sickness_score"]


def test_duplicated_index_in_new_data_keeps_last_row(tmp_path: Path):
    """df_new の index に重複がある場合も例外にならず、最後の行が採用されること"""
    csv_path = tmp_path / "manual.csv"
    df_old = pd.DataFrame(
        {"mind_score": [2]}, index=pd.to_datetime(["2026-01-01"])
    )
    df_old.index.name = "date"
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame(
        {"mind_score": [7, 10]},
        index=pd.to_datetime(["2026-01-02", "2026-01-02"]),
    )
    df_new.index.name = "date"

    df_merged = merge_csv(df_new, csv_path, "date")

    assert df_merged.loc["2026-01-02", "mind_score"] == 10
    assert len(df_merged) == 2


def test_large_integer_ids_are_not_rounded(tmp_path: Path):
    """19桁の整数ID（logId等）が combine_first のfloat昇格で丸められないこと"""
    csv_path = tmp_path / "activity_logs.csv"
    df_old = pd.DataFrame(
        {"logId": [5667773472718017992, 8694685614035756360]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    df_old.index.name = "date"
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame(
        {"logId": [1001717290611444584]},
        index=pd.to_datetime(["2026-01-03"]),
    )
    df_new.index.name = "date"

    df_merged = merge_csv(df_new, csv_path, "date")

    # 文字列比較で桁の丸めが起きていないことを確認
    assert str(df_merged.loc["2026-01-01", "logId"]) == "5667773472718017992"
    assert str(df_merged.loc["2026-01-02", "logId"]) == "8694685614035756360"
    assert str(df_merged.loc["2026-01-03", "logId"]) == "1001717290611444584"

    # CSVに書き出して読み直す往復でも精度が保たれること
    roundtrip_path = tmp_path / "activity_logs_roundtrip.csv"
    df_merged.to_csv(roundtrip_path)
    df_roundtrip = pd.read_csv(roundtrip_path, index_col="date")
    assert str(df_roundtrip.loc["2026-01-01", "logId"]) == "5667773472718017992"
    assert str(df_roundtrip.loc["2026-01-02", "logId"]) == "8694685614035756360"
