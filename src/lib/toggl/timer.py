"""Toggl の計測（start / stop / current）ロジック

fetch/push が「過去の実績を CSV と突き合わせる」バッチなのに対し、こちらは
その場で計測を開始・停止する対話的な操作。CSV も台帳も触らない
（計測結果は次回の fetch で time_entries.csv に入る）。

プロジェクト名 → ID の解決はローカルキャッシュ（data/toggl/projects.json）で行う。
Toggl の /me 系クォータは 30リクエスト/時で fetch・push と食い合うため、
start のたびにプロジェクト一覧（/me + /workspaces/{id}/projects で2リクエスト）を
取り直すと、1時間に十数回 start しただけで枠が尽きて fetch が落ちる。
キャッシュに無い名前を引いたときだけ取り直す。
"""

import datetime as dt
import json
from pathlib import Path

from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
PROJECTS_CACHE_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'projects.json')

CREATED_WITH = 'dailybuild'

# open サブコマンドで開く画面。API ではなく Web アプリ側の URL なので
# クォータは消費しない
WEB_URLS = {
    'timer': 'https://track.toggl.com/timer',
    'reports': 'https://track.toggl.com/reports',
    'projects': 'https://track.toggl.com/projects',
}


class ProjectResolutionError(Exception):
    """プロジェクト名を一意に解決できなかった"""


def save_project_cache(workspace_id: int, projects: dict[int, str]) -> None:
    """プロジェクト一覧をキャッシュへ書く（キーは JSON の都合で文字列になる）"""
    PROJECTS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROJECTS_CACHE_FILE.write_text(json.dumps({
        'workspace_id': workspace_id,
        'fetched_at': dt.datetime.now().astimezone().isoformat(),
        'projects': {str(pid): name for pid, name in projects.items()},
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_project_cache() -> tuple[int, dict[int, str]] | None:
    """キャッシュから (workspace_id, {project_id: name})。無い/壊れていれば None"""
    if not PROJECTS_CACHE_FILE.exists():
        return None
    try:
        cache = json.loads(PROJECTS_CACHE_FILE.read_text(encoding='utf-8'))
        workspace_id = int(cache['workspace_id'])
        projects = {int(pid): name for pid, name in cache['projects'].items()}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None
    return workspace_id, projects


def resolve_project(query: str, projects: dict[int, str]) -> tuple[int, str]:
    """プロジェクト名（の一部）から (project_id, project_name) を解決する

    完全一致 → 大文字小文字を無視した一致 → 部分一致の順に狭める。
    部分一致が複数あるときは黙って1つ選ばず候補を挙げて落とす（打ち間違いを
    別プロジェクトへの記録にしないため）。
    """
    exact = [(pid, name) for pid, name in projects.items() if name == query]
    if len(exact) == 1:
        return exact[0]

    lowered = query.casefold()
    ci = [(pid, name) for pid, name in projects.items() if name.casefold() == lowered]
    if len(ci) == 1:
        return ci[0]

    partial = [(pid, name) for pid, name in projects.items() if lowered in name.casefold()]
    if len(partial) == 1:
        return partial[0]

    candidates = exact or ci or partial
    if not candidates:
        raise ProjectResolutionError(f"プロジェクト '{query}' が見つからない")
    names = ', '.join(sorted(name for _, name in candidates))
    raise ProjectResolutionError(f"プロジェクト '{query}' が一意に決まらない（候補: {names}）")


def build_start_payload(workspace_id: int, project_id: int | None,
                        description: str, tags: tuple[str, ...],
                        start: dt.datetime) -> dict:
    """計測開始用のペイロード

    duration に負値を入れると計測中のエントリになる（stop は渡さない）。
    """
    payload = {
        'created_with': CREATED_WITH,
        'workspace_id': workspace_id,
        'description': description,
        'start': start.isoformat(),
        'duration': -1,
        'tags': list(tags),
        'billable': False,
    }
    if project_id is not None:
        payload['project_id'] = project_id
    return payload


def format_elapsed(seconds: int) -> str:
    """経過秒を 1h23m45s 形式にする"""
    hours, remainder = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(remainder, 60)
    return f'{hours}h{minutes:02d}m{secs:02d}s'


def elapsed_seconds(entry: dict, now: dt.datetime) -> int:
    """計測中エントリの経過秒。start が読めなければ 0"""
    start = entry.get('start')
    if not start:
        return 0
    started_at = dt.datetime.fromisoformat(start.replace('Z', '+00:00'))
    return int((now - started_at).total_seconds())


def describe_project(project_id: int | None, projects: dict[int, str]) -> str:
    """project_id の表示名

    キャッシュは archive 済みを持たないため、未知のIDを「プロジェクト無し」と
    書くと嘘になる。解決できなければIDのまま出す。
    """
    if project_id is None:
        return '(no project)'
    return projects.get(project_id, f'(project #{project_id})')


def describe_entry(entry: dict, projects: dict[int, str], now: dt.datetime) -> str:
    """計測中エントリの1行表示"""
    project = describe_project(entry.get('project_id'), projects)
    description = entry.get('description') or '(no description)'
    tags = entry.get('tags') or []
    tag_str = f" [{','.join(tags)}]" if tags else ''
    return (f'[{project}] {description}{tag_str} '
            f'({format_elapsed(elapsed_seconds(entry, now))} 経過)')
