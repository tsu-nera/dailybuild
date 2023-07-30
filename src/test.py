#!/usr/bin/env python3

import fitbit
import datetime
from oauthlib.oauth2 import LegacyApplicationClient
from requests_oauthlib import OAuth2Session


# OAuth2セッションを作成
auth = OAuth2Session(client_id, token={
    'access_token': access_token,
    'refresh_token': refresh_token,
    'token_type': 'Bearer',
    'expires_in': '-30',
    'expires_at': '-30'
}, client=LegacyApplicationClient(client_id))

# Fitbitクライアントを作成
client = fitbit.Fitbit(client_id,
                       client_secret,
                       oauth2=True,
                       access_token=access_token,
                       refresh_token=refresh_token,
                       system='en_GB')

# 睡眠データを取得
start_date = datetime.date(2023, 7, 30)
end_date = start_date + datetime.timedelta(days=7)
sleep = client.get_sleep(date=start_date)

# 睡眠データを表示
print(sleep)
