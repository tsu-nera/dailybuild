#!/usr/bin/env python
# coding: utf-8
"""
HealthPlanet 公式 OAuth API
注意: 現在は体重と体脂肪率のみ取得可能
"""

import json
import webbrowser
import requests

BASE_URL = "https://www.healthplanet.jp"
AUTH_URL = f"{BASE_URL}/oauth/auth"
TOKEN_URL = f"{BASE_URL}/oauth/token"
INNERSCAN_URL = f"{BASE_URL}/status/innerscan.json"

# 取得するデータタグ（体組成計）
# 6021: 体重, 6022: 体脂肪率, 6023: 筋肉量, 6024: 筋肉スコア
# 6025: 内臓脂肪レベル2, 6026: 内臓脂肪レベル, 6027: 基礎代謝量
# 6028: 体内年齢, 6029: 推定骨量, 6030: 体水分率, 6031: BMI
INNERSCAN_TAGS = "6021,6022,6023,6024,6025,6026,6027,6028,6029,6030,6031"

TAG_NAMES = {
    '6021': 'weight',
    '6022': 'body_fat_rate',
    '6023': 'muscle_mass',
    '6024': 'muscle_score',
    '6025': 'visceral_fat_level2',
    '6026': 'visceral_fat_level',
    '6027': 'basal_metabolic_rate',
    '6028': 'body_age',
    '6029': 'bone_mass',
    '6030': 'body_water_rate',
    '6031': 'bmi'
}


def get_auth_code(client_id, redirect_uri, scope="innerscan"):
    """ブラウザで認証してauthorization codeを取得（手動入力）"""
    from urllib.parse import urlencode

    auth_params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': scope,
        'response_type': 'code'
    }

    auth_url = f"{AUTH_URL}?" + urlencode(auth_params)
    print(f"以下のURLをブラウザで開いて認証してください:")
    print(auth_url)
    print()
    webbrowser.open(auth_url)

    print("認証後、リダイレクトされたURLの'code='以降の値を入力してください:")
    auth_code = input("code: ").strip()

    return auth_code if auth_code else None


def get_access_token(client_id, client_secret, redirect_uri, auth_code):
    """authorization codeからaccess tokenを取得"""
    token_params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'code': auth_code,
        'grant_type': 'authorization_code'
    }

    response = requests.post(TOKEN_URL, data=token_params)
    response.raise_for_status()
    return response.json()


def refresh_token(client_id, client_secret, redirect_uri, refresh_token_str):
    """リフレッシュトークンでアクセストークンを更新"""
    refresh_params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'refresh_token': refresh_token_str,
        'grant_type': 'refresh_token'
    }

    response = requests.post(TOKEN_URL, data=refresh_params)
    if response.status_code == 200:
        return response.json()
    return None


def get_innerscan_data(access_token, from_date=None, to_date=None):
    """体組成計データを取得"""
    params = {
        'access_token': access_token,
        'date': '1',
        'tag': INNERSCAN_TAGS
    }

    if from_date:
        params['from'] = from_date.strftime('%Y%m%d%H%M%S')
    if to_date:
        params['to'] = to_date.strftime('%Y%m%d%H%M%S')

    response = requests.get(INNERSCAN_URL, params=params)
    response.raise_for_status()
    return response.json()


def parse_innerscan_data(data):
    """APIレスポンスをレコードリストに変換"""
    records = {}
    for item in data.get('data', []):
        date = item['date']
        tag = item['tag']
        keydata = item['keydata']

        if date not in records:
            records[date] = {'date': date}

        tag_name = TAG_NAMES.get(tag, f'tag_{tag}')
        records[date][tag_name] = float(keydata)

    return list(records.values())
