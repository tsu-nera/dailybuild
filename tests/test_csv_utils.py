"""merge_csv() / merge_csv_by_columns() / replace_csv_period() のテスト（Issue #43, #75, #103）"""

from pathlib import Path

import pandas as pd

from lib.utils.csv_utils import merge_csv, merge_csv_by_columns, replace_csv_period


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


# =============================================================================
# merge_csv_by_columns（Issue #103: preserve_existing_on_nan=True でセル単位
# マージに切り替える。既定は従来通りの行単位置換で後方互換を固定する）
# =============================================================================

def test_merge_by_columns_preserve_existing_keeps_nan_overwritten_score(tmp_path: Path):
    """preserve_existing_on_nan=True で、再fetchのNaNが既存scoreを消さないこと（本件の再現）"""
    csv_path = tmp_path / "emotion.csv"
    df_old = pd.DataFrame({
        "timestamp": ["2026-08-26 22:42:00", "2026-08-27 05:30:00"],
        "date": ["2026-08-26", "2026-08-27"],
        "emotions": ["落ち着いている", "落ち着いている"],
        "score": [3, 3],
    })
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame({
        "timestamp": ["2026-08-26 22:42:00", "2026-08-27 05:30:00"],
        "date": ["2026-08-26", "2026-08-27"],
        "emotions": ["落ち着いている", "落ち着いている"],
        "score": [None, None],
    })

    df_merged = merge_csv_by_columns(
        df_new, csv_path,
        key_columns=["timestamp"],
        parse_dates=["timestamp"],
        preserve_existing_on_nan=True,
    )

    scores = df_merged.set_index("timestamp")["score"]
    assert scores["2026-08-26 22:42:00"] == 3
    assert scores["2026-08-27 05:30:00"] == 3


def test_merge_by_columns_preserve_existing_adds_new_row(tmp_path: Path):
    """preserve_existing_on_nan=True で、新規行の追加が入り新列に値が入ること"""
    csv_path = tmp_path / "emotion.csv"
    df_old = pd.DataFrame({
        "timestamp": ["2026-08-26 22:42:00"],
        "score": [3],
    })
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame({
        "timestamp": ["2026-08-27 05:30:00"],
        "score": [4],
        "body": ["肩"],
    })

    df_merged = merge_csv_by_columns(
        df_new, csv_path,
        key_columns=["timestamp"],
        parse_dates=["timestamp"],
        preserve_existing_on_nan=True,
    )

    assert len(df_merged) == 2
    new_row = df_merged.set_index("timestamp").loc["2026-08-27 05:30:00"]
    assert new_row["score"] == 4
    assert new_row["body"] == "肩"


def test_merge_by_columns_preserve_existing_updates_value(tmp_path: Path):
    """preserve_existing_on_nan=True で、既存行の値の更新（3->5）が反映されること"""
    csv_path = tmp_path / "emotion.csv"
    df_old = pd.DataFrame({
        "timestamp": ["2026-08-26 22:42:00"],
        "score": [3],
    })
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame({
        "timestamp": ["2026-08-26 22:42:00"],
        "score": [5],
    })

    df_merged = merge_csv_by_columns(
        df_new, csv_path,
        key_columns=["timestamp"],
        parse_dates=["timestamp"],
        preserve_existing_on_nan=True,
    )

    assert df_merged.set_index("timestamp").loc["2026-08-26 22:42:00", "score"] == 5


def test_merge_by_columns_preserve_existing_large_integer_ids_not_rounded(tmp_path: Path):
    """preserve_existing_on_nan=True で、19桁の整数IDがfloat化で丸められないこと"""
    csv_path = tmp_path / "entries.csv"
    df_old = pd.DataFrame({
        "timestamp": ["2026-01-01", "2026-01-02"],
        "entry_id": [5667773472718017992, 8694685614035756360],
    })
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame({
        "timestamp": ["2026-01-03"],
        "entry_id": [1001717290611444584],
    })

    df_merged = merge_csv_by_columns(
        df_new, csv_path,
        key_columns=["timestamp"],
        preserve_existing_on_nan=True,
    )

    merged = df_merged.set_index("timestamp")
    assert str(merged.loc["2026-01-01", "entry_id"]) == "5667773472718017992"
    assert str(merged.loc["2026-01-02", "entry_id"]) == "8694685614035756360"
    assert str(merged.loc["2026-01-03", "entry_id"]) == "1001717290611444584"

    roundtrip_path = tmp_path / "entries_roundtrip.csv"
    df_merged.to_csv(roundtrip_path, index=False)
    df_roundtrip = pd.read_csv(roundtrip_path)
    roundtrip = df_roundtrip.set_index("timestamp")
    assert str(roundtrip.loc["2026-01-01", "entry_id"]) == "5667773472718017992"
    assert str(roundtrip.loc["2026-01-02", "entry_id"]) == "8694685614035756360"


def test_merge_by_columns_default_still_overwrites_whole_row(tmp_path: Path):
    """既定（引数なし）では現行の行ごと置換のままであること（後方互換の固定）"""
    csv_path = tmp_path / "emotion.csv"
    df_old = pd.DataFrame({
        "timestamp": ["2026-08-26 22:42:00"],
        "score": [3],
    })
    _write_csv(csv_path, df_old)

    df_new = pd.DataFrame({
        "timestamp": ["2026-08-26 22:42:00"],
        "score": [None],
    })

    df_merged = merge_csv_by_columns(
        df_new, csv_path,
        key_columns=["timestamp"],
        parse_dates=["timestamp"],
    )

    # 従来通り、新データのNaNが既存値を消す（行ごと置換）
    assert pd.isna(df_merged.set_index("timestamp").loc["2026-08-26 22:42:00", "score"])


# =============================================================================
# replace_csv_period（Issue #75 PR #84 レビュー: 「期間内すべて削除」だと
# Google 側にデータが無い日の既存行まで消えてしまうと判明したため、
# 「新データに存在する日付だけ削除」に変更した）
# =============================================================================

def test_replace_csv_period_replaces_dates_present_in_new_data(tmp_path: Path):
    """期間内で新データに存在する日付は、既存行が置き換わること"""
    csv_path = tmp_path / "temperature_core.csv"
    df_old = pd.DataFrame({
        "date_time": ["2026-08-17 09:03:19"],
        "temperature": [36.8],
    })
    df_old.to_csv(csv_path, index=False)

    df_new = pd.DataFrame({
        "date_time": ["2026-08-17 10:00:00"],
        "temperature": [37.0],
    })

    df_merged = replace_csv_period(
        df_new, csv_path, "date_time", "2026-08-01", "2026-08-31",
    )

    assert len(df_merged) == 1
    assert df_merged.iloc[0]["date_time"] == "2026-08-17 10:00:00"


def test_replace_csv_period_keeps_dates_absent_from_new_data(tmp_path: Path, capsys):
    """期間内でも新データに1件も無い日付は、既存行が残ること（本件の核心）"""
    csv_path = tmp_path / "temperature_core.csv"
    df_old = pd.DataFrame({
        "date_time": ["2026-01-03 00:00:00", "2026-08-17 09:03:19"],
        "temperature": [36.4, 36.8],
    })
    df_old.to_csv(csv_path, index=False)

    # 新データは08-17分のみ。01-03はGoogle側にデータが無い想定
    df_new = pd.DataFrame({
        "date_time": ["2026-08-17 10:00:00"],
        "temperature": [37.0],
    })

    df_merged = replace_csv_period(
        df_new, csv_path, "date_time", "2026-01-01", "2026-08-31", label="temperature_core",
    )

    dates = set(df_merged["date_time"])
    assert "2026-01-03 00:00:00" in dates, "Google にデータが無い日の既存行が消えている"
    assert "2026-08-17 10:00:00" in dates
    assert "2026-08-17 09:03:19" not in dates  # 新データがある日は置き換わる
    assert len(df_merged) == 2

    captured = capsys.readouterr()
    assert 'temperature_core' in captured.out
    assert '2026-01-03' in captured.out
    assert '既存行を残した' in captured.out


def test_replace_csv_period_keeps_dates_outside_period(tmp_path: Path):
    """期間外の既存行はそのまま残ること（既存の挙動）"""
    csv_path = tmp_path / "temperature_core.csv"
    df_old = pd.DataFrame({
        "date_time": ["2026-05-01 00:00:00"],
        "temperature": [36.6],
    })
    df_old.to_csv(csv_path, index=False)

    df_new = pd.DataFrame({
        "date_time": ["2026-08-17 10:00:00"],
        "temperature": [37.0],
    })

    df_merged = replace_csv_period(
        df_new, csv_path, "date_time", "2026-08-01", "2026-08-31",
    )

    dates = set(df_merged["date_time"])
    assert "2026-05-01 00:00:00" in dates
    assert "2026-08-17 10:00:00" in dates
    assert len(df_merged) == 2


def test_replace_csv_period_no_warning_when_all_dates_covered(tmp_path: Path, capsys):
    """新データがすべての既存日付をカバーしていれば警告が出ないこと"""
    csv_path = tmp_path / "temperature_core.csv"
    df_old = pd.DataFrame({
        "date_time": ["2026-08-17 09:03:19"],
        "temperature": [36.8],
    })
    df_old.to_csv(csv_path, index=False)

    df_new = pd.DataFrame({
        "date_time": ["2026-08-17 10:00:00"],
        "temperature": [37.0],
    })

    replace_csv_period(df_new, csv_path, "date_time", "2026-08-01", "2026-08-31")

    captured = capsys.readouterr()
    assert '既存行を残した' not in captured.out
