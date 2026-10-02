"""
くらしTEPCO 30分値 CSV の読み書き

data/tepco/usage_30min.csv（dailybuild-private への symlink）に
`date, time, kwh` の縦持ちで蓄積する。
"""

from pathlib import Path

import pandas as pd

from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = require_private_path(BASE_DIR / 'data' / 'tepco')
USAGE_CSV = DATA_DIR / 'usage_30min.csv'

COLUMNS = ['date', 'time', 'kwh']


def parse_hourly(day: str, payload: dict) -> list[dict]:
    """hourly の応答を行に変換する。

    usedInfo の無いコマ（billingStatus=00、未計量・契約外）は**行を作らない**。
    0kWh で埋めると欠測が実測ゼロに化ける。
    """
    date = f'{day[:4]}-{day[4:6]}-{day[6:]}'
    rows = []
    for slot in payload.get('billInfos') or []:
        used = slot.get('usedInfo')
        if not used or used.get('power') in (None, ''):
            continue
        hhmm = slot['usedTime']
        rows.append({'date': date, 'time': f'{hhmm[:2]}:{hhmm[2:]}',
                     'kwh': float(used['power'])})
    return rows


def save(rows: list[dict], csv_path: Path = USAGE_CSV) -> pd.DataFrame:
    """(date, time) キーでマージ保存する。新データに無いコマには触らない"""
    df_new = pd.DataFrame(rows, columns=COLUMNS)
    df_merged = csv_utils.merge_csv_by_columns(
        df_new, csv_path, key_columns=['date', 'time'], sort_by=['date', 'time'],
    )
    ensure_dir(csv_path.parent)
    df_merged[COLUMNS].to_csv(csv_path, index=False)
    return df_merged
