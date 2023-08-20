#!/usr/bin/env python
# coding: utf-8

import fitbit
import json
import datetime as dt
from oauthlib.oauth2 import LegacyApplicationClient
from requests_oauthlib import OAuth2Session

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

CREDS_FILE = '../config/fitbit_creds.json'
TOKEN_FILE = '../config/fitbit_token.json'

OUT_FILE = "../data/sleep_master.csv"

# tokenファイルを上書きする関数
def update_token(token):
    f = open(TOKEN_FILE, 'w')
    f.write(str(token))
    f.close()
    return

# トークン情報をファイルから読み込む
with open(TOKEN_FILE, 'r') as f:
    token_data = json.load(f)

with open(CREDS_FILE, 'r') as f:
    creds = json.load(f)

# Fitbitクライアントを作成
client = fitbit.Fitbit(creds['client_id'],
                       creds['client_secret'],
                       oauth2=True,
                       access_token=token_data['access_token'],
                       refresh_token=token_data['refresh_token'],
                       refresh_cb=update_token)

def json_to_row(data):    
    sleep = data['sleep'][0]
    summary = data['summary']
    stages = summary['stages']
    
    sleep.pop('minuteData')
    summary.pop('stages')
    
    return {**sleep, 
            **summary,
            "deepStage": stages['deep'],
            "lightStage": stages['light'],
            "remStage": stages['rem'],
            "wakeStage": stages['wake']}


# 現在の日付から一ヶ月前の日付を取得
end_date = dt.date.today()
start_date = end_date - dt.timedelta(days=14)

# 一ヶ月分の睡眠データを取得
sleep_data = []
current_date = start_date
while current_date <= end_date:
    sleep_log = client.sleep(date=current_date)
    sleep_data.append(json_to_row(sleep_log))
    current_date += dt.timedelta(days=1)

df = pd.DataFrame(sleep_data)
df['dateOfSleep'] = pd.to_datetime(df['dateOfSleep'])

# 'date'カラムをインデックスとして設定
df.set_index('dateOfSleep', inplace=True)

df.to_csv(OUT_FILE)

