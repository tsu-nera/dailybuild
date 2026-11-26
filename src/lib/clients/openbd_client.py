"""openBD（無料・キー不要の書誌 API）から書名を引く

openBD は版元が登録した本しか持たない。無い本は `[null]` が返る。
`summary.title` には版（「第3版」など）が入っていないことがあるので、版は呼び出し側で補う。
"""

import requests

API_URL = 'https://api.openbd.jp/v1/get'
REQUEST_TIMEOUT = 15


def fetch_title(isbn: str) -> str | None:
    """ISBN-13 の書名。openBD に無い本は None"""
    r = requests.get(API_URL, params={'isbn': isbn}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    records = r.json()
    if not records or records[0] is None:
        return None
    return (records[0].get('summary') or {}).get('title') or None
