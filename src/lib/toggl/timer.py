"""Toggl 2.0（Focus）の計測（start / stop / current）ロジック

fetch/push が「過去の実績を CSV と突き合わせる」バッチなのに対し、こちらは
その場で計測を開始・停止する対話的な操作。CSV も台帳も触らない
（計測結果は次回の fetch-focus で focus_entries.csv に入る）。

プロジェクト名 → ID の解決はローカルキャッシュ（data/toggl/focus_projects.json）で行う。
キャッシュに無い名前を引いたときだけ取り直す。タグ名 → ID は focus_tags.json
（fetch-focus が貯める）を引く。Track の projects.json とは ID 体系が別なので混ぜない。
"""

import datetime as dt
import json
from pathlib import Path

from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
PROJECTS_CACHE_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'focus_projects.json')

# open サブコマンドで開く画面。API ではなく Web アプリ側の URL。2.0 の個別画面の
# URL は未確認なのでトップだけ
WEB_URL = 'https://focus.toggl.com/'


class ProjectResolutionError(Exception):
    """プロジェクト名を一意に解決できなかった"""


class TagResolutionError(Exception):
    """タグ名を focus_tags.json から引けなかった"""


def resolve_tags(names: tuple[str, ...], tag_map: dict[str, int]) -> list[int]:
    """タグ名 → ID。引けない名前があれば、既知のタグ名を挙げて落とす

    タグ無しで黙って進めると、auto タグ等で見分ける判定が壊れる。
    """
    unknown = [n for n in names if n not in tag_map]
    if unknown:
        known = ', '.join(sorted(tag_map)) or '(なし。fetch-focus でエントリを取ると貯まる)'
        raise TagResolutionError(f"タグ {', '.join(unknown)} を引けない（既知: {known}）")
    return [tag_map[n] for n in names]


def save_project_cache(workspace_id: int, projects: dict[int, str]) -> None:
    """プロジェクト一覧をキャッシュへ書く（キーは JSON の都合で文字列になる）"""
    ensure_dir(PROJECTS_CACHE_FILE.parent)
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


def build_start_payload(project_id: int | None, description: str,
                        tag_ids: list[int]) -> dict:
    """/tracking/start 用のペイロード。type: "activity" は必須、開始時刻はサーバが決める"""
    payload = {
        'type': 'activity',
        'description': description,
    }
    if project_id is not None:
        payload['project_id'] = project_id
    if tag_ids:
        payload['tag_ids'] = tag_ids
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
    names = [t['name'] if isinstance(t, dict) else str(t) for t in entry.get('tags') or []]
    tag_str = f" [{','.join(names)}]" if names else ''
    return (f'[{project}] {description}{tag_str} '
            f'({format_elapsed(elapsed_seconds(entry, now))} 経過)')
