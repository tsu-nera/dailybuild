"""
Toggl store（Issue #130）の fetch窓での削除・マージのテスト

fetch した窓の中で API レスポンスに無くなった行を削除することで、
push.select_pending の削除検出（「CSV に無い＝手動削除された」）を
正しく機能させる。安全弁（窓外は触らない・0件では削除しない）を中心に確認する。
"""

import datetime as dt

import pandas as pd

from lib.toggl import store


def _existing_csv(csv_path, rows):
    df = pd.DataFrame(rows, columns=store.CSV_COLUMNS)
    df.to_csv(csv_path, index=False)


def test_drop_stale_rows_removes_row_missing_from_window(tmp_path, monkeypatch):
    csv = tmp_path / 'time_entries.csv'
    _existing_csv(csv, [
        {'id': 1, 'start': '2026-08-20 08:00:00', 'stop': '2026-08-20 09:00:00',
         'duration_sec': 3600, 'description': 'a', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
        {'id': 2, 'start': '2026-08-21 08:00:00', 'stop': '2026-08-21 09:00:00',
         'duration_sec': 3600, 'description': 'b', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
    ])
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    # 窓 [2026-08-20, 2026-08-21] を fetch した結果、id=2 は無くなっていた
    df_new = pd.DataFrame([
        {'id': 1, 'start': '2026-08-20 08:00:00', 'stop': '2026-08-20 09:00:00',
         'duration_sec': 3600, 'description': 'a', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
    ], columns=store.CSV_COLUMNS)

    removed = store.drop_stale_rows_in_window(
        df_new, window=(dt.date(2026, 8, 20), dt.date(2026, 8, 21)))

    assert removed == 1
    remaining = pd.read_csv(csv)
    assert remaining['id'].tolist() == [1]


def test_drop_stale_rows_leaves_rows_outside_window(tmp_path, monkeypatch):
    """最重要の回帰テスト: 窓外の行は API に無くても消えない"""
    csv = tmp_path / 'time_entries.csv'
    _existing_csv(csv, [
        # 窓の外（過去分）。API レスポンス(df_new)には含まれないが消えてはいけない
        {'id': 1, 'start': '2026-01-01 08:00:00', 'stop': '2026-01-01 09:00:00',
         'duration_sec': 3600, 'description': 'old', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
        {'id': 2, 'start': '2026-08-21 08:00:00', 'stop': '2026-08-21 09:00:00',
         'duration_sec': 3600, 'description': 'b', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
    ])
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df_new = pd.DataFrame([
        {'id': 2, 'start': '2026-08-21 08:00:00', 'stop': '2026-08-21 09:00:00',
         'duration_sec': 3600, 'description': 'b', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
    ], columns=store.CSV_COLUMNS)

    removed = store.drop_stale_rows_in_window(
        df_new, window=(dt.date(2026, 8, 20), dt.date(2026, 8, 21)))

    assert removed == 0
    remaining = pd.read_csv(csv)
    assert sorted(remaining['id'].tolist()) == [1, 2]


def test_drop_stale_rows_does_nothing_when_response_empty(tmp_path, monkeypatch):
    """API レスポンスが0件のときは削除しない（通信不調との区別が付かない）"""
    csv = tmp_path / 'time_entries.csv'
    _existing_csv(csv, [
        {'id': 1, 'start': '2026-08-20 08:00:00', 'stop': '2026-08-20 09:00:00',
         'duration_sec': 3600, 'description': 'a', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
    ])
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df_new = pd.DataFrame(columns=store.CSV_COLUMNS)

    removed = store.drop_stale_rows_in_window(
        df_new, window=(dt.date(2026, 8, 20), dt.date(2026, 8, 21)))

    assert removed == 0
    remaining = pd.read_csv(csv)
    assert remaining['id'].tolist() == [1]


def test_save_merged_with_window_removes_and_merges(tmp_path, monkeypatch, capsys):
    csv = tmp_path / 'time_entries.csv'
    _existing_csv(csv, [
        {'id': 1, 'start': '2026-08-20 08:00:00', 'stop': '2026-08-20 09:00:00',
         'duration_sec': 3600, 'description': 'a', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
        {'id': 2, 'start': '2026-08-21 08:00:00', 'stop': '2026-08-21 09:00:00',
         'duration_sec': 3600, 'description': 'b', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
    ])
    monkeypatch.setattr(store, 'CSV_FILE', csv)

    df_new = pd.DataFrame([
        {'id': 1, 'start': '2026-08-20 08:00:00', 'stop': '2026-08-20 09:00:00',
         'duration_sec': 3600, 'description': 'a', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
        {'id': 3, 'start': '2026-08-21 10:00:00', 'stop': '2026-08-21 11:00:00',
         'duration_sec': 3600, 'description': 'c', 'project_id': None,
         'project_name': '', 'workspace_id': 1, 'tags': ''},
    ], columns=store.CSV_COLUMNS)

    df_merged = store.save_merged(df_new, window=(dt.date(2026, 8, 20), dt.date(2026, 8, 21)))

    assert sorted(df_merged['id'].tolist()) == [1, 3]
    captured = capsys.readouterr()
    assert '1件' in captured.err
