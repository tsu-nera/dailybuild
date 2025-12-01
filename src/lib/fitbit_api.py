#!/usr/bin/env python
# coding: utf-8
"""
Fitbit API クライアント
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
    """Fitbitクライアントを作成"""
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


def parse_sleep_log(data):
    """睡眠ログをフラットな辞書に変換"""
    if not data.get('sleep'):
        return None

    sleep = data['sleep'][0].copy()
    summary = data['summary'].copy()
    stages = summary.get('stages', {})

    sleep.pop('minuteData', None)
    sleep.pop('levels', None)
    summary.pop('stages', None)

    return {
        **sleep,
        **summary,
        'deepStage': stages.get('deep'),
        'lightStage': stages.get('light'),
        'remStage': stages.get('rem'),
        'wakeStage': stages.get('wake'),
    }
