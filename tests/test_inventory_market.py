"""中古相場の定期取得: 相場にならない件数を中央値として書かないこと・履歴を二重に積まないこと"""

from dataclasses import dataclass
from datetime import date, datetime

from lib.inventory.market import append_history, due, parse_query, read_history, sold_stats


@dataclass
class Item:
    name: str
    price: int
    updated: datetime


NOW = datetime(2026, 11, 12)


def test_sold_stats_counts_only_matching_recent_items():
    q = parse_query('WH-1000XM3 --min 5000')
    items = [Item('SONY WH-1000XM3 ブラック', p, datetime(2026, 11, 1)) for p in (6000, 7000, 8000, 9000)]
    items += [
        Item('WH-1000XM3 ケース', 9900, datetime(2026, 11, 1)),      # 除外語
        Item('WH-1000XM4', 20000, datetime(2026, 11, 1)),           # 語が合わない
        Item('WH-1000XM3', 30000, datetime(2026, 7, 1)),            # 90日より前
    ]
    stats = sold_stats(items, q, NOW)
    assert (stats.median, stats.count) == (7500, 4)


def test_sold_stats_too_few_is_not_a_price():
    q = parse_query('Charge 6')
    stats = sold_stats([Item('Fitbit Charge 6', 10000, NOW)] * 3, q, NOW)
    assert (stats.median, stats.count) == (None, 3)


def test_due_counts_unpriced_checks_as_checked():
    rows = [
        {'date': '2026-11-01', 'key': 'a', 'median': '7000'},
        {'date': '2026-10-01', 'key': 'b', 'median': ''},
        {'date': '2026-11-10', 'key': 'b', 'median': ''},   # 相場にならなかった日も調べた日
    ]
    assert due(['a', 'b', 'c'], rows, date(2026, 11, 12), 30) == ['c']
    assert due(['a', 'b', 'c'], rows, date(2026, 12, 1), 30) == ['a', 'c']
    assert due(['a', 'b', 'c'], rows, date(2026, 11, 12), 0) == ['a', 'b', 'c']


def test_append_history_replaces_same_day_and_keeps_others(tmp_path):
    path = tmp_path / 'market.csv'
    append_history(path, [{'date': '2026-10-12', 'key': 'a', 'name': 'x', 'median': '7000', 'count': 5, 'query': 'q'}])
    append_history(path, [{'date': '2026-11-12', 'key': 'a', 'name': 'x', 'median': '7100', 'count': 5, 'query': 'q'}])
    append_history(path, [{'date': '2026-11-12', 'key': 'a', 'name': 'x', 'median': '7150', 'count': 6, 'query': 'q'}])
    assert [(r['date'], r['median']) for r in read_history(path)] == [('2026-10-12', '7000'), ('2026-11-12', '7150')]


def test_full_width_in_listing_name_matches():
    q = parse_query('Domane AL2 Gen4')
    items = [Item('TREK ドマーネ DOMANE AL2 GEN４ 2024', 95000, NOW)] * 4
    assert sold_stats(items, q, NOW).count == 4
