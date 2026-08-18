#!/usr/bin/env python
# coding: utf-8
"""
HealthPlanet 非公式 graph.json API
参考: https://pc.atsuhiro-me.net/entry/2023/07/22/195837

注意: 非公式な方法のため、将来使えなくなる可能性あり
"""

import re

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

# 血圧計のkind番号
# kind=10 は他のkindと違い value1=収縮期 / value_ext=拡張期 のペアで返る
BP_KIND_PRESSURE = 10
BP_KIND_PULSE = 11

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
    """Webログインセッションを作成

    login.do のフォームは Struts の CSRF トークン
    (org.apache.struts.taglib.html.TOKEN) を要求する。
    ログインページから毎回スクレイプして同じ POST に載せる。
    """
    session = requests.Session()

    resp = session.get(f"{BASE_URL}/login.do")
    resp.raise_for_status()
    html = resp.content.decode('shift_jis', errors='replace')

    match = re.search(
        r'name="org\.apache\.struts\.taglib\.html\.TOKEN"\s+value="([^"]+)"',
        html,
    )
    if not match:
        raise RuntimeError("ログインページからCSRFトークンを取得できません（フォーム仕様変更の可能性）")

    login_data = {
        'org.apache.struts.taglib.html.TOKEN': match.group(1),
        'loginId': login_id,
        'passwd': password,
        'send': '1',
        'url': '',
        'auto': 'on',
    }

    response = session.post(f"{BASE_URL}/login.do", data=login_data)
    response.raise_for_status()

    # 失敗時はログイン画面が返るだけで 200 になるため、内容で判定する
    body = response.content.decode('shift_jis', errors='replace')
    if 'loginId' in body:
        raise RuntimeError("HealthPlanetのログインに失敗しました（認証情報またはフォーム仕様を確認）")

    return session


def get_innerscan_data(session, days=60, kinds=None):
    """体組成計データを取得

    Args:
        session: ログイン済みセッション
        days: 取得日数。graph.json は値によって粒度が変わる。
            14/30/60/120 は実測日そのままの日次だが、90 は日付がずれる
            バケット集約、365 は月次平均になるため使わないこと

        kinds: 取得するkind番号の辞書 {kind: col_name}。Noneの場合はINNERSCAN_KINDS

    Returns:
        dict: {date_str: {col_name: value, ...}, ...}
    """
    if kinds is None:
        kinds = INNERSCAN_KINDS

    records = defaultdict(dict)

    for kind, col_name in kinds.items():
        data = _fetch_kind(session, kind, days)
        if data is None:
            continue

        for date_str, value in _series(data, 'value1'):
            records[date_str][col_name] = value

    return dict(records)


def _series(data, key):
    """graph.json のデータ系列を (日付, 値) のリストで返す

    値が無い系列は null そのものだけでなく [null] のように
    None 要素を含むリストで返ることがあるため、両方を潰す。
    """
    return [pair for pair in (data.get(key) or []) if pair]


def _fetch_kind(session, kind, days):
    """graph.json を1 kind分取得。データが無い場合は None"""
    response = session.get(GRAPH_URL, params={'day': days, 'page': 1, 'kind': kind})
    response.raise_for_status()

    data = response.json()
    if data.get('code', [-1])[0] != 0:
        return None
    return data


def get_blood_pressure_data(session, days=60):
    """血圧計データ（収縮期・拡張期・脈拍）を取得

    kind=10 は value1 に収縮期、value_ext に拡張期が入るペア構造で返るため、
    value1 しか見ない get_innerscan_data では拡張期を取りこぼす。

    Args:
        session: ログイン済みセッション
        days: 取得日数（get_innerscan_data と同じ粒度の制約がある）

    Returns:
        dict: {date_str: {'bp_systolic': .., 'bp_diastolic': .., 'bp_pulse': ..}, ...}
    """
    records = defaultdict(dict)

    pressure = _fetch_kind(session, BP_KIND_PRESSURE, days)
    if pressure is not None:
        for date_str, value in _series(pressure, 'value1'):
            records[date_str]['bp_systolic'] = value
        for date_str, value in _series(pressure, 'value_ext'):
            records[date_str]['bp_diastolic'] = value

    pulse = _fetch_kind(session, BP_KIND_PULSE, days)
    if pulse is not None:
        for date_str, value in _series(pulse, 'value1'):
            records[date_str]['bp_pulse'] = value

    return dict(records)
