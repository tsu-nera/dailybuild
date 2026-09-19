#!/usr/bin/env python
# coding: utf-8
"""
Jinja2カスタムフィルタ

レポートテンプレート用のフォーマット関数を提供
"""

import pandas as pd


def format_change(value, unit='', positive_is_good=True):
    """
    変化量をフォーマット（良い変化は太字）

    Parameters
    ----------
    value : float
        変化量
    unit : str
        単位（'kg', '%', 'ms', 'bpm'など）
    positive_is_good : bool
        プラスが良い変化かどうか
        - True: 筋肉量、HRVなど（増加が良い）
        - False: 体脂肪率、RHRなど（減少が良い）

    Returns
    -------
    str
        フォーマットされた変化量
        - 良い変化: **太字**
        - 悪い変化: 通常
        - ゼロ: ±0{unit}

    Examples
    --------
    >>> format_change(2.5, 'kg', positive_is_good=True)
    '**+2.50kg**'
    >>> format_change(-1.3, '%', positive_is_good=False)
    '**-1.30%**'
    >>> format_change(0, '')
    '±0'
    """
    if pd.isna(value) or value is None:
        return "-"
    if value == 0:
        return f"±0{unit}"

    sign = '+' if value > 0 else ''
    formatted = f"{sign}{value:.2f}{unit}"

    # 良い変化の判定
    is_good = (value > 0 and positive_is_good) or (value < 0 and not positive_is_good)

    if is_good:
        return f"**{formatted}**"
    else:
        return formatted


def date_format(date, format='%m-%d'):
    """
    日付をフォーマット

    Parameters
    ----------
    date : str or datetime
        日付
    format : str
        フォーマット文字列（strftimeフォーマット）

    Returns
    -------
    str
        フォーマットされた日付

    Examples
    --------
    >>> date_format('2025-12-23', '%m-%d')
    '12-23'
    >>> date_format('2025-12-23', '%Y-%m-%d')
    '2025-12-23'
    """
    return pd.to_datetime(date).strftime(format)


def number_format(value, decimals=1):
    """
    数値をフォーマット（NaN対応）

    Parameters
    ----------
    value : float or None
        数値
    decimals : int
        小数点以下の桁数

    Returns
    -------
    str
        フォーマットされた数値。NaNの場合は'-'

    Examples
    --------
    >>> number_format(12.345, 1)
    '12.3'
    >>> number_format(None, 1)
    '-'
    >>> number_format(float('nan'), 1)
    '-'
    """
    if pd.isna(value):
        return '-'
    return f"{value:.{decimals}f}"
