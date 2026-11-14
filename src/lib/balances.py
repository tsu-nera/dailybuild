"""お金の画面（Grafana の money/assets）の口座別残高: data/mf/balances.csv（変わった行だけ）を日次に戻す

- balances.csv はキー（kind, institution, name, seq）ごとに前回から変わった日の行しか持たない。
  日次はキーごとに直前の行を引き継いで作る（docs/moneyforward.md）
- gone の日以降はそのキーを引き継がない（再び通常の行が出たら戻る）
- missing の日はそのキーを合計から外し、件数を missing_count に出す（合計はその分だけ過少）
- 種類の合計は、そのページ（資産 or 負債）の最初の行より前は空（0にしない）。それ以後に持っている
  キーが無ければ0
- 取得が止まった日も直前の値を引き継ぐ（変わらなかった日と見分けられない）。鮮度は表の updated と取得ログで見る
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from lib.mf.balances import LIABILITY_KIND, PORTFOLIO_KINDS, STATUS_GONE, STATUS_MISSING

KIND_COLUMNS = {'預金・現金': 'cash', '投資信託': 'funds', '暗号資産': 'crypto', 'ポイント': 'points'}
DAILY_COLUMNS = ['date', *KIND_COLUMNS.values(), 'assets_total', 'liabilities', 'net_worth', 'missing_count']
LATEST_COLUMNS = ['kind', 'institution', 'name', 'category', 'value', 'quantity', 'unrealized_gain',
                  'expires', 'updated', 'status', 'seq']
_KEY = ['kind', 'institution', 'name', 'seq']
_KIND_ORDER = [*PORTFOLIO_KINDS, LIABILITY_KIND]


def _num(text: str) -> int | float | None:
    if text == '':
        return None
    f = float(text)
    return int(f) if f.is_integer() else f


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    return df.sort_values('date', kind='stable').to_dict('records')


def _sum(values: list) -> int | float | None:
    return None if not values else sum(values)


def daily(rows: list[dict], end: dt.date) -> list[dict]:
    """変わった行だけの rows（日付順）を、最初の日〜end の1日1行にする"""
    if not rows:
        return []
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r['date'], []).append(r)
    first_page = {}
    for r in rows:
        page = LIABILITY_KIND if r['kind'] == LIABILITY_KIND else 'portfolio'
        first_page.setdefault(page, r['date'])

    state: dict[tuple, dict] = {}
    out = []
    day = dt.date.fromisoformat(rows[0]['date'])
    end = max(end, dt.date.fromisoformat(rows[-1]['date']))
    while day <= end:
        iso = day.isoformat()
        for r in by_day.get(iso, []):
            key = tuple(r[k] for k in _KEY)
            if r['status'] == STATUS_GONE:
                state.pop(key, None)
            else:
                state[key] = r
        held: dict[str, list] = {k: [] for k in _KIND_ORDER}
        missing: dict[str, int] = {k: 0 for k in _KIND_ORDER}
        for r in state.values():
            if r['status'] == STATUS_MISSING:
                missing[r['kind']] += 1
            else:
                held[r['kind']].append(_num(r['value']))

        def total(kind: str):
            page = LIABILITY_KIND if kind == LIABILITY_KIND else 'portfolio'
            if page not in first_page or iso < first_page[page]:
                return None
            return sum(held[kind])

        row = {'date': iso, **{col: total(kind) for kind, col in KIND_COLUMNS.items()}}
        assets = [row[c] for c in KIND_COLUMNS.values() if row[c] is not None]
        row['assets_total'] = _sum(assets)
        row['liabilities'] = total(LIABILITY_KIND)
        row['net_worth'] = (row['assets_total'] - row['liabilities']
                            if row['assets_total'] is not None and row['liabilities'] is not None else None)
        row['missing_count'] = sum(missing.values())
        out.append(row)
        day += dt.timedelta(days=1)
    return out


def latest(rows: list[dict]) -> list[dict]:
    """キーごとの最新の状態（gone は出さない）。updated は最後に値が変わった日"""
    last: dict[tuple, dict] = {}
    for r in rows:
        last[tuple(r[k] for k in _KEY)] = r
    out = []
    for r in last.values():
        if r['status'] == STATUS_GONE:
            continue
        out.append({'kind': r['kind'], 'institution': r['institution'], 'name': r['name'],
                    'category': r['category'], 'value': _num(r['value']), 'quantity': _num(r['quantity']),
                    'unrealized_gain': _num(r['unrealized_gain']), 'expires': r['expires'],
                    'updated': r['date'], 'status': r['status'], 'seq': r['seq']})
    out.sort(key=lambda r: (_KIND_ORDER.index(r['kind']) if r['kind'] in _KIND_ORDER else len(_KIND_ORDER),
                            -(r['value'] or 0), r['institution'], r['name'], int(r['seq'])))
    return out


def build(balances_csv: Path, today: dt.date) -> tuple[list[dict], list[dict]]:
    """(日次の合計, 最新の残高)。balances.csv がまだ無ければどちらも0行"""
    rows = _read(balances_csv)
    return daily(rows, today), latest(rows)
