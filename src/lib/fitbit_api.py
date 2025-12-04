#!/usr/bin/env python
# coding: utf-8
"""
Fitbit API クライアント

python-fitbitライブラリはOAuth認証のみに使用。
APIコールはv1.2エンドポイントを直接呼び出す。
"""

import json
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
    date_str = date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1.2/user/-/sleep/date/{date_str}.json"
    return client.make_request(url)


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
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    url = f"{client.API_ENDPOINT}/1.2/user/-/sleep/date/{start_str}/{end_str}.json"
    return client.make_request(url)


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
