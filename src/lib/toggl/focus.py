"""Toggl 2.0（Focus API）のクライアント（取得・作成・計測）

2026-10-27 から手動の時間記録は 2.0 に書いている。Track v9（lib.toggl.client）の
/me/time_entries には 2.0 に書いたエントリが返らないので、別のクライアントで扱う。
Track は同日で凍結し、push・start・stop の書き込み先はこちら。

Track との違い（docs/toggl.md の「Toggl 2.0」節）:
- 認証は Bearer token（toggl_sk_...）。Track の API Token とは別物
- include_taskless=true を付けないと task 無しのエントリが返らない
  （手動エントリはほぼ task 無しなので、付け忘れると黙って大半を取り逃す）
- stop フィールドが無い。start + duration で計算する
- 書き込み（実測 2026-11-02）: エントリ作成は type: "activity" が必須（無いと 400）。
  タグは tag_ids でしか付かない。tags / tag_names / tags:[{name}] は 201 が返るが
  タグが空になる（黙って落ちる）。名前 → ID の対応は取得したエントリの tags から
  focus_tags.json に貯める（タグ一覧 API は見つからなかった）
- id / project_id は Track と別の体系。time_entries.csv に混ぜると
  id の keep='last' マージで重複・取り違えが起きるので focus_entries.csv に分ける
"""

import dataclasses
import datetime as dt
import json
import logging
from pathlib import Path

import pandas as pd
import requests

from lib.toggl import store
from lib.utils.private_data import ensure_dir, require_private_path

logger = logging.getLogger(__name__)

API_BASE = 'https://focus.toggl.com/api'

REQUEST_TIMEOUT = 60

QUOTA_EXCEEDED_STATUS = 402

PAGE_SIZE = 100  # per_page の上限

CSV_FILE = store.FOCUS_CSV_FILE
TAGS_FILE = require_private_path(store.BASE_DIR / 'data' / 'toggl' / 'focus_tags.json')
PROJECTS_CSV_FILE = require_private_path(store.BASE_DIR / 'data' / 'toggl' / 'focus_projects.csv')

PROJECT_COLUMNS = ['id', 'name', 'client_id', 'client_name', 'created_at', 'archived_at']

UTC_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


CSV_COLUMNS = store.CSV_COLUMNS + ['type']

# id / project_id は Track と別体系で、整数かどうかを確認していない。
# 整数のときだけ Int64 に揃え（.0 を残さない）、そうでなければ文字列のまま持つ
MAYBE_INT_COLUMNS = ['id', 'project_id']
INT_COLUMNS = ['duration_sec', 'workspace_id']


@dataclasses.dataclass(frozen=True)
class Workspace:
    """API の認証と投入先。fetch 以外の関数はこれを受ける"""
    api_token: str
    organization_id: str
    workspace_id: str

    @property
    def base_path(self) -> str:
        return f'/organizations/{self.organization_id}/workspaces/{self.workspace_id}'


def _request(api_token: str, method: str, path: str, params: dict | None = None,
             json_body: dict | None = None) -> requests.Response:
    """API を叩き、クォータ残量のヘッダがあればログへ出す

    402 は Track と同じくレート制限（docs 上 Free は 30 req/h）なので専用のエラーにする。
    書き込みでもクォータのヘッダは返らない（実測）。
    """
    response = requests.request(
        method,
        f'{API_BASE}{path}',
        params=params,
        json=json_body,
        headers={'Authorization': f'Bearer {api_token}'},
        timeout=REQUEST_TIMEOUT,
    )

    remaining = response.headers.get('X-Toggl-Quota-Remaining')
    if remaining is not None:
        logger.info('Toggl 2.0 クォータ残: %s (%s)', remaining, path)

    if response.status_code == QUOTA_EXCEEDED_STATUS:
        resets_in = response.headers.get('X-Toggl-Quota-Resets-In', '不明')
        raise RuntimeError(
            f'Toggl 2.0 API のクォータ超過（402）。{resets_in} 秒後に回復。Premium 制限ではない'
        )

    response.raise_for_status()
    return response


def _get(api_token: str, path: str, params: dict) -> requests.Response:
    return _request(api_token, 'GET', path, params=params)


def _post(api_token: str, path: str, body: dict) -> requests.Response:
    return _request(api_token, 'POST', path, json_body=body)


def to_utc_str(value: dt.datetime) -> str:
    """API に送る時刻。UTC の RFC 3339、秒未満は切り捨てる（秒未満を含むと 400 になりうる）"""
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).strftime(UTC_FORMAT)


def date_range_params(start: dt.date, end: dt.date, tz: dt.tzinfo) -> dict:
    """JST の暦日 [start, end] を UTC の RFC 3339 の date_from / date_to にする"""
    date_from = dt.datetime.combine(start, dt.time.min, tzinfo=tz)
    date_to = dt.datetime.combine(end, dt.time(23, 59, 59), tzinfo=tz)
    fmt = '%Y-%m-%dT%H:%M:%SZ'
    return {
        'date_from': date_from.astimezone(dt.timezone.utc).strftime(fmt),
        'date_to': date_to.astimezone(dt.timezone.utc).strftime(fmt),
    }


def fetch_time_entries(api_token: str, organization_id: str, workspace_id: str,
                       start: dt.date, end: dt.date, tz: dt.tzinfo = store.JST) -> list[dict]:
    """期間のタイムエントリを全ページ取得して結合する（start, end は両端を含む暦日）"""
    path = f'/organizations/{organization_id}/workspaces/{workspace_id}/time-entries'
    entries: list[dict] = []
    page = 1
    while True:
        params = {
            **date_range_params(start, end, tz),
            'include_taskless': 'true',
            'page': page,
            'per_page': PAGE_SIZE,
        }
        batch = _get(api_token, path, params).json().get('data') or []
        entries.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return entries


def _fetch_project_pages(ws: Workspace, extra: dict | None = None) -> list[dict]:
    """GET /projects を全ページ取る。per_page の上限は100（200は400）、既定は20件"""
    projects: list[dict] = []
    page = 1
    while True:
        body = _get(ws.api_token, f'{ws.base_path}/projects',
                    {'page': page, 'per_page': PAGE_SIZE, **(extra or {})}).json()
        batch = body.get('data', []) if isinstance(body, dict) else body
        projects.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
    return projects


def fetch_projects(ws: Workspace) -> dict[int, str]:
    """アーカイブされていないプロジェクトの ID → 名前（start の名前解決用）

    GET /projects はアーカイブ済みを含まない。全件が要るときは fetch_project_records。
    """
    return {p['id']: p['name'] for p in _fetch_project_pages(ws)}


def fetch_project_records(ws: Workspace) -> list[dict]:
    """アーカイブ済みを含む全プロジェクト（2回引く）

    GET /projects はアーカイブ済みを含まず、archived=true はアーカイブ済みだけを返す。
    アーカイブの判定は archived_at（null でなければアーカイブ済み）。active は画面の
    状態と対応しない（API で作ったプロジェクトは作成直後から active: false）ので使わない。
    """
    by_id = {p['id']: p for p in _fetch_project_pages(ws)}
    by_id.update({p['id']: p for p in _fetch_project_pages(ws, {'archived': 'true'})})
    return list(by_id.values())


def build_projects_dataframe(projects: list[dict]) -> pd.DataFrame:
    """プロジェクト一覧を focus_projects.csv 用にする（id 昇順）

    クライアントは /clients が 404 で一覧できないので、各プロジェクトの client から読む。
    """
    rows = []
    for p in projects:
        client = p.get('client') or {}
        rows.append({
            'id': p['id'],
            'name': p.get('name') or '',
            'client_id': client.get('id', p.get('client_id')),
            'client_name': client.get('name') or '',
            'created_at': p.get('created_at') or '',
            'archived_at': p.get('archived_at') or '',
        })
    df = pd.DataFrame(rows, columns=PROJECT_COLUMNS)
    df['client_id'] = df['client_id'].astype('Int64')
    return df.sort_values('id').reset_index(drop=True)


def save_projects(df: pd.DataFrame, csv_path: Path | None = None) -> Path:
    """focus_projects.csv を全上書きする（API の一覧そのものの写し）"""
    path = csv_path or PROJECTS_CSV_FILE
    ensure_dir(path.parent)
    df.to_csv(path, index=False)
    return path


def load_projects(csv_path: Path | None = None) -> pd.DataFrame:
    """focus_projects.csv。無ければ空"""
    path = csv_path or PROJECTS_CSV_FILE
    if not path.exists():
        return pd.DataFrame(columns=PROJECT_COLUMNS)
    df = pd.read_csv(path, dtype={'name': str, 'client_name': str,
                                  'created_at': str, 'archived_at': str})
    df['client_id'] = df['client_id'].astype('Int64')
    return df.fillna({'name': '', 'client_name': '', 'created_at': '', 'archived_at': ''})


def client_id_by_name(projects: pd.DataFrame, client_name: str) -> int | None:
    """クライアント名 → ID。/clients が無いので既存プロジェクトの client から引く"""
    hit = projects.loc[(projects['client_name'] == client_name) & projects['client_id'].notna(),
                       'client_id']
    return int(hit.iloc[0]) if not hit.empty else None


def create_project(ws: Workspace, name: str, client_id: int) -> dict:
    """POST /projects {name} → PATCH /projects/{id} {client_id}

    POST に client_id を付けると 402 feature_not_available になる（実測）ので2段に分ける。
    PATCH は 204 で本文が無い。
    """
    project = _post(ws.api_token, f'{ws.base_path}/projects', {'name': name}).json()
    _request(ws.api_token, 'PATCH', f"{ws.base_path}/projects/{project['id']}",
             json_body={'client_id': client_id})
    return project


def create_time_entry(ws: Workspace, payload: dict) -> dict:
    """POST /time-entries（201 とエントリ）。payload は type: "activity" を含むこと"""
    return _post(ws.api_token, f'{ws.base_path}/time-entries', payload).json()


def start_tracking(ws: Workspace, payload: dict) -> dict:
    """POST /tracking/start（200 とエントリ）。既に計測中なら Toggl 側が扱う"""
    return _post(ws.api_token, f'{ws.base_path}/tracking/start', payload).json()


def fetch_current(ws: Workspace) -> dict | None:
    """GET /tracking/current。計測中が無ければ 204（None）"""
    response = _get(ws.api_token, f'{ws.base_path}/tracking/current', {})
    if response.status_code == 204:
        return None
    return response.json() or None


def stop_tracking(ws: Workspace, end: dt.datetime) -> dict:
    """POST /tracking/stop {"end": UTC RFC3339}（200 とエントリ）"""
    return _post(ws.api_token, f'{ws.base_path}/tracking/stop',
                 {'end': to_utc_str(end)}).json()


def collect_tags(entries: list[dict]) -> dict[str, int]:
    """取得したエントリの tags（{id, name}）から名前 → ID の対応を集める"""
    return {t['name']: t['id'] for e in entries for t in (e.get('tags') or [])
            if isinstance(t, dict) and t.get('name') and t.get('id') is not None}


def load_tags() -> dict[str, int]:
    """focus_tags.json の名前 → ID。無い/壊れていれば空"""
    if not TAGS_FILE.exists():
        return {}
    try:
        data = json.loads(TAGS_FILE.read_text(encoding='utf-8'))
        return {str(name): int(tag_id) for name, tag_id in data.items()}
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return {}


def save_tags(found: dict[str, int]) -> dict[str, int]:
    """既存の対応に found を足して保存する（縮めない。取得窓に出なかったタグを失わないため）"""
    merged = {**load_tags(), **found}
    if merged != load_tags():
        ensure_dir(TAGS_FILE.parent)
        TAGS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                             encoding='utf-8')
    return merged


def build_dataframe(entries: list[dict], workspace_id: int | str | None = None) -> pd.DataFrame:
    """取得したエントリを CSV 用 DataFrame に変換

    計測中のエントリは除外する。2.0 で計測中がどう表現されるかは未確認なので、
    duration が None または負値のものを計測中とみなす。
    """
    rows = []
    for entry in entries:
        duration = entry.get('duration')
        if duration is None or duration < 0:
            continue

        start = pd.Timestamp(entry['start'])
        stop = start + pd.Timedelta(seconds=duration)
        project = entry.get('project') or {}
        tags = entry.get('tags') or []

        rows.append({
            'id': entry.get('id'),
            'start': store.to_jst_naive_str(start.isoformat()),
            'stop': store.to_jst_naive_str(stop.isoformat()),
            'duration_sec': duration,
            'description': entry.get('description') or '',
            'project_id': entry.get('project_id'),
            'project_name': project.get('name') or '',
            'workspace_id': entry.get('workspace_id', workspace_id),
            'tags': ','.join(t['name'] for t in tags),
            'type': entry.get('type') or '',
        })

    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    # None が混ざると float64 に化けて 1234.0 になるので、DataFrame に通す前の値で判定する
    for col in MAYBE_INT_COLUMNS:
        raw = [row[col] for row in rows]
        if raw and all(v is None or (isinstance(v, int) and not isinstance(v, bool)) for v in raw):
            df[col] = pd.array(raw, dtype='Int64')
    return df


def save_merged(df_new: pd.DataFrame, window: tuple[dt.date, dt.date] | None = None,
                csv_path: Path | None = None) -> pd.DataFrame:
    """focus_entries.csv へマージする（ロジックは store と共有）

    window を渡すと窓内置換つき（fetch 用）。省略すると追記のみ（push が作成分を足す用）。
    """
    int_columns = INT_COLUMNS + [c for c in MAYBE_INT_COLUMNS if df_new[c].dtype == 'Int64']
    return store.save_merged(df_new, window=window, csv_path=csv_path or CSV_FILE,
                             int_columns=int_columns)
