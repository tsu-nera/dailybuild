"""
MoneyForward ME の CSV の読み書き

data/mf/（dailybuild-private への symlink）の収入・支出詳細_YYYY.csv・資産推移.csv・balances.csv を対象に、
fetch 側のマージ保存と show 側の読み込みをまとめる。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from lib.mf.balances import STATUS_GONE, STATUS_MISSING, STATUS_OK
from lib.utils import csv_utils
from lib.utils.private_data import ensure_dir, require_private_path

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


# 口座別残高（/bs/portfolio・/bs/liability）。キーごとに前回から変わった行だけを積む（docs/moneyforward.md）
BALANCES_CSV = DATA_DIR / 'balances.csv'
BALANCE_KEY = ['kind', 'institution', 'name', 'seq']
# 前回と比べる欄。どれかが変われば1行書く
BALANCE_STATE = ['status', 'value', 'quantity', 'unrealized_gain', 'category', 'expires']
BALANCE_COLUMNS = ['date', *BALANCE_KEY, *BALANCE_STATE]


def _cell(value) -> str:
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _balance_row(day: str, b) -> dict:
    return {'date': day, 'kind': b.kind, 'institution': b.institution, 'name': b.name, 'seq': str(b.seq),
            'status': STATUS_MISSING if b.value is None else STATUS_OK, 'value': _cell(b.value),
            'quantity': _cell(b.quantity), 'unrealized_gain': _cell(b.unrealized_gain),
            'category': b.category, 'expires': b.expires}


def merge_balances(existing: list[dict], new: list, fetched_kinds: set[str], day: dt.date) -> list[dict]:
    """既存の行に今日の取得分を足した全行を返す。

    - fetched_kinds は取得・parse が成功して行が1件以上あったページの種類。それ以外の種類には触らない
      （今日の行を消さない・消えたキーも判定しない）
    - 同じ日の取り直しは、その種類の今日の行を消してから今日より前の最新状態と比べ直す
    - 前回と同じ状態なら書かない。missing が続く間も書かない
    - 前回まであったキーが今回のページに無ければ gone を1行。gone の後に現れたら通常の行を書く
    """
    today = day.isoformat()
    kept = [r for r in existing if not (r['date'] == today and r['kind'] in fetched_kinds)]
    last: dict[tuple, dict] = {}
    for r in sorted(kept, key=lambda r: r['date']):
        if r['date'] < today:
            last[tuple(r[k] for k in BALANCE_KEY)] = r

    written, seen = [], set()
    for b in new:
        if b.kind not in fetched_kinds:
            continue
        row = _balance_row(today, b)
        key = tuple(row[k] for k in BALANCE_KEY)
        seen.add(key)
        prev = last.get(key)
        if prev is not None and (all(prev[c] == row[c] for c in BALANCE_STATE)
                                 or prev['status'] == row['status'] == STATUS_MISSING):
            continue
        written.append(row)
    for key, prev in last.items():
        if key[0] in fetched_kinds and key not in seen and prev['status'] != STATUS_GONE:
            written.append({'date': today, **dict(zip(BALANCE_KEY, key)), 'status': STATUS_GONE,
                            **{c: '' for c in BALANCE_STATE if c != 'status'}})

    rows = kept + written
    rows.sort(key=lambda r: (r['date'], r['kind'], r['institution'], r['name'], int(r['seq'])))
    return rows


def load_balances(path: Path | None = None) -> list[dict]:
    """balances.csv の全行（文字列のまま）。まだ無ければ空"""
    path = path or BALANCES_CSV
    if not path.exists():
        return []
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=OUTPUT_ENCODING)
    return df.reindex(columns=BALANCE_COLUMNS, fill_value='').to_dict('records')


def save_balances(new: list, fetched_kinds: set[str], day: dt.date, out) -> None:
    """口座別残高を変わった行だけ足して保存する（merge_balances）"""
    rows = merge_balances(load_balances(), new, fetched_kinds, day)
    ensure_dir(BALANCES_CSV.parent)
    pd.DataFrame(rows, columns=BALANCE_COLUMNS).to_csv(BALANCES_CSV, index=False, encoding=OUTPUT_ENCODING)
    changed = sum(r['date'] == day.isoformat() for r in rows)
    print(f"保存完了: {BALANCES_CSV} (今日の変化 {changed}行 / 総行数 {len(rows)}行)", file=out)
