"""tepco.py fetch の取得開始日: 無指定は CSV の最終日から取り直す（部分日を欠測のまま残さない）"""

import datetime as dt
import sys
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

import tepco

TODAY = dt.date(2026, 10, 2)


def _days(csv, **kw):
    args = Namespace(since=kw.get('since'), days=kw.get('days'))
    return tepco.resolve_days(args, today=TODAY, csv_path=csv)


def test_default_starts_at_last_csv_date(tmp_path):
    csv = tmp_path / 'u.csv'
    csv.write_text('date,time,kwh\n2026-09-29,00:00,0.1\n2026-09-30,00:30,0.2\n')

    assert _days(csv) == [dt.date(2026, 9, 30), dt.date(2026, 10, 1), TODAY]


def test_missing_or_empty_csv_falls_back_to_7_days(tmp_path):
    empty = tmp_path / 'e.csv'
    empty.write_text('date,time,kwh\n')

    for csv in (tmp_path / 'none.csv', empty):
        days = _days(csv)
        assert len(days) == 7 and days[0] == dt.date(2026, 9, 26) and days[-1] == TODAY


def test_explicit_args_win_over_csv(tmp_path):
    csv = tmp_path / 'u.csv'
    csv.write_text('date,time,kwh\n2026-10-01,00:00,0.1\n')

    assert _days(csv, days=2) == [dt.date(2026, 10, 1), TODAY]
    assert _days(csv, since='2026-09-30')[0] == dt.date(2026, 9, 30)
