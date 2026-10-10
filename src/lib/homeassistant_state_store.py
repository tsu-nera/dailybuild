"""Home Assistant state 履歴の保存（月別 CSV・縦持ち）

data/homeassistant/states/YYYY-MM.csv  列: time,entity_id,state,attributes
time は HA の last_updated を JST の tz-naive にしたもの（マイクロ秒まで残す。秒で丸めると
同一秒の更新が key 衝突する）。last_changed でなく last_updated なのは attributes だけの
更新（座標の変化）を落とさないため。月は JST の time で分割し、新データに含まれる月だけ触る。
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from lib.homeassistant_store import JST
from lib.utils.csv_utils import merge_csv_by_columns
from lib.utils.private_data import ensure_dir, require_private_write

COLUMNS = ['time', 'entity_id', 'state', 'attributes']
TS_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
# state・attributes は自由文字列。既定の読み込みだと `None` `NA` や空欄が NaN に化けて書き戻される
READ_CSV_KWARGS = {'dtype': str, 'keep_default_na': False}


def _us(epoch_s: float) -> int:
    return round(epoch_s * 1_000_000)


def epoch_s_to_jst_naive(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=JST).strftime(TS_FORMAT)


def _attributes(attrs: dict, keys: list[str]) -> str:
    """yaml で指定したキーだけを、指定順の JSON にする。指定が無ければ空"""
    if not keys:
        return ''
    return json.dumps({k: attrs[k] for k in keys if k in attrs}, ensure_ascii=False)


def to_dataframe(result: dict[str, list[dict]], attribute_keys: dict[str, list[str]],
                 start: datetime) -> pd.DataFrame:
    """API 応答（圧縮形式）を縦持ちへ。HA が返した行だけ作る（補間・0埋めはしない）

    各 entity の先頭行で lu が start と一致するものは捨てる。窓の開始時点の state で、
    lu が実際の更新時刻ではなく start に丸められているため（保存すると日次実行のたびに
    存在しない更新が1行ずつ増える）。この行は存在確認にだけ使う（呼び出し側）。
    unavailable / unknown は端末が止まっていた唯一の記録なので捨てない。
    """
    start_us = _us(start.timestamp())
    rows = []
    for entity_id, states in result.items():
        keys = attribute_keys.get(entity_id) or []
        for i, st in enumerate(states):
            if i == 0 and _us(st['lu']) == start_us:
                continue
            rows.append({
                'time': epoch_s_to_jst_naive(st['lu']),
                'entity_id': entity_id,
                'state': st['s'],
                'attributes': _attributes(st.get('a') or {}, keys),
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def states_dir(base_dir: Path) -> Path:
    return require_private_write(Path(base_dir) / 'data' / 'homeassistant' / 'states')


def save(df_new: pd.DataFrame, base_dir: Path) -> list[Path]:
    """月ごとにマージして書く。書いたファイルを返す"""
    if df_new.empty:
        return []
    out_dir = states_dir(base_dir)
    ensure_dir(out_dir)
    months = df_new['time'].str[:7]
    written = []
    for month, part in df_new.groupby(months):
        path = out_dir / f'{month}.csv'
        merged = merge_csv_by_columns(
            part[COLUMNS], path, key_columns=['time', 'entity_id'],
            sort_by=['time', 'entity_id'], read_csv_kwargs=READ_CSV_KWARGS,
        )
        merged[COLUMNS].to_csv(path, index=False)
        written.append(path)
    return written


def latest_time(base_dir: Path) -> datetime | None:
    """保存済みの最新 time（JST tz-naive）。無ければ None"""
    out_dir = states_dir(base_dir)
    if not out_dir.exists():
        return None
    for path in sorted(out_dir.glob('*.csv'), reverse=True):
        df = pd.read_csv(path, usecols=['time'], dtype=str)
        if not df.empty:
            return datetime.strptime(df['time'].max(), TS_FORMAT)
    return None
