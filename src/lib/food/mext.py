#!/usr/bin/env python
# coding: utf-8
"""
日本食品標準成分表（八訂）増補2023年 の Excel を食品マスタへ変換する

出典: 文部科学省「日本食品標準成分表（八訂）増補2023年」
https://www.mext.go.jp/a_menu/syokuhinseibun/mext_00001.html
二次利用可。引用時は出典の明記が必要。

Excel の見出しは4行にまたがる結合セルで機械可読ではないが、12行目の
「成分識別子」の行だけは1成分1列で並んでいる。列の対応はここだけを見る。
"""

from pathlib import Path

import pandas as pd
import requests

SEIBUN_URL = 'https://www.mext.go.jp/content/20260327-mxt_kagsei-mext-000029402_02.xlsx'
SHEET_NAME = '表全体'

# 成分識別子が並ぶ行（1始まり）。データはその次の行から
IDENT_ROW = 12
DATA_START_ROW = 13

# 食品番号・食品名などの位置（1始まり）
COL_GROUP = 1
COL_FOOD_ID = 2
COL_INDEX = 3
COL_NAME = 4

# 成分識別子 → マスタの列名。識別子は難読なのでここで一度だけ開く。
# ナイアシンは NIA ではなく NE（ナイアシン当量）、ビタミンAは VITA_RAE
# （レチノール活性当量）、ビタミンEは TOCPHA（α-トコフェロール）を採る。
COMPONENTS = {
    'ENERC_KCAL': 'energy_kcal',
    'WATER': 'water_g',
    'PROT-': 'protein_g',
    'FAT-': 'fat_g',
    'CHOCDF-': 'carb_g',
    'FIB-': 'fiber_g',
    'CHOLE': 'cholesterol_mg',
    'ASH': 'ash_g',
    'ALC': 'alcohol_g',
    'NACL_EQ': 'salt_g',
    # 無機質
    'NA': 'sodium_mg',
    'K': 'potassium_mg',
    'CA': 'calcium_mg',
    'MG': 'magnesium_mg',
    'P': 'phosphorus_mg',
    'FE': 'iron_mg',
    'ZN': 'zinc_mg',
    'CU': 'copper_mg',
    'MN': 'manganese_mg',
    'ID': 'iodine_ug',
    'SE': 'selenium_ug',
    'CR': 'chromium_ug',
    'MO': 'molybdenum_ug',
    # ビタミン
    'VITA_RAE': 'vitamin_a_ug',
    'VITD': 'vitamin_d_ug',
    'TOCPHA': 'vitamin_e_mg',
    'VITK': 'vitamin_k_ug',
    'THIA': 'vitamin_b1_mg',
    'RIBF': 'vitamin_b2_mg',
    'NE': 'niacin_mg',
    'VITB6A': 'vitamin_b6_mg',
    'VITB12': 'vitamin_b12_ug',
    'FOL': 'folate_ug',
    'PANTAC': 'pantothenic_mg',
    'BIOT': 'biotin_ug',
    'VITC': 'vitamin_c_mg',
}

BASE_COLUMNS = ['food_id', 'name', 'group', 'index_no', 'source']
MASTER_COLUMNS = BASE_COLUMNS + list(COMPONENTS.values())


def download(dest: Path, url: str = SEIBUN_URL, refresh: bool = False) -> Path:
    """成分表の Excel を取得する。既にあれば再取得しない"""
    if dest.exists() and not refresh:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    res = requests.get(url, timeout=60)
    res.raise_for_status()
    dest.write_bytes(res.content)
    return dest


def parse_value(raw):
    """
    成分値のセルを float へ。成分表の記号を潰す。

    - `-`      未測定 → None（0 ではない。混ぜると欠測を 0 と偽ることになる）
    - `Tr`     微量   → 0.0
    - `(数値)` 推計値 → 数値（推計であることは落ちるが、値としては採用する）
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    s = str(raw).strip().replace('（', '(').replace('）', ')')
    if s in ('', '-'):
        return None
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1].strip()
    if s in ('Tr', 'tr'):
        return 0.0
    try:
        return float(s.replace(',', ''))
    except ValueError:
        return None


def _code(raw, width):
    """食品番号・食品群は先頭0が意味を持つので文字列で保持する"""
    if raw is None:
        return ''
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    return str(raw).strip().zfill(width)


def load(xlsx_path: Path) -> pd.DataFrame:
    """成分表 Excel を食品マスタの DataFrame にする"""
    import openpyxl

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]

    rows = ws.iter_rows(values_only=True)
    ident_row = None
    records = []

    for i, row in enumerate(rows, start=1):
        if i == IDENT_ROW:
            ident_row = row
            continue
        if i < DATA_START_ROW or ident_row is None:
            continue

        food_id = _code(row[COL_FOOD_ID - 1], 5)
        name = row[COL_NAME - 1]
        if not food_id or not name:
            continue

        rec = {
            'food_id': food_id,
            'name': str(name).replace('　', ' ').strip(),
            'group': _code(row[COL_GROUP - 1], 2),
            'index_no': _code(row[COL_INDEX - 1], 4),
            'source': 'mext',
        }
        for col_i, ident in enumerate(ident_row):
            key = str(ident).strip() if ident is not None else ''
            if key in COMPONENTS:
                rec[COMPONENTS[key]] = parse_value(row[col_i])
        records.append(rec)

    if ident_row is None:
        raise ValueError(
            f"{IDENT_ROW}行目に成分識別子が見つかりません。成分表の書式が変わった可能性があります"
        )

    df = pd.DataFrame(records)
    missing = [c for c in MASTER_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"成分表に見つからない成分識別子があります: {missing}")

    return df[MASTER_COLUMNS]
