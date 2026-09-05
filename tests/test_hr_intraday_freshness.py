# coding: utf-8
"""
hr_intraday_freshness() のテスト（Issue #128）

heart_rate_intraday.csv がレポート期間の終端より古いのに、レポートが
例外を出さず空欄で正常終了する（＝古さに気づけない）ことの再発防止。
実データは使わず、tmp_path に小さなCSVを作って直接叩く。
"""

import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.utils.intraday_freshness import hr_intraday_freshness


def _write_csv(path, lines):
    content = "datetime,heart_rate\n" + "\n".join(lines) + ("\n" if lines else "")
    path.write_text(content, encoding='utf-8')


def test_up_to_date_returns_none(tmp_path):
    csv_path = tmp_path / 'heart_rate_intraday.csv'
    _write_csv(csv_path, [
        '2026-09-04 23:58:00,60',
        '2026-09-05 00:00:00,58',
    ])

    result = hr_intraday_freshness(csv_path, '2026-09-05')

    assert result is None


def test_stale_by_3_days(tmp_path):
    csv_path = tmp_path / 'heart_rate_intraday.csv'
    _write_csv(csv_path, [
        '2026-09-02 00:00:00,60',
        '2026-09-02 00:01:00,58',
    ])

    result = hr_intraday_freshness(csv_path, '2026-09-05')

    assert result is not None
    assert result['days_behind'] == 3
    assert result['last_date'] == '2026-09-02'
    assert result['fetch_days'] == 3


def test_missing_file_returns_no_last_date(tmp_path):
    csv_path = tmp_path / 'does_not_exist.csv'

    result = hr_intraday_freshness(csv_path, '2026-09-05')

    assert result is not None
    assert result['last_date'] is None
    assert result['days_behind'] is None
    assert result['fetch_days'] > 0


def test_empty_file_header_only_returns_no_last_date(tmp_path):
    csv_path = tmp_path / 'heart_rate_intraday.csv'
    _write_csv(csv_path, [])

    result = hr_intraday_freshness(csv_path, '2026-09-05')

    assert result is not None
    assert result['last_date'] is None
    assert result['days_behind'] is None


@pytest.mark.parametrize('period_end', [
    '2026-09-05',
    date(2026, 9, 5),
    datetime(2026, 9, 5, 12, 0, 0),
    pd.Timestamp('2026-09-05'),
])
def test_period_end_type_variants_give_same_result(tmp_path, period_end):
    csv_path = tmp_path / 'heart_rate_intraday.csv'
    _write_csv(csv_path, [
        '2026-09-02 00:00:00,60',
    ])

    result = hr_intraday_freshness(csv_path, period_end)

    assert result is not None
    assert result['days_behind'] == 3
    assert result['last_date'] == '2026-09-02'
