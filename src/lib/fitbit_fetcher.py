#!/usr/bin/env python
# coding: utf-8
"""
Fitbit データ取得共通処理

各エンドポイントの設定を定義し、統一的にデータ取得・保存を行う。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from . import fitbit_api, csv_utils

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / 'data' / 'fitbit'


ENDPOINTS = {
    'sleep': {
        'description': '睡眠データ',
        'fetch_fn': 'get_sleep_log_by_date_range',
        'parse_fn': 'parse_sleep',
        'date_column': 'dateOfSleep',
        'max_days': 100,
        'has_levels': True,
    },
    'hrv': {
        'description': 'HRV（心拍変動）',
        'fetch_fn': 'get_hrv_by_date_range',
        'parse_fn': 'parse_hrv',
        'date_column': 'date',
        'max_days': 30,
    },
    'heart_rate': {
        'description': '安静時心拍数',
        'fetch_fn': 'get_heart_rate_by_date_range',
        'parse_fn': 'parse_heart_rate',
        'date_column': 'date',
        'max_days': 30,
    },
    'activity': {
        'description': 'アクティビティサマリー',
        'fetch_fn': 'get_activity_summary_by_date_range',
        'parse_fn': None,  # DataFrameを直接返す
        'date_column': 'date',
        'max_days': None,
    },
}


def get_output_path(endpoint: str) -> Path:
    """エンドポイントの出力パスを取得"""
    return DATA_DIR / f'{endpoint}.csv'


def get_levels_output_path() -> Path:
    """睡眠ステージ詳細データの出力パスを取得"""
    return DATA_DIR / 'sleep_levels.csv'


def fetch_endpoint(client, endpoint: str, days: int = 14, overwrite: bool = False) -> dict:
    """
    指定エンドポイントのデータを取得・保存

    Args:
        client: Fitbitクライアント
        endpoint: エンドポイント名（sleep, hrv, heart_rate, activity）
        days: 取得日数
        overwrite: 上書きモード

    Returns:
        結果情報の辞書（records: レコード数, path: 保存パス）
    """
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown endpoint: {endpoint}. Available: {list(ENDPOINTS.keys())}")

    config = ENDPOINTS[endpoint]

    # 最大日数制限
    if config['max_days'] and days > config['max_days']:
        print(f"警告: {endpoint} APIは最大{config['max_days']}日間まで。制限します。")
        days = config['max_days']

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=days - 1)

    print(f"{config['description']}を取得中... ({start_date} ~ {end_date})")

    # API呼び出し
    fetch_fn = getattr(fitbit_api, config['fetch_fn'])
    response = fetch_fn(client, start_date, end_date)

    # パース
    if config['parse_fn']:
        parse_fn = getattr(fitbit_api, config['parse_fn'])
        records = parse_fn(response)
        if not records:
            print(f"  データがありません")
            return {'records': 0, 'path': None}
        df = pd.DataFrame(records)
    else:
        # activityはDataFrameを直接返す
        df = response
        if df.empty:
            print(f"  データがありません")
            return {'records': 0, 'path': None}

    # 日付列の処理
    date_col = config['date_column']
    df[date_col] = pd.to_datetime(df[date_col])
    df.set_index(date_col, inplace=True)
    df.sort_index(inplace=True)

    # 保存
    out_path = get_output_path(endpoint)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not overwrite:
        df = csv_utils.merge_csv(df, out_path, date_col)

    df.to_csv(out_path)
    print(f"  保存: {out_path} ({len(df)}件)")

    result = {'records': len(df), 'path': out_path}

    # 睡眠ステージ詳細データ（sleepのみ）
    if config.get('has_levels'):
        levels_result = _save_sleep_levels(response, overwrite)
        result['levels'] = levels_result

    return result


def _save_sleep_levels(response: dict, overwrite: bool) -> dict:
    """睡眠ステージ詳細データを保存"""
    levels_data = fitbit_api.parse_sleep_levels(response)
    if not levels_data:
        return {'records': 0, 'path': None}

    df_levels = pd.DataFrame(levels_data)
    df_levels['dateTime'] = pd.to_datetime(df_levels['dateTime'])
    df_levels.sort_values(['dateOfSleep', 'dateTime'], inplace=True)

    out_path = get_levels_output_path()

    if not overwrite:
        df_levels = csv_utils.merge_csv_by_columns(
            df_levels, out_path,
            key_columns=['dateOfSleep', 'dateTime'],
            parse_dates=['dateTime'],
            sort_by=['dateOfSleep', 'dateTime']
        )

    df_levels.to_csv(out_path, index=False)
    print(f"  詳細保存: {out_path} ({len(df_levels)}件)")

    return {'records': len(df_levels), 'path': out_path}


def fetch_all(client, days: int = 14, overwrite: bool = False) -> dict:
    """
    全エンドポイントのデータを取得

    Args:
        client: Fitbitクライアント
        days: 取得日数
        overwrite: 上書きモード

    Returns:
        各エンドポイントの結果辞書
    """
    results = {}
    for endpoint in ENDPOINTS:
        print(f"\n=== {ENDPOINTS[endpoint]['description']} ===")
        results[endpoint] = fetch_endpoint(client, endpoint, days, overwrite)
    return results


def list_endpoints() -> list[str]:
    """利用可能なエンドポイント一覧を取得"""
    return list(ENDPOINTS.keys())


def get_endpoint_info(endpoint: str) -> dict:
    """エンドポイントの情報を取得"""
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown endpoint: {endpoint}")
    return ENDPOINTS[endpoint].copy()
