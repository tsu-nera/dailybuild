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


def format_volume(value, is_bodyweight=False):
    """
    Volumeを適切な単位でフォーマット（ワークアウト用）

    Parameters
    ----------
    value : float
        Volume値
    is_bodyweight : bool
        自重エクササイズかどうか

    Returns
    -------
    str
        フォーマット済み文字列（例: "3150 kg" or "45 reps"）

    Examples
    --------
    >>> format_volume(3150.0, False)
    '3150 kg'
    >>> format_volume(45.0, True)
    '45 reps'
    >>> format_volume(None, False)
    '-'
    """
    if pd.isna(value):
        return "-"
    if is_bodyweight:
        return f"{int(value)} reps"
    else:
        return f"{int(value)} kg"


def format_volume_simple(value):
    """
    Volumeを単位なしでフォーマット（週次サマリー用）

    Parameters
    ----------
    value : float
        Volume値

    Returns
    -------
    str
        フォーマット済み文字列（例: "3150" or "45"）

    Examples
    --------
    >>> format_volume_simple(3150.0)
    '3150'
    >>> format_volume_simple(None)
    '-'
    """
    if pd.isna(value):
        return "-"
    return str(int(value))


def format_volume_change(value, is_bodyweight=False):
    """
    ワークアウトボリューム変化量をフォーマット（プラスは太字）

    Parameters
    ----------
    value : float
        変化量
    is_bodyweight : bool
        自重エクササイズかどうか

    Returns
    -------
    str
        フォーマット済み変化量（プラスの場合は太字）

    Notes
    -----
    ワークアウトでは増加が常に良いとされるため positive_is_good=True 固定

    Examples
    --------
    >>> format_volume_change(150.0, False)
    '**+150 kg**'
    >>> format_volume_change(-50.0, True)
    '-50 reps'
    >>> format_volume_change(0, False)
    '±0 kg'
    """
    if pd.isna(value):
        return "-"
    if value == 0:
        unit = " reps" if is_bodyweight else " kg"
        return f"±0{unit}"

    sign = '+' if value > 0 else ''
    unit = " reps" if is_bodyweight else " kg"
    formatted = f"{sign}{int(value)}{unit}"

    # プラスの変化は太字で強調（ワークアウトは増加が良い）
    if value > 0:
        return f"**{formatted}**"
    else:
        return formatted


def format_weights(min_weight, max_weight, is_bodyweight=False):
    """
    重量範囲をmin/max形式でフォーマット

    Parameters
    ----------
    min_weight : float
        最小重量
    max_weight : float
        最大重量
    is_bodyweight : bool
        自重エクササイズかどうか

    Returns
    -------
    str
        フォーマット済み文字列（例: "50/60 kg" or "-"）

    Examples
    --------
    >>> format_weights(50.0, 60.0, False)
    '50/60 kg'
    >>> format_weights(50.0, 50.0, False)
    '50 kg'
    >>> format_weights(50.0, 60.0, True)
    '-'
    """
    if is_bodyweight or pd.isna(min_weight) or pd.isna(max_weight):
        return "-"

    # min == maxの場合は単一値表示
    if min_weight == max_weight:
        return f"{int(min_weight)} kg"
    else:
        return f"{int(min_weight)}/{int(max_weight)} kg"
