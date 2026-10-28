"""
楽天市場の購入履歴ページから取った注文を正規化する

楽天市場には購入履歴の CSV 出力も個人向け API も無い。購入履歴一覧
（https://order.my.rakuten.co.jp/purchase-history/order-list）は注文を HTML 内の
`window.__INITIAL_STATE__.orderListData.orderList` に JSON で埋め込んで返すので、
ログイン済みのブラウザで rakuten_dump.js を実行してそれを全ページ集める。
画面の DOM は読まない（2026-03 に一覧ページが作り直され、DOM を読む拡張は壊れた）。

一覧の罠:
- 既定（絞り込みなし）で全期間が出る。`?page=N` は25件ずつ、年で絞るなら `?order_year=YYYY`
  （`orderYear` / `year` は黙って無視され、絞り込みなしの結果が返る）
- `orderDate` は UTC（末尾 Z）
- `itemPrice` は税込みの単価、`itemUnits` は個数。gmail.csv の price と同じ意味の行の金額は積
- 送料・クーポン・ポイント利用・支払額は一覧に無い（注文詳細ページにしか無い）
- `senderName`（注文者名）や配送先は保存しない
"""

import json
from pathlib import Path

import pandas as pd

JST = 'Asia/Tokyo'

COLUMNS = ['order_date', 'order_id', 'shop', 'item', 'quantity', 'unit_price', 'price',
           'item_url']


def read_dump(path: Path) -> pd.DataFrame:
    """rakuten_dump.js の出力（{"ordersFound", "orders"}）を読み、正規化して返す

    chrome-devtools-mcp の evaluate_script でファイルに落とすと JSON の前後に
    説明文が付くので、最初の `{` から最後の `}` までを読む。
    """
    text = Path(path).read_text(encoding='utf-8')
    dump = json.loads(text[text.index('{'):text.rindex('}') + 1])
    orders = dump['orders']
    if len(orders) != dump['ordersFound']:
        raise ValueError(f'注文数が一覧の件数と合わない: {len(orders)} / {dump["ordersFound"]}')
    return normalize(orders)


def normalize(orders: list[dict]) -> pd.DataFrame:
    """注文の list を1商品1行へ写す。読めない値があれば例外（推測で埋めない）"""
    rows = [
        {
            'order_date': order['orderDate'],
            'order_id': order['orderNumber'],
            'shop': order['shopName'],
            'item': item['itemName'],
            'quantity': int(item['itemUnits']),
            'unit_price': int(item['itemPrice']),
            'item_url': item['itemUrl'],
        }
        for order in orders
        for item in order['items']
    ]
    df = pd.DataFrame(rows, columns=[c for c in COLUMNS if c != 'price'])
    df['price'] = df['unit_price'] * df['quantity']

    dates = pd.to_datetime(df['order_date'], utc=True, format='ISO8601')
    df['order_date'] = dates.dt.tz_convert(JST).map(
        lambda t: t.isoformat(timespec='seconds'))

    return (df.sort_values(['order_date', 'order_id'], kind='stable')
              .reset_index(drop=True)[COLUMNS])
