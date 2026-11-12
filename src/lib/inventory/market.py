"""中古相場（メルカリ SOLD の中央値）を引き、履歴を data/inventory/market.csv に積む

検索条件は Homebox の custom field `相場検索` に、gtd の scripts/shopping/price.py と同じ引数の書式で持つ
（'WH-1000XM3 --min 5000'、'Domane AL 2 Gen4 --min 50000 --exclude "フレーム ホイール"'）。
品名の単語をすべて含み、除外語を含まない SOLD だけを数える。mercapi は非公式 API なので、取れない日がある前提で使う。

market.csv は1回の取得で1行（date, key, name, median, count, query）。件数が MIN_SOLD 未満の日は median を空にして
「調べたが相場にならなかった」を残す（行を作らないと毎日引き直す）。同じ日・同じ key は差し替える。
手で入れた相場（homebox.py market <key> <price>）も count 空・query に出どころで積む（お金の画面の履歴を1本にする）。
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import shlex
import statistics
import unicodedata
from dataclasses import dataclass
from datetime import date as Date, datetime, timedelta
from pathlib import Path

SOLD_DAYS = 90
DEFAULT_EXCLUDE = 'ケース カバー フィルム マウント スタンド ブラケット 金具 アーム ホルダー'
MIN_SOLD = 4  # これ未満は中央値を相場として使わない
HISTORY_COLUMNS = ['date', 'key', 'name', 'median', 'count', 'query']


@dataclass
class MarketQuery:
    query: str
    pmin: int
    exclude: list[str]

    @property
    def words(self) -> list[str]:
        return _norm(self.query).split()


@dataclass
class SoldStats:
    median: float | None  # 件数が MIN_SOLD 未満なら None
    count: int

    @property
    def source(self) -> str:
        return f'メルカリ SOLD（直近{SOLD_DAYS}日 {self.count}件）中央値'


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # 既定は SystemExit
        raise ValueError(message)


def parse_query(text: str) -> MarketQuery:
    ap = _Parser(add_help=False, exit_on_error=False)
    ap.add_argument('query', nargs='+')
    ap.add_argument('--min', type=int, default=0)
    ap.add_argument('--exclude', default=DEFAULT_EXCLUDE)
    try:
        a = ap.parse_args(shlex.split(text))
    except argparse.ArgumentError as e:
        raise ValueError(str(e)) from e
    return MarketQuery(' '.join(a.query), a.min, _norm(a.exclude).split())


def _norm(text: str) -> str:
    """出品名は全角英数が混じる（'GEN４'）"""
    return unicodedata.normalize('NFKC', text).lower()


def matches(name: str, q: MarketQuery) -> bool:
    n = _norm(name)
    return all(w in n for w in q.words) and not any(x in n for x in q.exclude)


def sold_stats(items, q: MarketQuery, now: datetime) -> SoldStats:
    """items は mercapi の検索結果（name・price・updated を持つ）"""
    since = now - timedelta(days=SOLD_DAYS)
    prices = [i.price for i in items
              if matches(i.name, q) and i.price >= q.pmin and i.updated >= since]
    median = statistics.median(prices) if len(prices) >= MIN_SOLD else None
    return SoldStats(median, len(prices))


async def _search_sold(q: MarketQuery):
    from mercapi import Mercapi
    from mercapi.requests import SearchRequestData as R
    r = await Mercapi().search(q.query, status=[R.Status.STATUS_SOLD_OUT],
                               price_min=q.pmin or None, sort_by=R.SortBy.SORT_CREATED_TIME)
    return r.items


def fetch_sold(text: str) -> SoldStats:
    q = parse_query(text)
    return sold_stats(asyncio.run(_search_sold(q)), q, datetime.now())


# ---- 履歴（market.csv） ----

def read_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def last_checked(rows: list[dict]) -> dict[str, Date]:
    """key → 最後に調べた日（相場にならなかった日も含む）"""
    out: dict[str, Date] = {}
    for r in rows:
        d = Date.fromisoformat(r['date'])
        if r['key'] not in out or d > out[r['key']]:
            out[r['key']] = d
    return out


def due(targets, rows: list[dict], today: Date, every_days: int) -> list[str]:
    checked = last_checked(rows)
    return [k for k in targets if k not in checked or (today - checked[k]).days >= every_days]


def append_history(path: Path, new: list[dict]) -> None:
    """同じ (date, key) は差し替え、他の行は残す。date, key 順で全体を書き直す"""
    replaced = {(r['date'], r['key']) for r in new}
    rows = [r for r in read_history(path) if (r['date'], r['key']) not in replaced] + new
    rows.sort(key=lambda r: (r['date'], r['key']))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HISTORY_COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows({c: r.get(c, '') for c in HISTORY_COLUMNS} for r in rows)
    tmp = path.with_suffix('.csv.tmp')
    tmp.write_text(buf.getvalue())
    tmp.replace(path)
