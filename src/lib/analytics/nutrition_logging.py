#!/usr/bin/env python
# coding: utf-8
"""
栄養記録の完全性モード（Issue #25）

Google Health の nutrition-log は食品項目しか運ばず、Cronometer の
Completed フラグは live の経路に乗らない。日単位の完全性フラグは作れないため、
`config/nutrition_logging.yaml` で期間ごとに記録運用を宣言し、モードに応じて
列を欠測（NaN）にする。0埋めはしない（protein_only の calories を 0 にすると
それ自体が直そうとしている誤表示になる）。
"""

from pathlib import Path

import pandas as pd
import numpy as np
import yaml

# protein_only で欠測にする列（protein 以外の栄養列）
PROTEIN_ONLY_BLANK_COLUMNS = ['calories', 'carbs', 'fat', 'fiber', 'sodium', 'water']


def load_logging_periods(config_path):
    """
    `config/nutrition_logging.yaml` の periods を読む

    Parameters
    ----------
    config_path : str or Path or None
        yaml のパス。None、または存在しない場合は空リスト
        （呼び出し側で全期間 unknown 扱いになる）

    Returns
    -------
    list of dict
        periods のリスト（from, to, mode, note）。無ければ空リスト
    """
    if config_path is None:
        return []
    path = Path(config_path)
    if not path.exists():
        return []
    with open(path, encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    return data.get('periods', []) or []


def _mode_for_date(date, periods):
    """1日分の日付に対応する記録モードを引く。宣言の外側は unknown。"""
    d = pd.Timestamp(date).normalize()
    for period in periods:
        start = pd.Timestamp(period['from']).normalize()
        to = period.get('to')
        end = pd.Timestamp(to).normalize() if to else None
        if d >= start and (end is None or d <= end):
            return period['mode']
    return 'unknown'


def load_nutrition_with_logging_mode(nutrition_csv_path, config_path=None):
    """
    `nutrition.csv` を読み、記録モード（`config/nutrition_logging.yaml`）を適用する

    - `complete`: そのまま
    - `protein_only`: protein 以外の栄養列（calories/carbs/fat/fiber/sodium/water）
      を NaN にする（0埋めしない）
    - `unknown`: その日の行を落とす
    - 宣言の外側の日付、および yaml 自体が無い場合は `unknown` 扱い
    - 期間は `from`/`to` を含む閉区間。`to` が無い期間は現在まで継続

    Parameters
    ----------
    nutrition_csv_path : str or Path
        `data/wearable/nutrition.csv` のパス
    config_path : str or Path, optional
        `config/nutrition_logging.yaml` のパス。省略・不在なら全期間 unknown

    Returns
    -------
    pd.DataFrame
        モード適用後のデータフレーム（unknown の日の行は含まない）
    """
    df = pd.read_csv(nutrition_csv_path)
    df['date'] = pd.to_datetime(df['date'])

    periods = load_logging_periods(config_path)
    modes = df['date'].apply(lambda d: _mode_for_date(d, periods))

    protein_only_mask = modes == 'protein_only'
    blank_columns = [c for c in PROTEIN_ONLY_BLANK_COLUMNS if c in df.columns]
    if blank_columns:
        df.loc[protein_only_mask, blank_columns] = np.nan

    df = df[modes != 'unknown'].reset_index(drop=True)
    return df
