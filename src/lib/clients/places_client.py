"""Places API (New) Place Details クライアント

place ID から正式名と主タイプを1件引く。認証は API キー（呼び出し側が渡す）。
"""

import requests

PLACES_URL = 'https://places.googleapis.com/v1/places/{place_id}'

# 課金の SKU はフィールドで決まる。増やさない
FIELD_MASK = 'id,displayName,primaryType'


class PlaceNotFound(Exception):
    """place ID が API 側に存在しない（404）"""


def get_place(place_id, api_key, session=requests, timeout=30):
    """place ID の正式名と主タイプを返す。404 は PlaceNotFound、他の失敗は HTTPError

    primaryType は応答に無い場所がある（その場合は空文字）。
    """
    resp = session.get(
        PLACES_URL.format(place_id=place_id),
        headers={'X-Goog-Api-Key': api_key, 'X-Goog-FieldMask': FIELD_MASK},
        # 付けないと displayName が英語表記で返る
        params={'languageCode': 'ja'},
        timeout=timeout,
    )
    if resp.status_code == 404:
        raise PlaceNotFound(place_id)
    resp.raise_for_status()
    body = resp.json()
    return {
        'display_name': body.get('displayName', {}).get('text', ''),
        'primary_type': body.get('primaryType', ''),
    }
