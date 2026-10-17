#!/usr/bin/env python
# coding: utf-8
"""
体重の日次系列（全期間・1日1行）

体重計の値は複数の経路に写されている。2026-10 時点では
HealthPlanet が実測の入口で、Google Health はその写し（HEALTH_CONNECT）と
Fitbit 時代の履歴（FITBIT / FITBIT_WEB_API、2012〜）を持つ。
`data/wearable/body_weight.csv` は Google Health に全日が含まれるので使わない。

どちらか一方だけでは全期間を覆えない。Google Health には HealthPlanet の
180日（2022年は丸ごと）が届いておらず、HealthPlanet は 2020-01 より前を持たない。
そこで日付ごとに SOURCES の先頭から値のある経路を1つ採る。経路を足すときは
SOURCES に1行足す。

体脂肪率は入れない。機器ごとに推定式が違い、経路をまたいで繋げられない。
"""

import pandas as pd

# (source, path, 日付列, 体重列, 時刻列)。先頭ほど優先。
# 時刻列がある経路は、同じ日に複数回測っていれば最初の測定を採る
SOURCES = (
    ('healthplanet', 'data/healthplanet_innerscan.csv', 'date', 'weight', None),
    ('googlehealth', 'data/googlehealth/weight.csv', 'date', 'weight_kg', 'time'),
)

COLUMNS = ['date', 'weight', 'source']


def _one_per_day(df, date_col, weight_col, time_col):
    df = df.dropna(subset=[weight_col])
    if time_col is not None:
        df = df.sort_values(time_col, kind='stable')
    df = df.drop_duplicates(subset=[date_col], keep='first')
    return pd.DataFrame({
        'date': pd.to_datetime(df[date_col]).dt.normalize(),
        'weight': df[weight_col].astype(float),
    })


def build_weight_daily(frames):
    """経路ごとの DataFrame から1日1行の体重系列を作る

    Parameters
    ----------
    frames : dict[str, DataFrame]
        source 名 → 元 CSV をそのまま読んだもの。無い経路は省いてよい

    Returns
    -------
    DataFrame
        date, weight, source。date 昇順。どの経路にも値が無い日は行を作らない
    """
    parts = []
    for rank, (source, _, date_col, weight_col, time_col) in enumerate(SOURCES):
        df = frames.get(source)
        if df is None or df.empty:
            continue
        part = _one_per_day(df, date_col, weight_col, time_col)
        parts.append(part.assign(source=source, _rank=rank))
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    merged = (pd.concat(parts)
              .sort_values(['date', '_rank'])
              .drop_duplicates(subset=['date'], keep='first'))
    return merged[COLUMNS].reset_index(drop=True)


def load_weight_daily(base_dir):
    """SOURCES の CSV を base_dir から読んで build_weight_daily() に渡す"""
    frames = {}
    for source, path, *_ in SOURCES:
        full = base_dir / path
        if full.exists():
            frames[source] = pd.read_csv(full)
    return build_weight_daily(frames)
