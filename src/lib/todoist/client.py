"""Todoist API v1 クライアント

API token による Bearer 認証。完了済みタスクは
GET /tasks/completed/by_completion_date から取り、next_cursor でページングする。

1回の since〜until の幅には上限がある（ドキュメント上は約3か月）。
長い期間は WINDOW_DAYS ずつの窓に分けて取る。
"""

import datetime as dt
import logging

import os
from pathlib import Path

import requests

from lib.utils.env import ENV_FILE, require_env

logger = logging.getLogger(__name__)

API_BASE = 'https://api.todoist.com/api/v1'

TOKEN_HINT = 'https://app.todoist.com/app/settings/integrations/developer の API トークン'

REQUEST_TIMEOUT = 60

# since〜until の上限（約3か月）より十分短く取る
WINDOW_DAYS = 30

PAGE_LIMIT = 200


def load_api_token(env_file: Path = ENV_FILE, environ=os.environ) -> str:
    """TODOIST_API_TOKEN。無ければ発行先 URL を添えて MissingEnvError"""
    return require_env('TODOIST_API_TOKEN', hint=TOKEN_HINT,
                       env_file=env_file, environ=environ)


def _get(api_token: str, path: str, params: dict) -> dict:
    response = requests.get(
        f'{API_BASE}{path}',
        params=params,
        headers={'Authorization': f'Bearer {api_token}'},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def _paginate(api_token: str, path: str, params: dict, key: str) -> list[dict]:
    items = []
    cursor = None
    while True:
        page_params = dict(params, limit=PAGE_LIMIT)
        if cursor:
            page_params['cursor'] = cursor
        body = _get(api_token, path, page_params)
        items.extend(body.get(key) or [])
        cursor = body.get('next_cursor')
        if not cursor:
            return items


def split_windows(start: dt.date, end: dt.date,
                  days: int = WINDOW_DAYS) -> list[tuple[dt.date, dt.date]]:
    """[start, end]（両端含む暦日）を days 日ずつの窓に分ける"""
    windows = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + dt.timedelta(days=days - 1), end)
        windows.append((cursor, window_end))
        cursor = window_end + dt.timedelta(days=1)
    return windows


def _utc_iso(day: dt.date, tz: dt.tzinfo) -> str:
    """tz の暦日 day の 00:00 を UTC の ISO8601（Z 付き）にする"""
    local = dt.datetime.combine(day, dt.time.min, tzinfo=tz)
    return local.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def fetch_completed_tasks(api_token: str, start: dt.date, end: dt.date,
                          tz: dt.tzinfo) -> list[dict]:
    """tz の暦日 [start, end] に完了したタスクを取得する"""
    items = []
    for window_start, window_end in split_windows(start, end):
        params = {
            'since': _utc_iso(window_start, tz),
            'until': _utc_iso(window_end + dt.timedelta(days=1), tz),
        }
        window_items = _paginate(api_token, '/tasks/completed/by_completion_date',
                                 params, 'items')
        logger.info('Todoist 完了タスク %s〜%s: %d件', window_start, window_end,
                    len(window_items))
        items.extend(window_items)
    return items


def fetch_projects(api_token: str) -> dict[str, str]:
    """project_id → プロジェクト名（archived は含まない）"""
    projects = _paginate(api_token, '/projects', {}, 'results')
    return {str(p['id']): p.get('name') or '' for p in projects}
