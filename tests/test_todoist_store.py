"""
Todoist 完了ログ（Issue #229）のマージのテスト

Todoist 側の履歴はプランやアカウントの都合で見えなくなり得るので、
再取得で行を消さない・二重に入れない・ID を数値に化けさせないことを確認する。
"""

import datetime as dt

import pandas as pd
import pytest

from lib.todoist import client, store
from lib.utils import private_data
from lib.utils.env import MissingEnvError


def _item(task_id, completed_at, content='銀行で振込', project_id='6Jf8VQXxpwv56VQ7'):
    return {
        'id': task_id, 'content': content, 'project_id': project_id,
        'section_id': None, 'parent_id': None, 'labels': ['money', 'errand'],
        'priority': 1, 'added_at': '2026-10-17T23:00:00.000000Z',
        'completed_at': completed_at,
        'due': {'date': '2026-10-18', 'is_recurring': False},
        'deadline': None, 'postponed_count': 2, 'completed_count': 1,
    }


class FakeClient:
    """窓ごとに決まった items を返すフェイク"""

    def __init__(self, items):
        self.items = items

    def fetch_completed_tasks(self, *_args):
        return list(self.items)


def _ingest(fake, csv_path):
    items = fake.fetch_completed_tasks('token', dt.date(2026, 10, 1), dt.date(2026, 10, 18))
    df_new = store.build_dataframe(items, {'6Jf8VQXxpwv56VQ7': 'お金'})
    return store.save_merged(df_new, csv_path=csv_path)


def test_same_window_twice_does_not_add_rows(tmp_path):
    csv = tmp_path / 'completed.csv'
    fake = FakeClient([
        _item('6hp3rC3Vx6wCWcF7', '2026-10-18T03:12:45.123456Z'),
        _item('6hp3rC3Vx6wCWcF8', '2026-10-18T04:00:00Z'),
    ])

    _ingest(fake, csv)
    _ingest(fake, csv)

    df = store.load_completed(csv)
    assert len(df) == 2


def test_empty_refetch_keeps_existing_rows(tmp_path):
    csv = tmp_path / 'completed.csv'
    _ingest(FakeClient([_item('6hp3rC3Vx6wCWcF7', '2026-10-18T03:12:45Z')]), csv)

    _ingest(FakeClient([]), csv)

    df = store.load_completed(csv)
    assert df['task_id'].tolist() == ['6hp3rC3Vx6wCWcF7']


def test_task_id_stays_string_including_numeric_prefix(tmp_path):
    csv = tmp_path / 'completed.csv'
    # 先頭が数字・全桁数字・指数表記に見える ID も文字列のまま残ること
    ids = ['6hp3rC3Vx6wCWcF7', '0123456789', '1e5']
    _ingest(FakeClient([
        _item(task_id, f'2026-10-18T0{i}:00:00Z', project_id='0042')
        for i, task_id in enumerate(ids)
    ]), csv)
    # 2回目の読み戻し→マージでも化けないこと
    _ingest(FakeClient([]), csv)

    df = store.load_completed(csv)
    assert sorted(df['task_id']) == sorted(ids)
    assert set(df['project_id']) == {'0042'}
    raw = csv.read_text(encoding='utf-8')
    assert '0123456789' in raw and '1e5' in raw


def test_recompleted_task_is_kept_as_two_rows(tmp_path):
    csv = tmp_path / 'completed.csv'
    _ingest(FakeClient([_item('6hp3rC3Vx6wCWcF7', '2026-10-10T03:00:00Z')]), csv)
    _ingest(FakeClient([_item('6hp3rC3Vx6wCWcF7', '2026-10-18T03:00:00Z')]), csv)

    df = store.load_completed(csv)
    assert df['completed_at'].tolist() == [
        '2026-10-10T12:00:00+09:00', '2026-10-18T12:00:00+09:00']


def test_build_dataframe_columns():
    df = store.build_dataframe(
        [_item('6hp3rC3Vx6wCWcF7', '2026-10-18T03:12:45.123456Z')],
        {'6Jf8VQXxpwv56VQ7': 'お金'})
    row = df.iloc[0]
    assert row['completed_at'] == '2026-10-18T12:12:45+09:00'
    assert row['project_name'] == 'お金'
    assert row['labels'] == 'money|errand'
    assert row['due_date'] == '2026-10-18'
    assert row['deadline'] == ''
    assert row['postponed_count'] == '2'


def test_save_refuses_public_data_dir(tmp_path, monkeypatch):
    """data/ が symlink でない（private 未マウント）なら public 側に作らず落ちる"""
    repo = tmp_path / 'dailybuild'
    (repo / 'data').mkdir(parents=True)
    monkeypatch.setattr(private_data, 'REPO_ROOT', repo)
    csv = repo / 'data' / 'todoist' / 'completed.csv'

    with pytest.raises(FileNotFoundError):
        store.save_merged(store.build_dataframe([], {}), csv_path=csv)
    assert not (repo / 'data' / 'todoist').exists()


def test_require_private_path_rejects_unmounted_data(tmp_path):
    with pytest.raises(FileNotFoundError):
        private_data.require_private_path(tmp_path / 'data' / 'todoist' / 'completed.csv')


def test_missing_token_hints_url(tmp_path):
    with pytest.raises(MissingEnvError) as exc:
        client.load_api_token(env_file=tmp_path / '.env', environ={})
    assert 'https://app.todoist.com/' in str(exc.value)


def test_split_windows_covers_range_without_gaps():
    windows = client.split_windows(dt.date(2026, 1, 1), dt.date(2026, 3, 15), days=30)
    assert windows[0][0] == dt.date(2026, 1, 1)
    assert windows[-1][1] == dt.date(2026, 3, 15)
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert next_start == prev_end + dt.timedelta(days=1)
