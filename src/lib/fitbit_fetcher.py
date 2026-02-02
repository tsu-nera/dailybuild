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
        'is_time_series_api': True,  # Time Series API（期間指定、1リクエスト）
    },
    'hrv': {
        'description': 'HRV（心拍変動）',
        'fetch_fn': 'get_hrv_by_date_range',
        'parse_fn': 'parse_hrv',
        'date_column': 'date',
        'max_days': 30,
        'is_range_api': True,
    },
    'heart_rate': {
        'description': '安静時心拍数',
        'fetch_fn': 'get_heart_rate_by_date_range',
        'parse_fn': 'parse_heart_rate',
        'date_column': 'date',
        'max_days': 30,
        'is_range_api': True,
    },
    'activity': {
        'description': 'アクティビティサマリー',
        'fetch_fn': 'get_activity_summary_by_date_range',
        'parse_fn': None,  # DataFrameを直接返す
        'date_column': 'date',
        'max_days': None,
        'is_time_series_api': False,  # 日付ごとにループ（N日間=Nリクエスト）
    },
    'active_zone_minutes': {
        'description': 'アクティブゾーン分数',
        'fetch_fn': 'get_active_zone_minutes_by_date_range',
        'parse_fn': 'parse_active_zone_minutes',
        'date_column': 'date',
        'max_days': None,  # 最大1095日間
        'is_range_api': True,
    },
    'nutrition': {
        'description': '栄養データ（食事ログサマリー）',
        'fetch_fn': 'get_food_log_by_date_range',
        'parse_fn': 'parse_food_log',
        'date_column': 'date',
        'max_days': None,
        'is_time_series_api': False,  # 日付ごとにループ（N日間=Nリクエスト）
        'has_nutrition_logs': True,  # 個別食事ログあり
    },
    'breathing_rate': {
        'description': '呼吸数',
        'fetch_fn': 'get_breathing_rate_by_date_range',
        'parse_fn': 'parse_breathing_rate',
        'date_column': 'date',
        'max_days': 30,
        'is_range_api': True,
    },
    'spo2': {
        'description': '血中酸素濃度（SpO2）',
        'fetch_fn': 'get_spo2_by_date_range',
        'parse_fn': 'parse_spo2',
        'date_column': 'date',
        'max_days': 30,
        'is_range_api': True,
    },
    'cardio_score': {
        'description': '心肺スコア（VO2 Max）',
        'fetch_fn': 'get_cardio_score_by_date_range',
        'parse_fn': 'parse_cardio_score',
        'date_column': 'date',
        'max_days': 30,
        'is_range_api': True,
    },
    'temperature_skin': {
        'description': '皮膚温（睡眠中）',
        'fetch_fn': 'get_temperature_skin_by_date_range',
        'parse_fn': 'parse_temperature_skin',
        'date_column': 'date',
        'max_days': 30,
        'is_range_api': True,
    },
    'temperature_core': {
        'description': '体温（手動記録）',
        'fetch_fn': 'get_temperature_core_by_date_range',
        'parse_fn': 'parse_temperature_core',
        'date_column': 'date_time',
        'max_days': 30,
        'is_range_api': True,
    },
    'activity_logs': {
        'description': '個別アクティビティログ（運動記録）',
        'fetch_fn': 'get_activity_logs_by_date_range',
        'parse_fn': None,  # DataFrameを直接返す
        'date_column': 'startTime',
        'max_days': None,
        'is_paginated': True,  # ページング方式のAPI
        'is_time_series_api': False,  # ページング（データ量次第）
    },
    'heart_rate_intraday': {
        'description': '心拍数Intraday（1分間隔）',
        'fetch_fn': 'get_heart_rate_intraday_by_date_range',
        'parse_fn': None,  # DataFrameを直接返す
        'date_column': 'datetime',
        'max_days': None,
        'is_time_series_api': False,  # 日付ごとにループ（N日間=Nリクエスト）
        'is_intraday': True,  # Intraday API
    },
    'steps_intraday': {
        'description': '歩数Intraday（1分間隔）',
        'fetch_fn': 'get_steps_intraday_by_date_range',
        'parse_fn': None,  # DataFrameを直接返す
        'date_column': 'datetime',
        'max_days': None,
        'is_time_series_api': False,  # 日付ごとにループ（N日間=Nリクエスト）
        'is_intraday': True,  # Intraday API
    },
    # 'hrv_intraday': {
    #     'description': 'HRV Intraday（5分間隔）',
    #     'fetch_fn': 'get_hrv_intraday_by_date_range',
    #     'parse_fn': None,  # DataFrameを直接返す
    #     'date_column': 'datetime',
    #     'max_days': 30,  # HRV intradayは最大30日間
    #     'is_time_series_api': False,  # 日付ごとにループ（N日間=Nリクエスト）
    #     'is_intraday': True,  # Intraday API
    # },
}


def get_output_path(endpoint: str) -> Path:
    """エンドポイントの出力パスを取得"""
    return DATA_DIR / f'{endpoint}.csv'


def get_levels_output_path() -> Path:
    """睡眠ステージ詳細データの出力パスを取得"""
    return DATA_DIR / 'sleep_levels.csv'


def get_nutrition_logs_output_path() -> Path:
    """個別食事ログの出力パスを取得"""
    return DATA_DIR / 'nutrition_logs.csv'


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


def fetch_endpoint(client, endpoint: str, days: int = None, overwrite: bool = False,
                   start_date: dt.date = None, end_date: dt.date = None) -> dict:
    """
    指定エンドポイントのデータを取得・保存

    Args:
        client: Fitbitクライアント
        endpoint: エンドポイント名（sleep, hrv, heart_rate, activity）
        days: 取得日数（start_dateが指定されていない場合のみ有効）
        overwrite: 上書きモード
        start_date: 開始日（指定時はdaysを無視）
        end_date: 終了日（start_date指定時のみ有効、未指定時は今日）

    Returns:
        結果情報の辞書（records: レコード数, path: 保存パス, error: エラーメッセージ）
    """
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown endpoint: {endpoint}. Available: {list(ENDPOINTS.keys())}")

    config = ENDPOINTS[endpoint]

    # 日付範囲の決定
    if start_date is not None:
        # start_date指定時
        if end_date is None:
            end_date = dt.date.today()
        calc_days = (end_date - start_date).days + 1
    else:
        # days指定時
        if days is None:
            days = 14
        end_date = dt.date.today()
        start_date = end_date - dt.timedelta(days=days - 1)
        calc_days = days

    # 最大日数制限チェック - 100日を超える場合は自動分割
    max_days = config.get('max_days')
    if max_days and calc_days > max_days:
        print(f"{config['description']}を取得中... ({start_date} ~ {end_date}, {calc_days}日)")
        print(f"  {max_days}日制限があるため、{max_days}日ごとに分割取得します")
        return _fetch_endpoint_chunked(client, endpoint, start_date, end_date, max_days, overwrite, config)

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
        # activity, activity_logsはDataFrameを直接返す
        df = response
        if df.empty:
            print(f"  データがありません")
            return {'records': 0, 'path': None}

    # 日付列の処理
    date_col = config['date_column']
    df[date_col] = pd.to_datetime(df[date_col])

    # 保存
    out_path = get_output_path(endpoint)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not overwrite:
        # 睡眠データはlogIdで重複判定（同じ日に複数の睡眠ログがあるため）
        if endpoint == 'sleep' and 'logId' in df.columns:
            df = csv_utils.merge_csv_by_columns(
                df, out_path,
                key_columns=['logId'],
                parse_dates=[date_col],
                sort_by=[date_col]
            )
        else:
            # その他のエンドポイントは日付で重複判定
            df.set_index(date_col, inplace=True)
            df = csv_utils.merge_csv(df, out_path, date_col)
    else:
        # overwriteモードでは既存のインデックス処理を維持
        if endpoint != 'sleep' or 'logId' not in df.columns:
            df.set_index(date_col, inplace=True)

    # CSVに保存（睡眠データはindex=False、その他はindex=True）
    if endpoint == 'sleep' and 'logId' in df.columns:
        df.to_csv(out_path, index=False)
    else:
        df.to_csv(out_path)
    print(f"  保存: {out_path} ({len(df)}件)")

    result = {'records': len(df), 'path': out_path}

    # 睡眠ステージ詳細データ（sleepのみ）
    if config.get('has_levels'):
        levels_result = _save_sleep_levels(response, overwrite)
        result['levels'] = levels_result

    # 個別食事ログ（nutritionのみ）
    if config.get('has_nutrition_logs'):
        nutrition_logs_result = _save_nutrition_logs(response, overwrite)
        result['nutrition_logs'] = nutrition_logs_result

    return result


def _fetch_endpoint_chunked(client, endpoint: str, start_date: dt.date, end_date: dt.date,
                             max_days: int, overwrite: bool, config: dict) -> dict:
    """
    100日を超える期間を自動分割して取得

    Args:
        client: Fitbitクライアント
        endpoint: エンドポイント名
        start_date: 開始日
        end_date: 終了日
        max_days: API最大日数制限（通常100日）
        overwrite: 上書きモード
        config: エンドポイント設定

    Returns:
        結果情報の辞書
    """
    all_records = []
    all_sleep_levels = []  # sleep_levels用
    all_nutrition_logs = []  # nutrition_logs用
    current_start = start_date
    chunk_num = 1
    total_chunks = ((end_date - start_date).days + max_days) // max_days

    while current_start <= end_date:
        # チャンクの終了日を計算（max_days-1日後、またはend_dateまで）
        chunk_end = min(current_start + dt.timedelta(days=max_days - 1), end_date)

        print(f"  チャンク {chunk_num}/{total_chunks}: {current_start} ~ {chunk_end}")

        try:
            # API呼び出し
            fetch_fn = getattr(fitbit_api, config['fetch_fn'])
            response = fetch_fn(client, current_start, chunk_end)

            # パース
            if config['parse_fn']:
                parse_fn = getattr(fitbit_api, config['parse_fn'])
                records = parse_fn(response)
                if records:
                    all_records.extend(records)
                    print(f"    取得: {len(records)}件")
                else:
                    print(f"    データなし")
            else:
                # activity, activity_logsはDataFrameを直接返す
                df_chunk = response
                if not df_chunk.empty:
                    all_records.append(df_chunk)
                    print(f"    取得: {len(df_chunk)}件")
                else:
                    print(f"    データなし")

            # sleep_levelsも取得
            if config.get('has_levels'):
                levels_data = fitbit_api.parse_sleep_levels(response)
                if levels_data:
                    all_sleep_levels.extend(levels_data)

            # nutrition_logsも取得
            if config.get('has_nutrition_logs'):
                nutrition_logs_data = fitbit_api.parse_nutrition_logs(response)
                if nutrition_logs_data:
                    all_nutrition_logs.extend(nutrition_logs_data)

        except Exception as e:
            error_msg = _format_api_error(e)
            print(f"    エラー: {error_msg}")
            # エラーがあっても次のチャンクを続行

        # 次のチャンクへ
        current_start = chunk_end + dt.timedelta(days=1)
        chunk_num += 1

    # 全チャンクのデータがない場合
    if not all_records:
        print(f"  全期間でデータがありません")
        return {'records': 0, 'path': None}

    # DataFrameに変換
    if config['parse_fn']:
        df = pd.DataFrame(all_records)
    else:
        # activity, activity_logsは複数のDataFrameを結合
        df = pd.concat(all_records, ignore_index=True)

    # 日付列の処理
    date_col = config['date_column']
    df[date_col] = pd.to_datetime(df[date_col])

    # 保存
    out_path = get_output_path(endpoint)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not overwrite:
        # 睡眠データはlogIdで重複判定（同じ日に複数の睡眠ログがあるため）
        if endpoint == 'sleep' and 'logId' in df.columns:
            df = csv_utils.merge_csv_by_columns(
                df, out_path,
                key_columns=['logId'],
                parse_dates=[date_col],
                sort_by=[date_col]
            )
        else:
            # その他のエンドポイントは日付で重複判定
            df.set_index(date_col, inplace=True)
            df = csv_utils.merge_csv(df, out_path, date_col)
    else:
        # overwriteモードでは既存のインデックス処理を維持
        if endpoint != 'sleep' or 'logId' not in df.columns:
            df.set_index(date_col, inplace=True)

    # CSVに保存（睡眠データはindex=False、その他はindex=True）
    if endpoint == 'sleep' and 'logId' in df.columns:
        df.to_csv(out_path, index=False)
    else:
        df.to_csv(out_path)
    print(f"  保存: {out_path} ({len(df)}件)")

    result = {'records': len(df), 'path': out_path}

    # 睡眠ステージ詳細データ（sleepのみ）
    if config.get('has_levels') and all_sleep_levels:
        df_levels = pd.DataFrame(all_sleep_levels)
        df_levels['dateTime'] = pd.to_datetime(df_levels['dateTime'])
        df_levels.sort_values(['dateOfSleep', 'dateTime'], inplace=True)

        out_levels_path = get_levels_output_path()

        if not overwrite:
            df_levels = csv_utils.merge_csv_by_columns(
                df_levels, out_levels_path,
                key_columns=['dateOfSleep', 'dateTime'],
                parse_dates=['dateTime'],
                sort_by=['dateOfSleep', 'dateTime']
            )

        df_levels.to_csv(out_levels_path, index=False)
        print(f"  詳細保存: {out_levels_path} ({len(df_levels)}件)")

        result['levels'] = {'records': len(df_levels), 'path': out_levels_path}

    # 個別食事ログ（nutritionのみ）
    if config.get('has_nutrition_logs') and all_nutrition_logs:
        df_nutrition_logs = pd.DataFrame(all_nutrition_logs)
        df_nutrition_logs['logDate'] = pd.to_datetime(df_nutrition_logs['logDate'])
        df_nutrition_logs.sort_values(['logDate', 'logId'], inplace=True)

        out_nutrition_logs_path = get_nutrition_logs_output_path()

        if not overwrite:
            df_nutrition_logs = csv_utils.merge_csv_by_columns(
                df_nutrition_logs, out_nutrition_logs_path,
                key_columns=['logId'],
                parse_dates=['logDate'],
                sort_by=['logDate', 'logId']
            )

        df_nutrition_logs.to_csv(out_nutrition_logs_path, index=False)
        print(f"  個別ログ保存: {out_nutrition_logs_path} ({len(df_nutrition_logs)}件)")

        result['nutrition_logs'] = {'records': len(df_nutrition_logs), 'path': out_nutrition_logs_path}

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


def _save_nutrition_logs(response: dict, overwrite: bool) -> dict:
    """個別食事ログを保存"""
    nutrition_logs_data = fitbit_api.parse_nutrition_logs(response)
    if not nutrition_logs_data:
        return {'records': 0, 'path': None}

    df_logs = pd.DataFrame(nutrition_logs_data)
    df_logs['logDate'] = pd.to_datetime(df_logs['logDate'])
    df_logs.sort_values(['logDate', 'logId'], inplace=True)

    out_path = get_nutrition_logs_output_path()

    if not overwrite:
        df_logs = csv_utils.merge_csv_by_columns(
            df_logs, out_path,
            key_columns=['logId'],
            parse_dates=['logDate'],
            sort_by=['logDate', 'logId']
        )

    df_logs.to_csv(out_path, index=False)
    print(f"  個別ログ保存: {out_path} ({len(df_logs)}件)")

    return {'records': len(df_logs), 'path': out_path}


def fetch_time_series_endpoints(client, days: int = None, overwrite: bool = False,
                                start_date: dt.date = None, end_date: dt.date = None) -> dict:
    """
    Time Series API（期間指定、1リクエスト）のエンドポイントを取得

    Args:
        client: Fitbitクライアント
        days: 取得日数
        overwrite: 上書きモード
        start_date: 開始日（指定時はdaysを無視）
        end_date: 終了日（start_date指定時のみ有効、未指定時は今日）

    Returns:
        各エンドポイントの結果辞書

    Note:
        sleep, hrv, heart_rate, active_zone_minutes, breathing_rate,
        spo2, cardio_score, temperature_skin, temperature_core
    """
    results = {}
    errors = []

    for endpoint, config in ENDPOINTS.items():
        # is_time_series_api または is_range_api のどちらかがTrueなら対象
        if not (config.get('is_time_series_api', False) or config.get('is_range_api', False)):
            continue

        print(f"\n=== {config['description']} ===")
        result = fetch_endpoint(client, endpoint, days, overwrite, start_date, end_date)
        results[endpoint] = result

        if result.get('error'):
            errors.append(f"{endpoint}: {result['error']}")

    return results, errors


def fetch_daily_endpoints(client, days: int = None, overwrite: bool = False,
                          start_date: dt.date = None, end_date: dt.date = None) -> dict:
    """
    日付ごとループまたはページング方式のエンドポイントを取得

    Args:
        client: Fitbitクライアント
        days: 取得日数
        overwrite: 上書きモード
        start_date: 開始日（指定時はdaysを無視）
        end_date: 終了日（start_date指定時のみ有効、未指定時は今日）

    Returns:
        各エンドポイントの結果辞書

    Note:
        activity（日付ごと）, nutrition（日付ごと）, activity_logs（ページング）
    """
    results = {}
    errors = []

    for endpoint, config in ENDPOINTS.items():
        # is_time_series_api または is_range_api がTrueの場合は対象外
        if config.get('is_time_series_api', False) or config.get('is_range_api', False):
            continue

        print(f"\n=== {config['description']} ===")
        result = fetch_endpoint(client, endpoint, days, overwrite, start_date, end_date)
        results[endpoint] = result

        if result.get('error'):
            errors.append(f"{endpoint}: {result['error']}")

    return results, errors


def fetch_all(client, days: int = None, overwrite: bool = False,
              start_date: dt.date = None, end_date: dt.date = None) -> dict:
    """
    全エンドポイントのデータを取得

    Args:
        client: Fitbitクライアント
        days: 取得日数
        overwrite: 上書きモード
        start_date: 開始日（指定時はdaysを無視）
        end_date: 終了日（start_date指定時のみ有効、未指定時は今日）

    Returns:
        各エンドポイントの結果辞書
        各結果: {records: int, path: Path, error: str (optional)}

    Note:
        Time Series API（1リクエスト）と日付ごとAPI（N日間=Nリクエスト）を
        分けて実行することで、リクエスト数を把握しやすくする
    """
    print("=" * 60)
    print("Time Series API（期間指定、1リクエスト）")
    print("=" * 60)
    time_series_results, time_series_errors = fetch_time_series_endpoints(
        client, days, overwrite, start_date, end_date
    )

    print("\n" + "=" * 60)
    print("日付ごとAPI（N日間=Nリクエスト）")
    print("=" * 60)
    daily_results, daily_errors = fetch_daily_endpoints(
        client, days, overwrite, start_date, end_date
    )

    # 結果を統合
    results = {**time_series_results, **daily_results}
    errors = time_series_errors + daily_errors

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
