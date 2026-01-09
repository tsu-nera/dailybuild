#!/usr/bin/env python
# coding: utf-8
"""
Fitbit API クライアント

python-fitbitライブラリはOAuth認証のみに使用。
APIコールはv1.2エンドポイントを直接呼び出す。
"""

import json
import os
import fitbit


def load_token(token_file):
    """トークンをファイルから読み込み"""
    with open(token_file, 'r') as f:
        return json.load(f)


def save_token(token_file, token):
    """トークンをファイルに保存"""
    with open(token_file, 'w') as f:
        json.dump(token, f, indent=2)


def create_client(creds_file, token_file):
    """
    Fitbitクライアントを作成

    python-fitbitはOAuth認証とトークン管理に使用。
    APIコールはmake_requestで任意のURLを指定可能。
    """
    with open(creds_file, 'r') as f:
        creds = json.load(f)

    token_data = load_token(token_file)

    def update_token(token):
        save_token(token_file, token)

    client = fitbit.Fitbit(
        creds['client_id'],
        creds['client_secret'],
        oauth2=True,
        access_token=token_data['access_token'],
        refresh_token=token_data['refresh_token'],
        refresh_cb=update_token
    )

    return client


def create_client_with_env(creds_file=None, token_file=None):
    """
    環境変数またはファイルからFitbitクライアントを作成

    Args:
        creds_file: 認証情報ファイルパス（環境変数がない場合に使用）
        token_file: トークンファイルパス（環境変数がない場合に使用）

    Returns:
        (client, updated_token_holder): クライアントと更新トークン格納用dict

    Note:
        環境変数 FITBIT_CREDS/FITBIT_TOKEN を優先的に使用
        ファイルが指定されている場合、トークン更新時にファイルに保存
    """
    fitbit_creds_env = os.environ.get('FITBIT_CREDS')
    fitbit_token_env = os.environ.get('FITBIT_TOKEN')

    updated_token = {'value': None}

    if fitbit_creds_env and fitbit_token_env:
        # 環境変数から読み込み
        creds = json.loads(fitbit_creds_env)
        token_data = json.loads(fitbit_token_env)

        def update_token(token):
            updated_token['value'] = token
            if token_file:
                save_token(token_file, token)

        client = fitbit.Fitbit(
            creds['client_id'],
            creds['client_secret'],
            oauth2=True,
            access_token=token_data['access_token'],
            refresh_token=token_data['refresh_token'],
            refresh_cb=update_token
        )

        return client, updated_token

    # ファイルから読み込み
    if not creds_file or not token_file:
        raise FileNotFoundError(
            "認証情報が見つかりません。\n"
            "環境変数 FITBIT_CREDS/FITBIT_TOKEN を設定するか、\n"
            "creds_file/token_file を指定してください。"
        )

    with open(creds_file, 'r') as f:
        creds = json.load(f)

    token_data = load_token(token_file)

    def update_token(token):
        updated_token['value'] = token
        save_token(token_file, token)

    client = fitbit.Fitbit(
        creds['client_id'],
        creds['client_secret'],
        oauth2=True,
        access_token=token_data['access_token'],
        refresh_token=token_data['refresh_token'],
        refresh_cb=update_token
    )

    return client, updated_token


# =============================================================================
# 汎用APIヘルパー
# =============================================================================

def _build_url(client, resource_path, api_version='1.2'):
    """
    Fitbit API URLを構築

    Args:
        client: Fitbitクライアント
        resource_path: リソースパス（例: 'sleep/date/2025-01-01'）
        api_version: APIバージョン（デフォルト: '1'）

    Returns:
        完全なAPI URL
    """
    return f"{client.API_ENDPOINT}/{api_version}/user/-/{resource_path}.json"


def get_by_date(client, resource, date, api_version='1.2'):
    """
    日付指定でリソースを取得（汎用）

    Args:
        client: Fitbitクライアント
        resource: リソース名（例: 'sleep', 'activities'）
        date: 日付（datetime.date）
        api_version: APIバージョン（デフォルト: '1'）

    Returns:
        APIレスポンス（dict）

    Example:
        get_by_date(client, 'sleep', date, '1.2')
        -> GET /1.2/user/-/sleep/date/2025-01-01.json
    """
    date_str = date.strftime('%Y-%m-%d')
    url = _build_url(client, f"{resource}/date/{date_str}", api_version)
    return client.make_request(url)


def get_by_date_range(client, resource, start_date, end_date, api_version='1.2'):
    """
    期間指定でリソースを取得（汎用）

    Args:
        client: Fitbitクライアント
        resource: リソース名（例: 'sleep', 'activities/tracker/steps'）
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）
        api_version: APIバージョン（デフォルト: '1'）

    Returns:
        APIレスポンス（dict）

    Example:
        get_by_date_range(client, 'sleep', start, end, '1.2')
        -> GET /1.2/user/-/sleep/date/2025-01-01/2025-01-07.json
    """
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    url = _build_url(client, f"{resource}/date/{start_str}/{end_str}", api_version)
    return client.make_request(url)


# =============================================================================
# Sleep API v1.2
# https://dev.fitbit.com/build/reference/web-api/sleep/
# =============================================================================

def get_sleep_log_by_date(client, date):
    """
    指定日の睡眠データを取得

    Args:
        client: Fitbitクライアント
        date: 日付（datetime.date）

    Returns:
        APIレスポンス（dict）: sleep配列 + summary

    https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/
    """
    return get_by_date(client, 'sleep', date)


def get_sleep_log_by_date_range(client, start_date, end_date):
    """
    期間指定で睡眠データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: sleep配列のみ

    Note:
        最大100日間まで一括取得可能

    https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date-range/
    """
    return get_by_date_range(client, 'sleep', start_date, end_date)


def parse_sleep(data):
    """
    睡眠ログをリストに変換（API v1.2用）

    Args:
        data: get_sleepの戻り値

    Returns:
        睡眠エントリのリスト（単日でも期間でも同じ形式）
    """
    if not data.get('sleep'):
        return []

    results = []
    for entry in data['sleep']:
        levels = entry.get('levels', {})
        summary = levels.get('summary', {})

        row = {
            # 基本情報
            'dateOfSleep': entry.get('dateOfSleep'),
            'startTime': entry.get('startTime'),
            'endTime': entry.get('endTime'),
            'duration': entry.get('duration'),
            'timeInBed': entry.get('timeInBed'),
            # 睡眠品質
            'efficiency': entry.get('efficiency'),
            'minutesAsleep': entry.get('minutesAsleep'),
            'minutesAwake': entry.get('minutesAwake'),
            'minutesAfterWakeup': entry.get('minutesAfterWakeup'),
            'minutesToFallAsleep': entry.get('minutesToFallAsleep'),
            # メタデータ
            'logId': entry.get('logId'),
            'logType': entry.get('logType'),
            'type': entry.get('type'),
            'infoCode': entry.get('infoCode'),
            'isMainSleep': entry.get('isMainSleep'),
            # 睡眠ステージ（分）
            'deepMinutes': summary.get('deep', {}).get('minutes'),
            'lightMinutes': summary.get('light', {}).get('minutes'),
            'remMinutes': summary.get('rem', {}).get('minutes'),
            'wakeMinutes': summary.get('wake', {}).get('minutes'),
            # 睡眠ステージ（回数）
            'deepCount': summary.get('deep', {}).get('count'),
            'lightCount': summary.get('light', {}).get('count'),
            'remCount': summary.get('rem', {}).get('count'),
            'wakeCount': summary.get('wake', {}).get('count'),
            # 30日平均
            'deepAvg30': summary.get('deep', {}).get('thirtyDayAvgMinutes'),
            'lightAvg30': summary.get('light', {}).get('thirtyDayAvgMinutes'),
            'remAvg30': summary.get('rem', {}).get('thirtyDayAvgMinutes'),
            'wakeAvg30': summary.get('wake', {}).get('thirtyDayAvgMinutes'),
        }
        results.append(row)

    return results


def parse_sleep_levels(data):
    """
    睡眠ステージの詳細データをリストに変換

    Args:
        data: get_sleep_log_by_dateまたはget_sleep_log_by_date_rangeの戻り値

    Returns:
        睡眠ステージの時系列データリスト
        各レコード: logId, dateOfSleep, dateTime, level, seconds
    """
    if not data.get('sleep'):
        return []

    results = []
    for entry in data['sleep']:
        log_id = entry.get('logId')
        date_of_sleep = entry.get('dateOfSleep')
        levels = entry.get('levels', {})

        # メインの睡眠ステージデータ
        for item in levels.get('data', []):
            results.append({
                'logId': log_id,
                'dateOfSleep': date_of_sleep,
                'dateTime': item.get('dateTime'),
                'level': item.get('level'),
                'seconds': item.get('seconds'),
                'isShort': False,
            })

        # 短い覚醒データ（3分以内）
        for item in levels.get('shortData', []):
            results.append({
                'logId': log_id,
                'dateOfSleep': date_of_sleep,
                'dateTime': item.get('dateTime'),
                'level': item.get('level'),
                'seconds': item.get('seconds'),
                'isShort': True,
            })

    return results


# =============================================================================
# Nutrition API
# https://dev.fitbit.com/build/reference/web-api/nutrition/
# =============================================================================

def get_food_log(client, date):
    """
    指定日の食事ログを取得
    https://dev.fitbit.com/build/reference/web-api/nutrition/get-food-log/
    """
    date_str = date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/foods/log/date/{date_str}.json"
    return client.make_request(url)


def search_foods(client, query):
    """
    食品を検索
    https://dev.fitbit.com/build/reference/web-api/nutrition/search-foods/
    """
    import urllib.parse
    encoded_query = urllib.parse.quote(query)
    url = f"{client.API_ENDPOINT}/1/user/-/foods/log/search.json?query={encoded_query}"
    return client.make_request(url)


def log_food(client, food_id, meal_type_id, unit_id, amount, date):
    """
    食品をログに記録
    https://dev.fitbit.com/build/reference/web-api/nutrition/create-food-log/
    """
    date_str = date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/foods/log.json"
    data = {
        'foodId': food_id,
        'mealTypeId': meal_type_id,
        'unitId': unit_id,
        'amount': amount,
        'date': date_str
    }
    return client.make_request(url, data=data, method='POST')


def delete_food_log(client, food_log_id):
    """
    食事ログを削除
    https://dev.fitbit.com/build/reference/web-api/nutrition/delete-food-log/
    """
    url = f"{client.API_ENDPOINT}/1/user/-/foods/log/{food_log_id}.json"
    return client.make_request(url, method='DELETE')


def edit_food_log(client, food_log_id, meal_type_id, unit_id, amount):
    """
    食事ログを編集
    https://dev.fitbit.com/build/reference/web-api/nutrition/update-food-log/
    """
    url = f"{client.API_ENDPOINT}/1/user/-/foods/log/{food_log_id}.json"
    data = {
        'mealTypeId': meal_type_id,
        'unitId': unit_id,
        'amount': amount
    }
    return client.make_request(url, data=data, method='POST')


def create_meal(client, name, description, meal_elements):
    """
    カスタム食事（Meal）を作成
    https://dev.fitbit.com/build/reference/web-api/nutrition/create-meal/
    """
    url = f"{client.API_ENDPOINT}/1/user/-/meals.json"
    # mealElements is a list of dicts: [{'foodId': ..., 'unitId': ..., 'amount': ...}, ...]
    # API expects parameters like mealElements[0][foodId]=...
    data = {
        'name': name,
        'description': description,
    }
    for i, element in enumerate(meal_elements):
        data[f'mealElements[{i}][foodId]'] = element['foodId']
        data[f'mealElements[{i}][unitId]'] = element['unitId']
        data[f'mealElements[{i}][amount]'] = element['amount']

    return client.make_request(url, data=data, method='POST')


def get_meals(client):
    """
    カスタム食事（Meal）のリストを取得
    https://dev.fitbit.com/build/reference/web-api/nutrition/get-meals/
    """
    url = f"{client.API_ENDPOINT}/1/user/-/meals.json"
    return client.make_request(url)


def edit_meal(client, meal_id, name, description, meal_elements):
    """
    カスタム食事（Meal）を編集
    https://dev.fitbit.com/build/reference/web-api/nutrition/update-meal/
    """
    url = f"{client.API_ENDPOINT}/1/user/-/meals/{meal_id}.json"
    data = {
        'name': name,
        'description': description,
    }
    for i, element in enumerate(meal_elements):
        data[f'mealElements[{i}][foodId]'] = element['foodId']
        data[f'mealElements[{i}][unitId]'] = element['unitId']
        data[f'mealElements[{i}][amount]'] = element['amount']

    return client.make_request(url, data=data, method='POST')


def delete_meal(client, meal_id):
    """
    カスタム食事（Meal）を削除
    https://dev.fitbit.com/build/reference/web-api/nutrition/delete-meal/
    """
    url = f"{client.API_ENDPOINT}/1/user/-/meals/{meal_id}.json"
    return client.make_request(url, method='DELETE')


def get_food_log_by_date_range(client, start_date, end_date):
    """
    期間指定で食事ログを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        dict: 各日付の食事ログデータの辞書

    Note:
        Nutrition APIには期間指定エンドポイントがないため、
        日付ごとにループして取得する
    """
    import datetime as dt

    current = start_date
    results = {}

    while current <= end_date:
        data = get_food_log(client, current)
        results[current.strftime('%Y-%m-%d')] = data
        current += dt.timedelta(days=1)

    return results


def parse_food_log(data):
    """
    食事ログの栄養サマリーをリストに変換

    Args:
        data: get_food_log_by_date_rangeの戻り値

    Returns:
        栄養サマリーのリスト（日別の栄養素合計）

    栄養素:
        - calories: カロリー
        - carbs: 炭水化物
        - fat: 脂質
        - fiber: 食物繊維
        - protein: タンパク質
        - sodium: ナトリウム
        - water: 水分
    """
    results = []

    for date_str, day_data in data.items():
        summary = day_data.get('summary', {})

        row = {
            'date': date_str,
            'calories': summary.get('calories'),
            'carbs': summary.get('carbs'),
            'fat': summary.get('fat'),
            'fiber': summary.get('fiber'),
            'protein': summary.get('protein'),
            'sodium': summary.get('sodium'),
            'water': summary.get('water'),
        }
        results.append(row)

    return results


# =============================================================================
# Activity API
# https://dev.fitbit.com/build/reference/web-api/activity/
# =============================================================================

def get_activity_log_list(client, before_date=None, after_date=None, sort='desc', limit=20):
    """
    アクティビティログのリストを取得

    Args:
        client: Fitbitクライアント
        before_date: この日付より前のログを取得（datetime.date）
        after_date: この日付より後のログを取得（datetime.date）
        sort: 'asc' or 'desc'（デフォルト: 'desc'）
        limit: 取得件数（最大100、デフォルト: 20）

    Returns:
        APIレスポンス（dict）: activities配列 + pagination

    Note:
        before_dateまたはafter_dateのどちらか一方が必須

    https://dev.fitbit.com/build/reference/web-api/activity/get-activity-log-list/
    """
    params = {
        'sort': sort,
        'limit': limit,
        'offset': 0,
    }

    if before_date:
        params['beforeDate'] = before_date.strftime('%Y-%m-%d')
    elif after_date:
        params['afterDate'] = after_date.strftime('%Y-%m-%d')
    else:
        raise ValueError("before_date or after_date is required")

    query = '&'.join(f"{k}={v}" for k, v in params.items())
    url = f"{client.API_ENDPOINT}/1/user/-/activities/list.json?{query}"
    return client.make_request(url)


def get_activity_tcx(client, log_id):
    """
    アクティビティのTCX（GPSデータ）を取得

    Args:
        client: Fitbitクライアント
        log_id: アクティビティログID

    Returns:
        TCX XML形式のデータ

    https://dev.fitbit.com/build/reference/web-api/activity/get-activity-tcx/
    """
    url = f"{client.API_ENDPOINT}/1/user/-/activities/{log_id}.tcx"
    return client.make_request(url)


def get_daily_activity_summary(client, date):
    """
    指定日のアクティビティサマリーを取得

    Args:
        client: Fitbitクライアント
        date: 日付（datetime.date）

    Returns:
        APIレスポンス（dict）: activities, goals, summary

    https://dev.fitbit.com/build/reference/web-api/activity/get-daily-activity-summary/
    """
    return get_by_date(client, 'activities', date, api_version='1')


def parse_activity_log(data):
    """
    アクティビティログをリストに変換

    Args:
        data: get_activity_log_listの戻り値

    Returns:
        アクティビティエントリのリスト
    """
    if not data.get('activities'):
        return []

    results = []
    for entry in data['activities']:
        row = {
            'logId': entry.get('logId'),
            'activityName': entry.get('activityName'),
            'activityTypeId': entry.get('activityTypeId'),
            'startTime': entry.get('startTime'),
            'originalStartTime': entry.get('originalStartTime'),
            'duration': entry.get('duration'),  # milliseconds
            'durationMinutes': entry.get('duration', 0) // 60000,  # minutes
            'calories': entry.get('calories'),
            'steps': entry.get('steps'),
            'distance': entry.get('distance'),
            'distanceUnit': entry.get('distanceUnit'),
            'logType': entry.get('logType'),  # auto_detected, manual, mobile_run, tracker
            'hasGps': entry.get('hasGps'),
            'hasStartTime': entry.get('hasStartTime'),
            # Heart rate zones
            'averageHeartRate': entry.get('averageHeartRate'),
            'heartRateZones': entry.get('heartRateZones'),
            # Active zone minutes
            'activeZoneMinutes': entry.get('activeZoneMinutes'),
        }
        results.append(row)

    return results


def get_activity_time_series_by_date_range(client, resource_path, start_date, end_date):
    """
    期間指定でアクティビティTime Seriesデータを取得

    Args:
        client: Fitbitクライアント
        resource_path: リソースパス（例: 'calories', 'steps', 'distance'）
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: activities-{resource} 配列

    Available resource_path:
        - calories: 総消費カロリー
        - caloriesBMR: 基礎代謝カロリー
        - activityCalories: アクティビティ消費カロリー
        - steps: 歩数
        - distance: 距離
        - floors: 階段
        - elevation: 標高
        - minutesSedentary: 座位時間
        - minutesLightlyActive: 軽い活動時間
        - minutesFairlyActive: やや活発時間
        - minutesVeryActive: とても活発時間

    https://dev.fitbit.com/build/reference/web-api/activity-timeseries/get-activity-timeseries-by-date-range/
    """
    return get_by_date_range(client, f'activities/tracker/{resource_path}', start_date, end_date, api_version='1')


def get_activity_summary_by_date_range(client, start_date, end_date):
    """
    期間指定で主要なアクティビティデータをまとめて取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        pandas.DataFrame: 日別のアクティビティデータ

    Note:
        Daily Activity Summary APIを日付ごとに呼び出す
        Time Series APIより効率的（1日1リクエスト vs 8リソース×1リクエスト）
    """
    import pandas as pd
    import datetime as dt

    current = start_date
    results = []

    while current <= end_date:
        data = get_daily_activity_summary(client, current)
        summary = data.get('summary', {})

        # 距離の合計を計算（distances配列から）
        total_distance = 0.0
        distances = summary.get('distances', [])
        for dist in distances:
            if dist.get('activity') == 'total':
                total_distance = float(dist.get('distance', 0))
                break

        row = {
            'date': current.strftime('%Y-%m-%d'),
            'caloriesOut': float(summary.get('caloriesOut', 0)),
            'activityCalories': float(summary.get('activityCalories', 0)),
            'steps': float(summary.get('steps', 0)),
            'distance': total_distance,
            'sedentaryMinutes': float(summary.get('sedentaryMinutes', 0)),
            'lightlyActiveMinutes': float(summary.get('lightlyActiveMinutes', 0)),
            'fairlyActiveMinutes': float(summary.get('fairlyActiveMinutes', 0)),
            'veryActiveMinutes': float(summary.get('veryActiveMinutes', 0)),
        }
        results.append(row)
        current += dt.timedelta(days=1)

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    return df


# Activity Type IDs
ACTIVITY_TYPE_MEDITATING = 7075


def get_meditation_logs(client, before_date=None, after_date=None, limit=100):
    """
    瞑想アクティビティのみ取得

    Args:
        client: Fitbitクライアント
        before_date: この日付より前のログを取得（datetime.date）
        after_date: この日付より後のログを取得（datetime.date）
        limit: 取得件数（最大100、デフォルト: 100）

    Returns:
        瞑想アクティビティのリスト

    Note:
        Fitbit APIはactivityTypeでフィルタできないため、
        取得後にクライアント側でフィルタリング
    """
    data = get_activity_log_list(client, before_date, after_date, limit=limit)
    activities = parse_activity_log(data)
    return [act for act in activities if act['activityTypeId'] == ACTIVITY_TYPE_MEDITATING]


def get_activity_logs_by_date_range(client, start_date, end_date):
    """
    期間指定で全アクティビティログを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        pandas.DataFrame: 個別アクティビティログのデータ

    Note:
        Activity Logs APIはページング方式のため、
        期間内の全ログを取得するまでループする
    """
    import pandas as pd
    import datetime as dt

    all_activities = []
    before_date = end_date + dt.timedelta(days=1)  # 終了日を含めるため+1

    # ページングで全件取得
    while True:
        data = get_activity_log_list(client, before_date=before_date, limit=100)
        activities = parse_activity_log(data)

        if not activities:
            break

        # 期間内のログのみ追加
        for act in activities:
            act_date = pd.to_datetime(act['startTime']).date()
            if act_date < start_date:
                # 開始日より前のログに到達したら終了
                break
            if start_date <= act_date <= end_date:
                all_activities.append(act)

        # 次のページがあるかチェック
        pagination = data.get('pagination', {})
        if not pagination.get('next'):
            break

        # 最後のアクティビティの日付を次のbefore_dateにセット
        if activities:
            last_date = pd.to_datetime(activities[-1]['startTime']).date()
            if last_date < start_date:
                break
            before_date = last_date

    if not all_activities:
        return pd.DataFrame()

    df = pd.DataFrame(all_activities)
    return df


# =============================================================================
# Active Zone Minutes API
# https://dev.fitbit.com/build/reference/web-api/active-zone-minutes-timeseries/
# =============================================================================

def get_active_zone_minutes_by_date_range(client, start_date, end_date):
    """
    期間指定でActive Zone Minutes（アクティブゾーン分数）を取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: activities-active-zone-minutes配列

    Note:
        最大1,095日間（約3年）まで一括取得可能
        心拍数ベースのアクティビティ強度を測定

    Endpoint: /1/user/-/activities/active-zone-minutes/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/active-zone-minutes-timeseries/get-azm-timeseries-by-interval/
    """
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/activities/active-zone-minutes/date/{start_str}/{end_str}.json"
    return client.make_request(url)


def parse_active_zone_minutes(data):
    """
    Active Zone Minutesデータをリストに変換

    Args:
        data: get_active_zone_minutes_by_date_rangeの戻り値

    Returns:
        Active Zone Minutesエントリのリスト

    データ構造:
        - dateTime: 日付
        - activeZoneMinutes: 総アクティブゾーン分数
        - fatBurnActiveZoneMinutes: 脂肪燃焼ゾーン（1分=1AZM）
        - cardioActiveZoneMinutes: 有酸素運動ゾーン（1分=2AZM）
        - peakActiveZoneMinutes: ピークゾーン（1分=2AZM）
    """
    if not data.get('activities-active-zone-minutes'):
        return []

    results = []
    for entry in data['activities-active-zone-minutes']:
        value = entry.get('value', {})
        row = {
            'date': entry.get('dateTime'),
            'activeZoneMinutes': value.get('activeZoneMinutes'),
            'fatBurnActiveZoneMinutes': value.get('fatBurnActiveZoneMinutes'),
            'cardioActiveZoneMinutes': value.get('cardioActiveZoneMinutes'),
            'peakActiveZoneMinutes': value.get('peakActiveZoneMinutes'),
        }
        results.append(row)

    return results


# =============================================================================
# HRV (Heart Rate Variability) API
# https://dev.fitbit.com/build/reference/web-api/heartrate-variability/
# =============================================================================

def get_hrv_by_date(client, date):
    """
    指定日のHRV（心拍変動）データを取得

    Args:
        client: Fitbitクライアント
        date: 日付（datetime.date）

    Returns:
        APIレスポンス（dict）: hrv配列

    Endpoint: /1/user/-/hrv/date/{date}.json
    https://dev.fitbit.com/build/reference/web-api/heartrate-variability/get-hrv-by-date/
    """
    return get_by_date(client, 'hrv', date, api_version='1')


def get_hrv_by_date_range(client, start_date, end_date):
    """
    期間指定でHRV（心拍変動）データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: hrv配列

    Note:
        最大30日間まで一括取得可能

    Endpoint: /1/user/-/hrv/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/heartrate-variability/get-hrv-by-date-range/
    """
    return get_by_date_range(client, 'hrv', start_date, end_date, api_version='1')


def parse_hrv(data):
    """
    HRVデータをリストに変換

    Args:
        data: get_hrv_by_dateまたはget_hrv_by_date_rangeの戻り値

    Returns:
        HRVエントリのリスト

    HRVデータ構造:
        - dateTime: 日付
        - value.dailyRmssd: 日次RMSSD（Root Mean Square of Successive Differences）
        - value.deepRmssd: 深い睡眠中のRMSSD
    """
    if not data.get('hrv'):
        return []

    results = []
    for entry in data['hrv']:
        value = entry.get('value', {})
        row = {
            'date': entry.get('dateTime'),
            'daily_rmssd': value.get('dailyRmssd'),
            'deep_rmssd': value.get('deepRmssd'),
        }
        results.append(row)

    return results


# =============================================================================
# Heart Rate API
# https://dev.fitbit.com/build/reference/web-api/heartrate-timeseries/
# =============================================================================

def get_heart_rate_by_date_range(client, start_date, end_date):
    """
    期間指定で心拍数データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: activities-heart配列

    Note:
        最大30日間まで一括取得可能
        安静時心拍数（restingHeartRate）が含まれる

    Endpoint: /1/user/-/activities/heart/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/heartrate-timeseries/get-heartrate-timeseries-by-date-range/
    """
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/activities/heart/date/{start_str}/{end_str}.json"
    return client.make_request(url)


def parse_heart_rate(data):
    """
    心拍数データをリストに変換

    Args:
        data: get_heart_rate_by_date_rangeの戻り値

    Returns:
        心拍数エントリのリスト

    データ構造:
        - dateTime: 日付
        - value.restingHeartRate: 安静時心拍数（RHR）
    """
    if not data.get('activities-heart'):
        return []

    results = []
    for entry in data['activities-heart']:
        value = entry.get('value', {})
        row = {
            'date': entry.get('dateTime'),
            'resting_heart_rate': value.get('restingHeartRate'),
        }
        results.append(row)

    return results


# =============================================================================
# Breathing Rate API
# https://dev.fitbit.com/build/reference/web-api/breathing-rate/
# =============================================================================

def get_breathing_rate_by_date_range(client, start_date, end_date):
    """
    期間指定で呼吸数データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: br配列

    Note:
        最大30日間まで一括取得可能
        睡眠中の平均呼吸数を返す

    Endpoint: /1/user/-/br/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/breathing-rate/get-br-summary-by-interval/
    """
    return get_by_date_range(client, 'br', start_date, end_date, api_version='1')


def parse_breathing_rate(data):
    """
    呼吸数データをリストに変換

    Args:
        data: get_breathing_rate_by_date_rangeの戻り値

    Returns:
        呼吸数エントリのリスト

    データ構造:
        - dateTime: 日付
        - value.breathingRate: 平均呼吸数（回/分）
    """
    if not data.get('br'):
        return []

    results = []
    for entry in data['br']:
        value = entry.get('value', {})
        row = {
            'date': entry.get('dateTime'),
            'breathing_rate': value.get('breathingRate'),
        }
        results.append(row)

    return results


# =============================================================================
# SpO2 (Oxygen Saturation) API
# https://dev.fitbit.com/build/reference/web-api/spo2/
# =============================================================================

def get_spo2_by_date_range(client, start_date, end_date):
    """
    期間指定でSpO2（血中酸素濃度）データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（list）: SpO2データの配列

    Note:
        最大30日間まで一括取得可能
        睡眠中の血中酸素濃度を返す

    Endpoint: /1/user/-/spo2/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/spo2/get-spo2-summary-by-interval/
    """
    return get_by_date_range(client, 'spo2', start_date, end_date, api_version='1')


def parse_spo2(data):
    """
    SpO2データをリストに変換

    Args:
        data: get_spo2_by_date_rangeの戻り値

    Returns:
        SpO2エントリのリスト

    データ構造:
        - dateTime: 日付
        - value.avg: 平均SpO2（%）
        - value.min: 最小SpO2（%）
        - value.max: 最大SpO2（%）
    """
    # SpO2 APIはリストを直接返す場合がある
    entries = data if isinstance(data, list) else data.get('spo2', [])

    if not entries:
        return []

    results = []
    for entry in entries:
        value = entry.get('value', {})
        row = {
            'date': entry.get('dateTime'),
            'avg_spo2': value.get('avg'),
            'min_spo2': value.get('min'),
            'max_spo2': value.get('max'),
        }
        results.append(row)

    return results


# =============================================================================
# Temperature API
# https://dev.fitbit.com/build/reference/web-api/temperature/
# =============================================================================

def get_temperature_skin_by_date_range(client, start_date, end_date):
    """
    期間指定で皮膚温データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: tempSkin配列

    Note:
        最大30日間まで一括取得可能
        睡眠中（最も長い睡眠期間）の皮膚温を返す

    Endpoint: /1/user/-/temp/skin/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/temperature/get-temperature-skin-summary-by-interval/
    """
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/temp/skin/date/{start_str}/{end_str}.json"
    return client.make_request(url)


def get_temperature_core_by_date_range(client, start_date, end_date, api_version='1'):
    """
    期間指定で体温データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）
        api_version: APIバージョン（'1' または '1.2'、デフォルト: '1'）

    Returns:
        APIレスポンス（dict）: tempCore配列

    Note:
        最大30日間まで一括取得可能
        ユーザーが手動で記録した体温データ

        API version 1.0 と 1.2 の両方をサポート

    Endpoint: /{api_version}/user/-/temp/core/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/temperature/get-temperature-core-summary-by-interval/
    """
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/{api_version}/user/-/temp/core/date/{start_str}/{end_str}.json"
    return client.make_request(url)


def parse_temperature_skin(data):
    """
    皮膚温データをリストに変換

    Args:
        data: get_temperature_skin_by_date_rangeの戻り値

    Returns:
        皮膚温エントリのリスト

    データ構造:
        - dateTime: 日付
        - value.nightlyRelative: 基礎体温からの差分（°C）
        - logType: センサータイプ（dedicated_temp_sensor / other_sensors）
    """
    if not data.get('tempSkin'):
        return []

    results = []
    for entry in data['tempSkin']:
        value = entry.get('value', {})
        row = {
            'date': entry.get('dateTime'),
            'nightly_relative': value.get('nightlyRelative'),
            'log_type': entry.get('logType'),
        }
        results.append(row)

    return results


def parse_temperature_core(data):
    """
    体温データをリストに変換

    Args:
        data: get_temperature_core_by_date_rangeの戻り値

    Returns:
        体温エントリのリスト

    データ構造:
        - dateTime: 日付時刻
        - value: 体温（°C または °F）
    """
    if not data.get('tempCore'):
        return []

    results = []
    for entry in data['tempCore']:
        row = {
            'date_time': entry.get('dateTime'),
            'temperature': entry.get('value'),
        }
        results.append(row)

    return results


# =============================================================================
# Intraday Time Series API
# https://dev.fitbit.com/build/reference/web-api/intraday/
# =============================================================================

def get_heart_rate_intraday(client, date, detail_level='1min'):
    """
    指定日の心拍数Intradayデータを取得

    Args:
        client: Fitbitクライアント
        date: 日付（datetime.date）
        detail_level: 粒度（'1sec', '1min', '5min', '15min'）

    Returns:
        APIレスポンス（dict）

    Note:
        Personal用途では自動的に利用可能
        1日分のみ取得可能（複数日は日付ごとにループ）

    Endpoint: /1/user/-/activities/heart/date/{date}/1d/{detail-level}.json
    https://dev.fitbit.com/build/reference/web-api/intraday/get-heartrate-intraday-by-date/
    """
    date_str = date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/activities/heart/date/{date_str}/1d/{detail_level}.json"
    return client.make_request(url)


def get_steps_intraday(client, date, detail_level='1min'):
    """
    指定日の歩数Intradayデータを取得

    Args:
        client: Fitbitクライアント
        date: 日付（datetime.date）
        detail_level: 粒度（'1min', '5min', '15min'）

    Returns:
        APIレスポンス（dict）

    Note:
        Personal用途では自動的に利用可能
        1日分のみ取得可能（複数日は日付ごとにループ）

    Endpoint: /1/user/-/activities/steps/date/{date}/1d/{detail-level}.json
    https://dev.fitbit.com/build/reference/web-api/intraday/get-steps-intraday-by-date/
    """
    date_str = date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1/user/-/activities/steps/date/{date_str}/1d/{detail_level}.json"
    return client.make_request(url)


def parse_heart_rate_intraday(data, date):
    """
    Heart Rate Intradayデータをリストに変換

    Args:
        data: get_heart_rate_intradayの戻り値
        date: 日付（datetime.date）

    Returns:
        心拍数Intradayエントリのリスト

    データ構造:
        - datetime: タイムスタンプ（日付+時刻）
        - heart_rate: 心拍数（bpm）
    """
    intraday_data = data.get('activities-heart-intraday', {}).get('dataset', [])
    if not intraday_data:
        return []

    results = []
    date_str = date.strftime('%Y-%m-%d')

    for entry in intraday_data:
        time_str = entry.get('time')
        value = entry.get('value')

        if time_str and value is not None:
            results.append({
                'datetime': f"{date_str} {time_str}",
                'heart_rate': value,
            })

    return results


def parse_steps_intraday(data, date):
    """
    Steps Intradayデータをリストに変換

    Args:
        data: get_steps_intradayの戻り値
        date: 日付（datetime.date）

    Returns:
        歩数Intradayエントリのリスト

    データ構造:
        - datetime: タイムスタンプ（日付+時刻）
        - steps: 歩数
    """
    intraday_data = data.get('activities-steps-intraday', {}).get('dataset', [])
    if not intraday_data:
        return []

    results = []
    date_str = date.strftime('%Y-%m-%d')

    for entry in intraday_data:
        time_str = entry.get('time')
        value = entry.get('value')

        if time_str and value is not None:
            results.append({
                'datetime': f"{date_str} {time_str}",
                'steps': value,
            })

    return results


def get_heart_rate_intraday_by_date_range(client, start_date, end_date, detail_level='1min'):
    """
    期間指定で心拍数Intradayデータを取得（日付ごとにループ）

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）
        detail_level: 粒度（'1sec', '1min', '5min', '15min'）

    Returns:
        pandas.DataFrame: 心拍数Intradayデータ

    Note:
        Intraday APIは1日分ずつしか取得できないため、
        日付ごとにループして取得する
        N日間 = Nリクエスト
    """
    import datetime as dt
    import pandas as pd

    current = start_date
    all_records = []

    while current <= end_date:
        data = get_heart_rate_intraday(client, current, detail_level)
        records = parse_heart_rate_intraday(data, current)
        all_records.extend(records)
        current += dt.timedelta(days=1)

    if not all_records:
        return pd.DataFrame()

    return pd.DataFrame(all_records)


def get_steps_intraday_by_date_range(client, start_date, end_date, detail_level='1min'):
    """
    期間指定で歩数Intradayデータを取得（日付ごとにループ）

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）
        detail_level: 粒度（'1min', '5min', '15min'）

    Returns:
        pandas.DataFrame: 歩数Intradayデータ

    Note:
        Intraday APIは1日分ずつしか取得できないため、
        日付ごとにループして取得する
        N日間 = Nリクエスト
    """
    import datetime as dt
    import pandas as pd

    current = start_date
    all_records = []

    while current <= end_date:
        data = get_steps_intraday(client, current, detail_level)
        records = parse_steps_intraday(data, current)
        all_records.extend(records)
        current += dt.timedelta(days=1)

    if not all_records:
        return pd.DataFrame()

    return pd.DataFrame(all_records)


# =============================================================================
# Cardio Fitness Score (VO2 Max) API
# https://dev.fitbit.com/build/reference/web-api/cardio-fitness-score/
# =============================================================================

def get_cardio_score_by_date_range(client, start_date, end_date):
    """
    期間指定で心肺スコア（VO2 Max）データを取得

    Args:
        client: Fitbitクライアント
        start_date: 開始日（datetime.date）
        end_date: 終了日（datetime.date）

    Returns:
        APIレスポンス（dict）: cardioScore配列

    Note:
        最大30日間まで一括取得可能
        VO2 Maxの推定値を返す

    Endpoint: /1/user/-/cardioscore/date/{startDate}/{endDate}.json
    https://dev.fitbit.com/build/reference/web-api/cardio-fitness-score/get-vo2max-summary-by-interval/
    """
    return get_by_date_range(client, 'cardioscore', start_date, end_date, api_version='1')


def parse_cardio_score(data):
    """
    心肺スコアデータをリストに変換

    Args:
        data: get_cardio_score_by_date_rangeの戻り値

    Returns:
        心肺スコアエントリのリスト

    データ構造:
        - dateTime: 日付
        - value.vo2Max: VO2 Max推定値（ml/kg/min）
            GPS使用時: "45" (単一数値)
            GPS未使用時: "44-48" (範囲形式)
    """
    if not data.get('cardioScore'):
        return []

    def parse_vo2_max(vo2_str):
        """
        VO2 Max文字列を数値に変換

        Args:
            vo2_str: "45" または "44-48" 形式の文字列

        Returns:
            float: 数値または範囲の中央値
        """
        if not vo2_str:
            return None

        if '-' in vo2_str:
            # 範囲形式: 中央値を計算
            parts = vo2_str.split('-')
            try:
                min_val = float(parts[0])
                max_val = float(parts[1])
                return (min_val + max_val) / 2
            except (ValueError, IndexError):
                return None
        else:
            # 単一数値
            try:
                return float(vo2_str)
            except ValueError:
                return None

    results = []
    for entry in data['cardioScore']:
        value = entry.get('value', {})
        vo2_raw = value.get('vo2Max')
        row = {
            'date': entry.get('dateTime'),
            'vo2_max': parse_vo2_max(vo2_raw),
            'vo2_max_raw': vo2_raw,  # 元の文字列も保存
        }
        results.append(row)

    return results
