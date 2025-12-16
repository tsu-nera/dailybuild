#!/usr/bin/env python
# coding: utf-8
"""
Fitbit データ取得共通処理

各エンドポイントの設定を定義し、統一的にデータ取得・保存を行う。
"""

import datetime as dt
from pathlib import Path

import pandas as pd

from .clients import fitbit_api
from .utils import csv_utils


def _patch_fitbit_exceptions():
    """
    fitbitライブラリのexceptions.pyのバグを回避するパッチ

    Retry-Afterヘッダーがない場合のKeyErrorを防ぐ
    """
    import fitbit.exceptions

    original_detect = fitbit.exceptions.detect_and_raise_error

    def patched_detect_and_raise_error(response):
        """Retry-Afterヘッダーのチェックを安全に行う"""
        if response.status_code >= 400:
            # エラーレスポンスの詳細を保存
            error_data = {
                'status_code': response.status_code,
                'headers': dict(response.headers),
                'body': response.text[:1000],  # 最初の1000文字
            }

            # Retry-Afterヘッダーを安全に取得
            retry_after = response.headers.get('Retry-After')

            try:
                # 元の関数を呼び出し
                return original_detect(response)
            except KeyError as e:
                if 'retry-after' in str(e).lower():
                    # KeyErrorの場合は、より詳細な例外を投げる
                    exc = fitbit.exceptions.HTTPException(response)
                    exc.status = response.status_code
                    exc.error_data = error_data
                    if retry_after:
                        exc.retry_after_secs = int(retry_after)
                    raise exc
                else:
                    raise
        return response

    fitbit.exceptions.detect_and_raise_error = patched_detect_and_raise_error


# fitbitライブラリのエラーハンドリングのバグを回避するためのパッチを適用
_patch_fitbit_exceptions()

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
    'active_zone_minutes': {
        'description': 'アクティブゾーン分数',
        'fetch_fn': 'get_active_zone_minutes_by_date_range',
        'parse_fn': 'parse_active_zone_minutes',
        'date_column': 'date',
        'max_days': None,  # 最大1095日間
    },
    'nutrition': {
        'description': '栄養データ（食事ログサマリー）',
        'fetch_fn': 'get_food_log_by_date_range',
        'parse_fn': 'parse_food_log',
        'date_column': 'date',
        'max_days': None,
    },
    'breathing_rate': {
        'description': '呼吸数',
        'fetch_fn': 'get_breathing_rate_by_date_range',
        'parse_fn': 'parse_breathing_rate',
        'date_column': 'date',
        'max_days': 30,
    },
    'spo2': {
        'description': '血中酸素濃度（SpO2）',
        'fetch_fn': 'get_spo2_by_date_range',
        'parse_fn': 'parse_spo2',
        'date_column': 'date',
        'max_days': 30,
    },
    'cardio_score': {
        'description': '心肺スコア（VO2 Max）',
        'fetch_fn': 'get_cardio_score_by_date_range',
        'parse_fn': 'parse_cardio_score',
        'date_column': 'date',
        'max_days': 30,
    },
    'temperature_skin': {
        'description': '皮膚温（睡眠中）',
        'fetch_fn': 'get_temperature_skin_by_date_range',
        'parse_fn': 'parse_temperature_skin',
        'date_column': 'date',
        'max_days': 30,
    },
    'temperature_core': {
        'description': '体温（手動記録）',
        'fetch_fn': 'get_temperature_core_by_date_range',
        'parse_fn': 'parse_temperature_core',
        'date_column': 'date_time',
        'max_days': 30,
    },
}


def get_output_path(endpoint: str) -> Path:
    """エンドポイントの出力パスを取得"""
    return DATA_DIR / f'{endpoint}.csv'


def get_levels_output_path() -> Path:
    """睡眠ステージ詳細データの出力パスを取得"""
    return DATA_DIR / 'sleep_levels.csv'


def _format_api_error(exception: Exception) -> str:
    """
    APIエラーを読みやすい形式にフォーマット

    Args:
        exception: 発生した例外

    Returns:
        フォーマットされたエラーメッセージ
    """
    import fitbit.exceptions

    # fitbitライブラリの例外の場合
    if isinstance(exception, fitbit.exceptions.HTTPException):
        # HTTPレスポンスから詳細を取得
        status = getattr(exception, 'status', getattr(exception, 'status_code', 'Unknown'))

        # パッチで追加したerror_data属性から詳細を取得
        if hasattr(exception, 'error_data'):
            error_data = exception.error_data
            status_code = error_data.get('status_code', status)
            body = error_data.get('body', '')

            # HTTPステータスコードに応じたメッセージ
            if status_code == 429:
                return f"HTTP 429: レート制限に達しました。しばらく待ってから再試行してください。"
            elif status_code == 403:
                return f"HTTP 403: アクセス権限がありません（デバイスがこの機能をサポートしていない可能性）"
            elif status_code == 404:
                return f"HTTP 404: データが見つかりません"
            elif status_code >= 500:
                return f"HTTP {status_code}: Fitbitサーバーエラー"
            else:
                # レスポンス本文から詳細を取得
                msg = body[:200] if body else str(exception)
                return f"HTTP {status_code}: {msg}"

        # 通常の例外メッセージ
        msg = exception.message if hasattr(exception, 'message') else str(exception)
        return f"HTTP {status}: {msg}"

    # KeyError: 'retry-after' の場合（パッチが適用される前にエラーが発生した場合）
    if isinstance(exception, KeyError) and 'retry-after' in str(exception).lower():
        return "APIエラー（詳細不明、fitbitライブラリのバグによりエラー情報が失われました）"

    # 一般的な例外
    error_type = type(exception).__name__
    error_msg = str(exception)

    return f"{error_type}: {error_msg}"


def fetch_endpoint(client, endpoint: str, days: int = 14, overwrite: bool = False) -> dict:
    """
    指定エンドポイントのデータを取得・保存

    Args:
        client: Fitbitクライアント
        endpoint: エンドポイント名（sleep, hrv, heart_rate, activity）
        days: 取得日数
        overwrite: 上書きモード

    Returns:
        結果情報の辞書（records: レコード数, path: 保存パス, error: エラーメッセージ）
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

    try:
        # API呼び出し
        fetch_fn = getattr(fitbit_api, config['fetch_fn'])
        response = fetch_fn(client, start_date, end_date)
    except Exception as e:
        error_msg = _format_api_error(e)
        print(f"  エラー: {error_msg}")
        return {'records': 0, 'path': None, 'error': error_msg}

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
        各結果: {records: int, path: Path, error: str (optional)}
    """
    results = {}
    errors = []

    for endpoint in ENDPOINTS:
        print(f"\n=== {ENDPOINTS[endpoint]['description']} ===")
        result = fetch_endpoint(client, endpoint, days, overwrite)
        results[endpoint] = result

        if result.get('error'):
            errors.append(f"{endpoint}: {result['error']}")

    # エラーサマリーを表示
    if errors:
        print(f"\n⚠️  {len(errors)}件のエンドポイントでエラーが発生:")
        for error in errors:
            print(f"  - {error}")

    return results


def list_endpoints() -> list[str]:
    """利用可能なエンドポイント一覧を取得"""
    return list(ENDPOINTS.keys())


def get_endpoint_info(endpoint: str) -> dict:
    """エンドポイントの情報を取得"""
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown endpoint: {endpoint}")
    return ENDPOINTS[endpoint].copy()
