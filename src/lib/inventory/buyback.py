"""本の買取価格（参考値）を ISBN で引き、履歴を data/inventory/buyback.csv に積む

メルカリの相場検索は書名のキーワードで探すので版が混ざる。ISBN で引ける買取価格を、本だけ参考値として持つ。
参照元は駿河屋の買取検索だけ（ログイン不要・HTML に価格が入っている）。予備の参照元を順に試す作りにはしない。
ブックオフ・バリューブックス・ネットオフは ISBN で買取価格を引ける URL が requests から見つからなかった（2026-11-26）。

buyback.csv は1回の取得で1行（date, key, name, isbn, price, source）。「買取不可」「メールにてお見積」「該当なし」の日は
price を空にした行を残す（0円として記録しない。行を作らないと毎日引き直す）。取得に失敗した日は行を残さない。
"""

from __future__ import annotations

import html as htmllib
import json
import re
import sys
import time
from pathlib import Path

import requests

from lib.inventory.homebox import buyback_targets, set_buyback_price
from lib.inventory.market import append_history, due, read_history

SOURCE = '駿河屋 買取'
SEARCH_URL = 'https://www.suruga-ya.jp/kaitori/search_buy'
USER_AGENT = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/130.0 Safari/537.36')
REQUEST_TIMEOUT = 20
REQUEST_INTERVAL = 2  # 秒。1件ずつ間を空ける
HISTORY_COLUMNS = ['date', 'key', 'name', 'isbn', 'price', 'source']

_ROW = re.compile(r'<tr class="listap">(.*?)</tr>', re.S)
_PRODUCT = re.compile(r'data-product="([^"]*)"')
_NO_HIT = '検索結果は０件です'


class BuybackError(Exception):
    pass


def parse_buyback(page: str, isbn: str) -> int | None:
    """駿河屋の買取検索結果から ISBN が一致する行の買取価格（円）。買取不可・見積もり・該当なしは None

    結果の行も「0件」の文言も無いページは形が変わったとみなして例外にする（黙って欠測を増やさない）
    """
    if _NO_HIT in page:
        return None
    rows = _ROW.findall(page)
    if not rows:
        raise BuybackError('結果の行も「0件」の文言も無い（ページの形が変わった）')
    prices = []
    for row in rows:
        if isbn not in row:
            continue
        m = _PRODUCT.search(row)
        if not m:
            raise BuybackError('結果の行に data-product が無い（ページの形が変わった）')
        kakaku = json.loads(htmllib.unescape(m.group(1))).get('kakaku')
        if isinstance(kakaku, int) and kakaku > 0:  # -1 は「メールにてお見積」
            prices.append(kakaku)
    return max(prices) if prices else None


def fetch_buyback(isbn: str) -> int | None:
    r = requests.get(SEARCH_URL, params={'category': '', 'search_word': isbn},
                     headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    time.sleep(REQUEST_INTERVAL)
    if r.status_code == 404 and _NO_HIT in r.text:  # 該当0件は 404 で返る
        return None
    r.raise_for_status()
    return parse_buyback(r.text, isbn)


def fetch_buybacks(client, path: Path, date: str, every_days: int, fetch=fetch_buyback) -> int:
    """ISBN を持つ手放していない物のうち、前回から every_days 日以上空いた物の買取価格を引く。失敗した件数を返す"""
    from datetime import date as Date
    targets = buyback_targets(client)
    keys = due(targets, read_history(path), Date.fromisoformat(date), every_days)
    print(f'ISBN あり {len(targets)} 件、うち今回買取価格を引く {len(keys)} 件', file=sys.stderr)
    rows, failed = [], 0
    for key in keys:
        entity, isbn = targets[key]
        try:
            price = fetch(isbn)
        except Exception as e:  # 1件の失敗で他を止めない。行を残さず翌日引き直す
            print(f'error: {key} {entity["name"]} の買取価格が取れない: {e!r}', file=sys.stderr)
            failed += 1
            continue
        rows.append({'date': date, 'key': key, 'name': entity['name'], 'isbn': isbn,
                     'price': str(price) if price else '', 'source': SOURCE})
        if not price:
            print(f'買取価格なし: {key} {entity["name"]}（{SOURCE}）', file=sys.stderr)
            continue
        set_buyback_price(client, key, price)
        print(f'買取価格: {key} {entity["name"]} {price:,}円（{SOURCE}）', file=sys.stderr)
    if rows:
        append_history(path, rows, HISTORY_COLUMNS)
    return failed
