"""
Gmail の注文確認メールから購入履歴の行を作る

対象は送信元の allowlist だけ（`category:purchases` は発送・配達通知や証券の約定まで
拾うので使わない）。送信元ごとに text/plain 本文の正規表現パーサを持つ。
書式が合わないメールは行を作らない（品名も金額も推測で埋めない）。

Amazon の過去分は開示データ（amazon_export、data/purchases/amazon.csv）が持つ。
2024 年以前の Amazon の注文確認には品名が無いので、ここでは現行書式だけを読む。
楽天市場の全期間は購入履歴ページ由来の rakuten.csv が持つ。
読む側は order_id が amazon.csv / rakuten.csv にある行を gmail.csv から落とせば重複しない。

メールの値と開示データの値はずれうる（開示データが正）:
- Amazon は1通に複数の注文がまとまることがあり、表示される注文番号は1つだけ。
  そのメールの全商品にその番号が付く（別の注文の商品が混ざる）
- 金額は注文時点の税込み。開示データの price は確定後の値で送料も含む

asin は Amazon の text/html 本文にある注文商品へのリンク（ref が `fed_asin_title`）から取り、
品名（画像の alt か、切り詰められたリンク文字の前方一致）で行と照合する。
Amazon が品名を伏せた商品（「プライバシー保護のため、商品は非表示になっています」）は
行もリンクも同じ伏せ字なので品名では決まらない。同じ品名の行とリンクの数が等しいときだけ、
その品名の中で並び順に対応付ける（リンクは本文の商品と同じ順に並ぶ）。
それでも決まらない行・楽天の行は空。
"""

import datetime as dt
import html
import re
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

JST = dt.timezone(dt.timedelta(hours=9))

COLUMNS = ['order_date', 'shop', 'order_id', 'asin', 'item', 'quantity', 'price', 'message_id']

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

# 注文商品のリンクだけが ref に fed_asin_title を持つ（おすすめ商品のリンクは持たない）。
# 画像リンクは _i_、文字リンクは _t_。href の中の商品 URL は URL エンコードされている
_ORDERED_ITEM_REF = 'fed_asin_title'
_ASIN_IN_HREF = re.compile(r'dp(?:%2F|/)([A-Z0-9]{10})', re.I)
_TRUNCATION = ('...', '…')


def _normalize(text: str) -> str:
    return re.sub(r'\s+', '', html.unescape(text))


class _OrderedItemLinks(HTMLParser):
    """注文商品のリンクから (ASIN, 画像の alt, リンク文字) を集める"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[dict] = []
        self._current: dict | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            href = attrs.get('href') or ''
            m = _ASIN_IN_HREF.search(href)
            self._current = ({'asin': m[1].upper(), 'alt': '', 'text': ''}
                             if m and _ORDERED_ITEM_REF in href else None)
        elif tag == 'img' and self._current is not None and attrs.get('alt'):
            self._current['alt'] = attrs['alt']

    def handle_data(self, data):
        if self._current is not None:
            self._current['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self._current is not None:
            self.links.append(self._current)
            self._current = None


def ordered_item_candidates(html_body: str) -> dict[str, dict[str, set[str]]]:
    """ASIN ごとの照合用の品名。full は完全な品名（alt）、prefix は切り詰められたリンク文字"""
    parser = _OrderedItemLinks()
    parser.feed(html_body)
    parser.close()
    candidates: dict[str, dict[str, set[str]]] = {}
    for link in parser.links:
        entry = candidates.setdefault(link['asin'], {'full': set(), 'prefix': set()})
        if link['alt'].strip():
            entry['full'].add(_normalize(link['alt']))
        text = link['text'].strip()
        for mark in _TRUNCATION:
            text = text.removesuffix(mark)
        if _normalize(text):
            entry['prefix'].add(_normalize(text))
    return candidates


def match_asin(item: str, candidates: dict[str, dict[str, set[str]]]) -> str:
    """品名に対応する ASIN。完全一致を優先し、無ければ前方一致。1件に決まらなければ空"""
    name = _normalize(item)
    exact = [a for a, c in candidates.items() if name in c['full']]
    if exact:
        return exact[0] if len(exact) == 1 else ''
    prefix = [a for a, c in candidates.items() if any(name.startswith(p) for p in c['prefix'])]
    return prefix[0] if len(prefix) == 1 else ''


def assign_asins(items: list[str], candidates: dict[str, dict[str, set[str]]]) -> list[str]:
    """行ごとの ASIN。同じ品名の行が複数あるときは、その品名のリンクが同数の場合だけ順に対応付ける

    同じ品名の行が複数あるのは、伏せ字の商品か同名の別商品。品名だけで照合すると
    全行が同じ ASIN を取るので、数が合わなければ空にする。
    """
    names = [_normalize(item) for item in items]
    asins = []
    for item, name in zip(items, names):
        if names.count(name) > 1:
            links = [a for a, c in candidates.items() if name in c['full']]  # dict は本文の出現順
            rows = [i for i, n in enumerate(names) if n == name]
            asins.append(links[rows.index(len(asins))] if len(links) == len(rows) else '')
        else:
            asins.append(match_asin(item, candidates))
    return asins


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


def to_rows(message: dict, text: str, html_body: str = '') -> list[dict] | None:
    """1通を行に変換する。対象外の送信元・書式が合わないメールは None

    html_body は Amazon の asin を取るためだけに使う。無ければ asin は空。
    """
    sender = sender_address(message['payload'].get('headers', []))
    parser = PARSERS.get(sender)
    if parser is None:
        return None
    parsed = parser(text)
    if parsed is None:
        return None
    shop, order_id, items = parsed
    received = dt.datetime.fromtimestamp(int(message['internalDate']) / 1000, JST)
    order_date = received.isoformat(timespec='seconds')
    candidates = (ordered_item_candidates(html_body)
                  if sender == AMAZON_SENDER and html_body else {})
    asins = (assign_asins([item['item'] for item in items], candidates) if candidates
             else [''] * len(items))
    return [{'order_date': order_date, 'shop': shop, 'order_id': order_id, 'asin': asin,
             **item, 'message_id': message['id']} for item, asin in zip(items, asins)]


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
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    for column in COLUMNS:
        if column not in df.columns:
            df[column] = ''  # asin 列より前に書いた CSV
    return df[COLUMNS]


def merge(csv_path: Path, rows: list[dict]) -> pd.DataFrame:
    """取得したメールの行で同じ message_id の既存行を差し替える。他の行は残す"""
    existing = load(csv_path)
    new = pd.DataFrame(rows, columns=COLUMNS).astype(str)
    kept = existing[~existing['message_id'].isin(set(new['message_id']))]
    merged = pd.concat([kept, new], ignore_index=True)
    return (merged.sort_values(['order_date', 'message_id'], kind='stable')
                  .reset_index(drop=True)[COLUMNS])
