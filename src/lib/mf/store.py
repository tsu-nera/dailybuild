"""
MoneyForward ME 収入・支出詳細 CSV の読み書き

data/mf/収入・支出詳細_YYYY.csv（dailybuild-private への symlink）を対象に、
fetch 側のマージ保存と show 側の読み込みをまとめる。
"""

from pathlib import Path

import pandas as pd

from lib.utils import csv_utils
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]
# dailybuild-private への symlink。未設定なら空データで成功しないよう落とす
DATA_DIR = require_private_path(BASE_DIR / 'data' / 'mf')

CSV_GLOB = '収入・支出詳細_*.csv'
ASSETS_CSV = DATA_DIR / '資産推移.csv'

# MF の CSV 列名
COL_TARGET = '計算対象'
COL_DATE = '日付'
COL_NAME = '内容'
COL_AMOUNT = '金額（円）'
COL_ACCOUNT = '保有金融機関'
COL_CATEGORY = '大項目'
COL_SUBCATEGORY = '中項目'
COL_ID = 'ID'

# 資産推移 CSV の列名。合計と日付以外（預金・現金 / 投資信託 / …）は MF 側の
# 保有状況で増減するため、コードには持たず読んだものをそのまま使う
COL_ASSET_DATE = '日付'
COL_ASSET_TOTAL = '合計（円）'

# 既存ファイルに合わせる（Excel で開けるよう BOM 付き）
OUTPUT_ENCODING = 'utf-8-sig'


def csv_path(year: int) -> Path:
    return DATA_DIR / f'収入・支出詳細_{year}.csv'


def save_by_year(df_new: pd.DataFrame, out) -> None:
    """明細を日付の年ごとに振り分けて既存 CSV とマージ保存する"""
    years = pd.to_datetime(df_new[COL_DATE], format='%Y/%m/%d').dt.year

    for year, df_year in df_new.groupby(years):
        path = csv_path(year)
        df_merged = csv_utils.merge_csv_by_columns(
            df_year, path, key_columns=[COL_ID], sort_by=[COL_DATE],
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        df_merged.to_csv(path, index=False, encoding=OUTPUT_ENCODING)
        print(f"保存完了: {path} (総行数 {len(df_merged)}行)", file=out)


def load_entries() -> pd.DataFrame:
    """show 側の CSV 読み込み。年別ファイルをまとめて読み、日付列を付与する。

    計算対象=0 の明細（振替・重複計上）は家計の集計から外す。口座間の振替は
    MF 側で必ず計算対象=0 が付くため、この絞り込みだけで一緒に落ちる。
    """
    paths = sorted(DATA_DIR.glob(CSV_GLOB))
    if not paths:
        return pd.DataFrame()

    df = pd.concat(
        [pd.read_csv(p, encoding=OUTPUT_ENCODING) for p in paths],
        ignore_index=True,
    )
    df = df[df[COL_TARGET] == 1].copy()
    df['date'] = pd.to_datetime(df[COL_DATE]).dt.normalize()
    return df.sort_values('date')


def save_assets(df_new: pd.DataFrame, out) -> None:
    """資産推移を日付キーでマージ保存する。

    MF が返す粒度は当月だけ日次で、月をまたぐと月末1点に潰れる。マージは
    日付キーの置換なので、**過去に取った日次の行はここで消えない**
    （新データに無い日付には触らない）。
    """
    df_merged = csv_utils.merge_csv_by_columns(
        df_new, ASSETS_CSV, key_columns=[COL_ASSET_DATE], sort_by=[COL_ASSET_DATE],
    )
    ASSETS_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_merged.to_csv(ASSETS_CSV, index=False, encoding=OUTPUT_ENCODING)
    print(f"保存完了: {ASSETS_CSV} (総行数 {len(df_merged)}行)", file=out)


def load_assets() -> pd.DataFrame:
    """show 側の資産推移の読み込み。日付列を付与し、残高列を数値にする"""
    if not ASSETS_CSV.exists():
        return pd.DataFrame()

    df = pd.read_csv(ASSETS_CSV, encoding=OUTPUT_ENCODING)
    df['date'] = pd.to_datetime(df[COL_ASSET_DATE]).dt.normalize()
    for col in asset_columns(df):
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df.sort_values('date')


def asset_columns(df: pd.DataFrame) -> list[str]:
    """残高の列（合計を含む）。日付と派生列を除いたもの"""
    return [c for c in df.columns if c not in (COL_ASSET_DATE, 'date', 'bucket')]
