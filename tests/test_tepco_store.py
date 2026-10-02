"""くらしTEPCO 30分値: 欠測を 0kWh に化けさせない・取り直しで二重に入れない"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pandas as pd

from lib.tepco import store


def _slot(no, hhmm, power=None):
    slot = {'no': str(no), 'usedTime': hhmm, 'billingStatus': '01' if power else '00'}
    if power is not None:
        slot['usedInfo'] = {'power': power, 'unit': 'kWh'}
    return slot


def test_slots_without_used_info_are_not_rows():
    payload = {'billInfos': [_slot(1, '0000', '0.0'), _slot(2, '0030'), _slot(3, '0100', '0.3')]}

    rows = store.parse_hourly('20261001', payload)

    assert rows == [
        {'date': '2026-10-01', 'time': '00:00', 'kwh': 0.0},
        {'date': '2026-10-01', 'time': '01:00', 'kwh': 0.3},
    ]


def test_refetch_replaces_slot_and_keeps_untouched_days(tmp_path):
    csv = tmp_path / 'usage_30min.csv'
    store.save([{'date': '2026-09-30', 'time': '23:30', 'kwh': 0.2},
                {'date': '2026-10-01', 'time': '00:00', 'kwh': 0.1}], csv)

    store.save([{'date': '2026-10-01', 'time': '00:00', 'kwh': 0.4}], csv)

    df = pd.read_csv(csv)
    assert len(df) == 2
    assert df.set_index(['date', 'time']).loc[('2026-10-01', '00:00'), 'kwh'] == 0.4
    assert df.set_index(['date', 'time']).loc[('2026-09-30', '23:30'), 'kwh'] == 0.2
