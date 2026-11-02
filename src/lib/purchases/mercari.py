"""
メルカリの取引通知メールから購入・販売の履歴を作る

個人向けの API も公式の CSV 出力も無いので、no-reply@mercari.jp の通知を読む。
1商品1行で、主キーは (direction, item_id)。item_id は商品ページの ID（`m` + 11桁）。

件名で種類を分ける。それ以外の件名（評価・発送依頼の催促・宣伝・メルカリストア）は読まない:
- buy: 「ご購入ありがとうございます」と「〇〇さんから「品名」が発送されました」。
  2026 年の購入には前者が届いていなかったので、後者も購入の証拠として使う
- sell: 「「品名」の発送をお願いします」と「〇〇さんが「品名」を購入しました」
  （コンビニ・ATM 払いの時は後者が先に来る）
- cancel: 「取引キャンセル完了のお知らせ」。売り買いのどちらかは書かれていないので
  item_id で行に当てる。キャンセルの後に同じ item_id の取引通知が来ていれば取引は生きている

price はメールに書かれた商品価格で、手数料・送料・ポイントは引かない。
件名が合うのに本文が読めないメールは行を作らない（品名も金額も推測で埋めない）。
"""

import datetime as dt
import re
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

JST = dt.timezone(dt.timedelta(hours=9))

SENDER = 'no-reply@mercari.jp'

COLUMNS = ['date', 'direction', 'item_id', 'item', 'counterparty', 'price', 'status',
           'message_id']

# Gmail の検索は粗い絞り込み。種類の判定は下の正規表現で行う
SEARCH_QUERY = (f'from:{SENDER} subject:(ご購入ありがとうございます OR 発送されました'
                ' OR 発送をお願いします OR 購入しました OR 取引キャンセル完了)')

_KINDS = [
    ('buy', re.compile(r'^【メルカリ】ご購入ありがとうございます$')),
    ('buy', re.compile(r'^【メルカリ】.+さんから「.+」が発送されました$')),
    ('sell', re.compile(r'^【メルカリ】「.+」の発送をお願いします$')),
    ('sell', re.compile(r'^【メルカリ】.+さんが「.+」を購入しました$')),
    ('cancel', re.compile(r'^【メルカリ】取引キャンセル完了のお知らせ$')),
]

# 古い書式は「商品ID : 」、キャンセル通知は全角コロン
_FIELD = r'^{}\s*[:：]\s*(.+?)\s*$'
_ITEM_ID = re.compile(_FIELD.format('商品ID'), re.M)
_ITEM_NAME = re.compile(_FIELD.format('商品名'), re.M)
_PRICE = re.compile(r'^(?:商品代金|商品価格)\s*[:：]\s*[￥¥]?\s*([\d,]+)\s*円?\s*$', re.M)
_SELLER = re.compile(_FIELD.format('出品者'), re.M)
_BUYER = re.compile(r'^下記の商品を(.+?)さんが購入しました。?\s*$', re.M)
_SHIPPER = re.compile(r'^下記の商品が(.+?)さんより発送されました。?\s*$', re.M)
_ITEM_ID_SHAPE = re.compile(r'^m\d+$')


def classify(subject: str) -> str | None:
    subject = subject.strip()
    for kind, pattern in _KINDS:
        if pattern.match(subject):
            return kind
    return None


def _search(pattern: re.Pattern, text: str) -> str:
    m = pattern.search(text)
    return m[1].strip() if m else ''


def parse(kind: str, text: str) -> dict | None:
    """本文から取引の項目を取り出す。必須項目が欠けたら None"""
    item_id = _search(_ITEM_ID, text)
    if not _ITEM_ID_SHAPE.match(item_id):
        return None
    if kind == 'cancel':
        return {'item_id': item_id}

    item = _search(_ITEM_NAME, text)
    price = _search(_PRICE, text).replace(',', '')
    if not item or not price:
        return None
    if kind == 'buy':
        counterparty = _search(_SELLER, text) or _search(_SHIPPER, text)
    else:
        counterparty = _search(_BUYER, text)
    return {'item_id': item_id, 'item': item, 'counterparty': counterparty, 'price': price}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'p', 'div', 'tr', 'li'):
            self.chunks.append('\n')

    def handle_data(self, data):
        self.chunks.append(data)


def html_to_text(html_body: str) -> str:
    parser = _Text()
    parser.feed(html_body)
    parser.close()
    return '\n'.join(line.strip() for line in ''.join(parser.chunks).splitlines())


def header(message: dict, name: str) -> str:
    for h in message['payload'].get('headers', []):
        if h.get('name', '').lower() == name.lower():
            return h['value']
    return ''


def to_event(message: dict, text: str, html_body: str = '') -> dict | None:
    """1通を取引イベントにする。対象外の件名は {'kind': None}、読めなければ None"""
    kind = classify(header(message, 'Subject'))
    if kind is None:
        return {'kind': None}
    fields = parse(kind, text) if text else None
    if fields is None and html_body:
        fields = parse(kind, html_to_text(html_body))
    if fields is None:
        return None
    received = dt.datetime.fromtimestamp(int(message['internalDate']) / 1000, JST)
    return {'kind': kind, 'at': received.isoformat(timespec='seconds'),
            'message_id': message['id'], **fields}


def build(events: list[dict]) -> pd.DataFrame:
    """取引イベントを1商品1行にまとめる

    同じ (direction, item_id) の通知が複数あれば最初の通知の日時・message_id を採り、
    空の項目は後の通知で埋める。キャンセルを挟んだ再取引は後の取引で行を作り直す。
    最後の取引通知より後にキャンセルがあれば status=cancelled。
    """
    rows: dict[tuple[str, str], dict] = {}
    last_trade: dict[str, str] = {}
    cancels: dict[str, str] = {}
    for e in sorted((e for e in events if e.get('kind')), key=lambda e: e['at']):
        if e['kind'] == 'cancel':
            cancels[e['item_id']] = e['at']
            continue
        key = (e['kind'], e['item_id'])
        row = rows.get(key)
        # キャンセル後の再取引は別の取引（相手も日時も違う）なので行を作り直す
        relisted = row is not None and cancels.get(e['item_id'], '') > last_trade[e['item_id']]
        last_trade[e['item_id']] = e['at']
        if row is None or relisted:
            rows[key] = {'date': e['at'], 'direction': e['kind'], 'item_id': e['item_id'],
                         'item': e['item'], 'counterparty': e['counterparty'],
                         'price': e['price'], 'status': '', 'message_id': e['message_id']}
        else:
            for column in ('item', 'counterparty', 'price'):
                row[column] = row[column] or e[column]

    for (_, item_id), row in rows.items():
        if item_id in cancels and cancels[item_id] > last_trade[item_id]:
            row['status'] = 'cancelled'

    df = pd.DataFrame(list(rows.values()), columns=COLUMNS).astype(str)
    return df.sort_values(['date', 'item_id'], kind='stable').reset_index(drop=True)


def lost_keys(csv_path: Path, new: pd.DataFrame) -> set[tuple[str, str]]:
    """既存 CSV にあって new に無い (direction, item_id)。メールは消えないので、あれば取得が欠けている"""
    if not csv_path.exists():
        return set()
    existing = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    return (set(zip(existing['direction'], existing['item_id']))
            - set(zip(new['direction'], new['item_id'])))
