#!/usr/bin/env python
# coding: utf-8
"""
HealthPlanet 非公式 graph.json API
参考: https://pc.atsuhiro-me.net/entry/2023/07/22/195837

注意: 非公式な方法のため、将来使えなくなる可能性あり
"""

import requests
from collections import defaultdict

BASE_URL = "https://www.healthplanet.jp"
GRAPH_URL = f"{BASE_URL}/graph/graph.json"

# graph.json APIのkind番号と列名のマッピング（体組成計）
INNERSCAN_KINDS = {
    1: 'weight',
    2: 'body_fat_rate',
    3: 'body_fat_mass',
    4: 'visceral_fat_level',
    5: 'basal_metabolic_rate',
    6: 'muscle_mass',
    7: 'bone_mass',
    14: 'body_age',
    22: 'body_water_rate',
    23: 'muscle_quality_score',
}

# 全てのkind番号（参考用）
ALL_KINDS = {
    1: ('体組成計 - 体重', 'kg'),
    2: ('体組成計 - 体脂肪率', '%'),
    3: ('体組成計 - 体脂肪量', 'kg'),
    4: ('体組成計 - 内臓脂肪レベル', ''),
    5: ('体組成計 - 基礎代謝量', 'kcal'),
    6: ('体組成計 - 筋肉量', 'kg'),
    7: ('体組成計 - 推定骨量', 'kg'),
    8: ('歩数計 - 歩数', '歩'),
    9: ('歩数計 - 総消費カロリー', 'kcal'),
    10: ('血圧計 - 血圧', 'mmHg'),
    11: ('血圧計 - 脈拍', '拍/分'),
    13: ('その他 - ウエスト', 'cm'),
    14: ('体組成計 - 体内年齢', '才'),
    15: ('血糖計 - 血糖', 'mg/dL'),
    16: ('尿糖計 - 尿糖', 'mg/dL'),
    17: ('歩数計 - 歩行時間', '分'),
    18: ('歩数計 - 活動消費カロリー', 'kcal'),
    20: ('歩数計 - 自転車活動カロリー', 'kcal'),
    21: ('歩数計 - 自転車時間', '分'),
    22: ('体組成計 - 体水分率', '%'),
    23: ('体組成計 - 筋質点数（全身）', ''),
    24: ('体組成計 - 筋質点数（左腕）', ''),
    25: ('体組成計 - 筋質点数（右腕）', ''),
    26: ('体組成計 - 筋質点数（左足）', ''),
    27: ('体組成計 - 筋質点数（右足）', ''),
    28: ('体組成計 - アスリート指数', ''),
}


def create_login_session(login_id, password):
    """Webログインセッションを作成"""
    session = requests.Session()
    session.get(f"{BASE_URL}/login.do")

    login_data = {
        'loginId': login_id,
        'passwd': password,
        'send': '1'
    }

    response = session.post(f"{BASE_URL}/login_oauth.do", data=login_data)
    response.raise_for_status()
    return session


def get_innerscan_data(session, days=90, kinds=None):
    """体組成計データを取得

    Args:
        session: ログイン済みセッション
        days: 取得日数
        kinds: 取得するkind番号の辞書 {kind: col_name}。Noneの場合はINNERSCAN_KINDS

    Returns:
        dict: {date_str: {col_name: value, ...}, ...}
    """
    if kinds is None:
        kinds = INNERSCAN_KINDS

    records = defaultdict(dict)

    for kind, col_name in kinds.items():
        params = {'day': days, 'page': 1, 'kind': kind}
        response = session.get(GRAPH_URL, params=params)
        response.raise_for_status()

        data = response.json()
        if data.get('code', [-1])[0] != 0:
            continue

        for date_str, value in data.get('value1', []):
            records[date_str][col_name] = value

    return dict(records)
