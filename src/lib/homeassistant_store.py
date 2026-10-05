"""Home Assistant statistics の保存（月別 CSV・縦持ち）

data/homeassistant/statistics_5min/YYYY-MM.csv  列: start,entity_id,mean,min,max
start は JST の tz-naive。月は JST の start で分割する。
マージで触るのは新データに含まれる月だけで、過去の月は書き換えない。
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from lib.utils.csv_utils import merge_csv_by_columns
from lib.utils.private_data import ensure_dir, require_private_write

JST = ZoneInfo('Asia/Tokyo')
COLUMNS = ['start', 'entity_id', 'mean', 'min', 'max']
TS_FORMAT = '%Y-%m-%d %H:%M:%S'


def epoch_ms_to_jst_naive(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=JST).strftime(TS_FORMAT)


def to_dataframe(result: dict[str, list[dict]]) -> pd.DataFrame:
    """API 応答を縦持ちへ。HA が返した行だけ作る（補間・0埋めはしない）"""
    rows = []
    for entity_id, points in result.items():
        for p in points:
            rows.append({
                'start': epoch_ms_to_jst_naive(p['start']),
                'entity_id': entity_id,
                'mean': p.get('mean'),
                'min': p.get('min'),
                'max': p.get('max'),
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def stats_dir(base_dir: Path) -> Path:
    return require_private_write(Path(base_dir) / 'data' / 'homeassistant' / 'statistics_5min')


def save(df_new: pd.DataFrame, base_dir: Path) -> list[Path]:
    """月ごとにマージして書く。書いたファイルを返す"""
    if df_new.empty:
        return []
    out_dir = stats_dir(base_dir)
    ensure_dir(out_dir)
    months = df_new['start'].str[:7]
    written = []
    for month, part in df_new.groupby(months):
        path = out_dir / f'{month}.csv'
        merged = merge_csv_by_columns(
            part[COLUMNS], path, key_columns=['start', 'entity_id'],
            sort_by=['start', 'entity_id'],
        )
        merged = merged.sort_values(['start', 'entity_id'], kind='stable')
        merged[COLUMNS].to_csv(path, index=False)
        written.append(path)
    return written


def latest_start(base_dir: Path) -> datetime | None:
    """保存済みの最新 start（JST tz-naive）。無ければ None"""
    out_dir = stats_dir(base_dir)
    if not out_dir.exists():
        return None
    for path in sorted(out_dir.glob('*.csv'), reverse=True):
        df = pd.read_csv(path, usecols=['start'])
        if not df.empty:
            return datetime.strptime(df['start'].max(), TS_FORMAT)
    return None
