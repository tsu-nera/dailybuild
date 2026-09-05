"""googlehealth_daily.fetch_activity の caloriesOut 妥当性チェック（Issue #125）

--days の窓が狭いと部分日が二度と取り直されず、低い caloriesOut のまま
CSV に固定される（欠測を捏造しないための警告の一種）。ネットワーク不要、
test_googlehealth_date_range.py と同じくフェイクで _rollup_by_date を
差し替える。
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from lib.clients import googlehealth_client  # noqa: F401  (resolve circular import first)
from lib.clients import googlehealth_daily as ghd

START = dt.date(2026, 9, 1)
END = dt.date(2026, 9, 5)


def make_rollup_by_date(kcal_by_date):
    """_rollup_by_date を差し替えるフェイク。total-calories だけ値を持たせ、
    他の型（steps/distance/active-minutes）は空にする
    （fetch_activity は各列が無くても None で埋めて行を作る）"""
    def fake(creds, data_type, payload_key, start_date, end_date):
        if data_type != 'total-calories':
            return {}
        return {date: {'kcalSum': kcal} for date, kcal in kcal_by_date.items()}
    return fake


def test_fetch_activity_warns_on_implausibly_low_calories_for_past_date(monkeypatch, capsys):
    past_date = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    monkeypatch.setattr(ghd, '_rollup_by_date', make_rollup_by_date({past_date: 500.0}))

    rows = ghd.fetch_activity(None, START, END)

    assert len(rows) == 1
    assert rows[0]['caloriesOut'] == 500.0  # 行は落とさない（warn-only）
    captured = capsys.readouterr()
    assert '⚠️' in captured.out
    assert past_date in captured.out
    assert '500.0' in captured.out


def test_fetch_activity_does_not_warn_for_today_even_if_low(monkeypatch, capsys):
    today = dt.date.today().isoformat()
    monkeypatch.setattr(ghd, '_rollup_by_date', make_rollup_by_date({today: 500.0}))

    rows = ghd.fetch_activity(None, START, END)

    assert len(rows) == 1
    assert rows[0]['caloriesOut'] == 500.0
    captured = capsys.readouterr()
    assert '低すぎる' not in captured.out


def test_fetch_activity_does_not_warn_when_calories_are_plausible(monkeypatch, capsys):
    past_date = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    monkeypatch.setattr(ghd, '_rollup_by_date', make_rollup_by_date({past_date: 1800.0}))

    ghd.fetch_activity(None, START, END)

    captured = capsys.readouterr()
    assert '低すぎる' not in captured.out
