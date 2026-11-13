"""
XOSS サイコンの FIT（正本）と要約 CSV の読み書き

data/xoss/fit/*.fit（dailybuild-private への symlink）が正本で、data/xoss/rides.csv は
FIT から作り直せる要約。主キーはファイル名。

rides.csv は upsert のみで、入力に無い行は消さない。本体は容量（8 MB）が尽きると古い FIT を
失いうるので、「本体から消えた」ことを CSV から消す根拠にしない。
"""

from pathlib import Path

import pandas as pd

from lib.utils.private_data import ensure_dir, require_private_path
from lib.xoss.fit_summary import COLUMNS

BASE_DIR = Path(__file__).resolve().parents[3]
FIT_DIR = require_private_path(BASE_DIR / 'data' / 'xoss' / 'fit')
RIDES_CSV = require_private_path(BASE_DIR / 'data' / 'xoss' / 'rides.csv')

READ_CSV_KWARGS = {'dtype': str, 'keep_default_na': False}


def existing_fit_names(fit_dir: Path | None = None) -> set[str]:
    fit_dir = fit_dir or FIT_DIR
    return {p.name for p in fit_dir.glob('*.fit')} if fit_dir.exists() else set()


def save_fit(src: Path, fit_dir: Path | None = None) -> bool:
    """FIT を保存先へコピーする。同名が既にあれば上書きせず False（同じファイルを指す場合も False）"""
    fit_dir = fit_dir or FIT_DIR
    ensure_dir(fit_dir)
    dest = fit_dir / Path(src).name
    if dest.exists():
        return False
    dest.write_bytes(Path(src).read_bytes())
    return True


def upsert_rides(rows: list[dict], csv_path: Path | None = None) -> pd.DataFrame:
    """file をキーに rides.csv へ upsert する。入力に無い既存行は残し、start 昇順で保存する"""
    csv_path = csv_path or RIDES_CSV
    ensure_dir(csv_path.parent)
    new = pd.DataFrame(rows, columns=COLUMNS).astype(str).replace({'nan': ''})
    if csv_path.exists():
        old = pd.read_csv(csv_path, **READ_CSV_KWARGS)
        old = old[~old['file'].isin(new['file'])]
        merged = pd.concat([old, new], ignore_index=True)
    else:
        merged = new
    merged = merged.reindex(columns=COLUMNS).sort_values(['start', 'file'], kind='stable')
    merged.to_csv(csv_path, index=False)
    return merged
