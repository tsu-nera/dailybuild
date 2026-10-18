"""
Todoist 完了ログ CSV の読み書き

data/todoist/completed.csv（dailybuild-private への symlink）に、1行=1完了で
積み上げる。マージのキーは (task_id, completed_at)。同じタスクを再オープンして
再完了した場合は別行として残す。

取得した窓の中も置換ではなく upsert にする。Todoist 側で履歴が見えなくなる
（プラン・アカウントの都合）ことがあり、API に無いことは「消えた」の根拠にならない。

ID は英数字の文字列（例 6hp3rC3Vx6wCWcF7）。読み書きはすべて dtype=str で行い、
先頭が数字の ID を数値に化けさせない。
"""

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'todoist' / 'completed.csv')
PROJECTS_CACHE_FILE = require_private_path(BASE_DIR / 'data' / 'todoist' / 'projects.json')

TIMEZONE = 'Asia/Tokyo'

CSV_COLUMNS = [
    'completed_at', 'task_id', 'content', 'project_id', 'project_name',
    'section_id', 'parent_id', 'labels', 'priority', 'added_at',
    'due_date', 'deadline', 'postponed_count',
]

KEY_COLUMNS = ['task_id', 'completed_at']

READ_CSV_KWARGS = {'dtype': str, 'keep_default_na': False}


def to_local_iso(iso_str: str | None) -> str:
    """API の UTC ISO8601 を Asia/Tokyo の ISO8601（秒精度）にする

    マージキーに入るので、API 側の小数秒の有無で別行にならないよう秒に揃える。
    """
    if not iso_str:
        return ''
    ts = pd.Timestamp(iso_str)
    if ts.tzinfo is None:
        ts = ts.tz_localize('UTC')
    return ts.tz_convert(TIMEZONE).floor('s').isoformat()


def _date_of(value: dict | None) -> str:
    """due / deadline オブジェクトの date。無ければ空文字"""
    if not value:
        return ''
    return str(value.get('date') or '')


def _str(value) -> str:
    return '' if value is None else str(value)


def build_dataframe(items: list[dict], projects: dict[str, str]) -> pd.DataFrame:
    """API の items を CSV 用 DataFrame（全列 str）に変換"""
    rows = []
    for item in items:
        project_id = _str(item.get('project_id'))
        rows.append({
            'completed_at': to_local_iso(item.get('completed_at')),
            'task_id': _str(item.get('id')),
            'content': _str(item.get('content')),
            'project_id': project_id,
            'project_name': projects.get(project_id, ''),
            'section_id': _str(item.get('section_id')),
            'parent_id': _str(item.get('parent_id')),
            'labels': '|'.join(item.get('labels') or []),
            'priority': _str(item.get('priority')),
            'added_at': to_local_iso(item.get('added_at')),
            'due_date': _date_of(item.get('due')),
            'deadline': _date_of(item.get('deadline')),
            'postponed_count': _str(item.get('postponed_count')),
        })
    return pd.DataFrame(rows, columns=CSV_COLUMNS, dtype=str)


def load_completed(csv_path: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(csv_path or CSV_FILE, **READ_CSV_KWARGS)


def last_completed_date(csv_path: Path | None = None) -> dt.date | None:
    """CSV の最終完了日（Asia/Tokyo の暦日）。CSV が無い・空なら None"""
    csv_path = csv_path or CSV_FILE
    if not csv_path.exists():
        return None
    df = load_completed(csv_path)
    if df.empty:
        return None
    return dt.date.fromisoformat(df['completed_at'].max()[:10])


def save_merged(df_new: pd.DataFrame, csv_path: Path | None = None) -> pd.DataFrame:
    """既存 CSV へ (task_id, completed_at) で upsert して保存する

    df_new が空でも既存行には触れない（窓の置換をしないため）。
    """
    csv_path = csv_path or CSV_FILE
    ensure_dir(csv_path.parent)
    df_merged = csv_utils.merge_csv_by_columns(
        df_new, csv_path, key_columns=KEY_COLUMNS, sort_by=['completed_at', 'task_id'],
        read_csv_kwargs=READ_CSV_KWARGS,
    )
    df_merged = df_merged.reindex(columns=CSV_COLUMNS)
    df_merged.to_csv(csv_path, index=False)
    return df_merged


def load_project_cache(cache_path: Path | None = None) -> dict[str, str]:
    """キャッシュの {project_id: name}。無い/壊れていれば空 dict"""
    cache_path = cache_path or PROJECTS_CACHE_FILE
    if not cache_path.exists():
        return {}
    try:
        cache = json.loads(cache_path.read_text(encoding='utf-8'))
        return {str(pid): name for pid, name in cache['projects'].items()}
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return {}


def update_project_cache(fetched: dict[str, str],
                         cache_path: Path | None = None) -> dict[str, str]:
    """取得した一覧でキャッシュを上書きマージして保存し、マージ後を返す

    削除・アーカイブされたプロジェクトは一覧に出なくなるが、過去の完了の
    名前解決に要るのでキャッシュからは消さない。
    """
    cache_path = cache_path or PROJECTS_CACHE_FILE
    projects = {**load_project_cache(cache_path), **fetched}
    ensure_dir(cache_path.parent)
    cache_path.write_text(json.dumps({
        'fetched_at': dt.datetime.now().astimezone().isoformat(),
        'projects': projects,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return projects
