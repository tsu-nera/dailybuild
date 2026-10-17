"""
Gmail の注文確認メールから購入履歴の行を作る

対象は送信元の allowlist だけ（`category:purchases` は発送・配達通知や証券の約定まで
拾うので使わない）。送信元ごとに text/plain 本文の正規表現パーサを持つ。
書式が合わないメールは行を作らない（品名も金額も推測で埋めない）。

Amazon の過去分は開示データ（amazon_export、data/purchases/amazon.csv）が持つ。
2024 年以前の Amazon の注文確認には品名が無いので、ここでは現行書式だけを読む。
読む側は order_id が amazon.csv にある行を gmail.csv から落とせば重複しない。

メールの値と開示データの値はずれうる（開示データが正）:
- Amazon は1通に複数の注文がまとまることがあり、表示される注文番号は1つだけ。
  そのメールの全商品にその番号が付く（別の注文の商品が混ざる）
- 金額は注文時点の税込み。開示データの price は確定後の値で送料も含む
"""

import datetime as dt
import re
from pathlib import Path

import pandas as pd

JST = dt.timezone(dt.timedelta(hours=9))

COLUMNS = ['order_date', 'shop', 'order_id', 'item', 'quantity', 'price', 'message_id']

AMAZON_SENDER = 'auto-confirm@amazon.co.jp'
RAKUTEN_SENDER = 'order@rakuten.co.jp'

_AMAZON_ORDER_ID = re.compile(r'^注文番号\s*\n\s*(\d{3}-\d{7}-\d{7})\s*$', re.M)
_AMAZON_ITEM = re.compile(
    r'^\*\s+(?P<item>.+?)\s*\n\s+数量:\s*(?P<qty>\d+)\s*\n\s+(?P<price>[\d,]+)\s*JPY\s*$', re.M)

_RAKUTEN_ORDER_ID = re.compile(r'^\[受注番号\]\s+(\S+)', re.M)
_RAKUTEN_SHOP = re.compile(r'^\[ショップ名\]\s+(.+?)(?:\s+\(\d+ショップ\))?\s*$', re.M)
# 実物は桁揃えのため空白が複数入る（MCP 経由で読むと1つに詰められて見える）
_RAKUTEN_PRICE = re.compile(
    r'^価格\s+[\d,]+\(円\)\s*x\s*(?P<qty>[\d,]+)\(個\)\s*=\s*(?P<price>[\d,]+)\(円\)')


def _int(text: str) -> int:
    return int(text.replace(',', ''))


def parse_amazon(text: str) -> tuple[str, str, list[dict]] | None:
    order = _AMAZON_ORDER_ID.search(text)
    # メールの金額は税込みの単価。行の金額（amazon.csv の price と同じ意味）に揃える
    items = [{'item': m['item'].strip(), 'quantity': _int(m['qty']),
              'price': _int(m['qty']) * _int(m['price'])}
             for m in _AMAZON_ITEM.finditer(text)]
    if not order or not items:
        return None
    return 'Amazon.co.jp', order[1], items


def parse_rakuten(text: str) -> tuple[str, str, list[dict]] | None:
    order = _RAKUTEN_ORDER_ID.search(text)
    shop = _RAKUTEN_SHOP.search(text)
    if not order or not shop or '[商品]' not in text:
        return None

    section = text.split('[商品]', 1)[1]
    items, block = [], []
    for line in section.splitlines():
        line = line.strip()
        if line.startswith('*****') or line.startswith('送料計'):
            break
        m = _RAKUTEN_PRICE.match(line)
        if m:
            if not block:
                return None
            items.append({'item': block[0], 'quantity': _int(m['qty']),
                          'price': _int(m['price'])})
            block = []
        elif line:
            block.append(line)
    if not items:
        return None
    return shop[1].strip(), order[1], items


PARSERS = {AMAZON_SENDER: parse_amazon, RAKUTEN_SENDER: parse_rakuten}


def search_query(since: dt.datetime) -> str:
    """allowlist の送信元に絞った Gmail 検索式（after は epoch 秒で tz の曖昧さを避ける）"""
    senders = ' OR '.join(PARSERS)
    return f'from:({senders}) after:{int(since.timestamp())}'


def sender_address(headers: list[dict]) -> str:
    for h in headers:
        if h.get('name', '').lower() == 'from':
            m = re.search(r'<([^>]+)>', h['value'])
            return (m[1] if m else h['value']).strip().lower()
    return ''


def to_rows(message: dict, text: str) -> list[dict] | None:
    """1通を行に変換する。対象外の送信元・書式が合わないメールは None"""
    parser = PARSERS.get(sender_address(message['payload'].get('headers', [])))
    if parser is None:
        return None
    parsed = parser(text)
    if parsed is None:
        return None
    shop, order_id, items = parsed
    received = dt.datetime.fromtimestamp(int(message['internalDate']) / 1000, JST)
    order_date = received.isoformat(timespec='seconds')
    return [{'order_date': order_date, 'shop': shop, 'order_id': order_id,
             **item, 'message_id': message['id']} for item in items]


# 最後の行より少し前から取り直す。message_id で差し替えるので重なっても二重にならない
CATCHUP_MARGIN_DAYS = 3


def catchup_start(csv_path: Path) -> dt.date | None:
    """前回の続きから取るための開始日。CSV が無い・空なら None（初回は --since が要る）"""
    existing = load(csv_path)
    if existing.empty:
        return None
    last = dt.datetime.fromisoformat(existing['order_date'].max()).date()
    return last - dt.timedelta(days=CATCHUP_MARGIN_DAYS)


def load(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(csv_path, dtype=str)


def merge(csv_path: Path, rows: list[dict]) -> pd.DataFrame:
    """取得したメールの行で同じ message_id の既存行を差し替える。他の行は残す"""
    existing = load(csv_path)
    new = pd.DataFrame(rows, columns=COLUMNS).astype(str)
    kept = existing[~existing['message_id'].isin(set(new['message_id']))]
    merged = pd.concat([kept, new], ignore_index=True)
    return (merged.sort_values(['order_date', 'message_id'], kind='stable')
                  .reset_index(drop=True)[COLUMNS])
