"""
Amazon の個人データ開示（privacy-central）の注文履歴を正規化する

Amazon の個人アカウントには注文履歴の API も画面からの CSV 出力も無く、
privacy-central のデータ開示申請で届く `Your Orders.zip` が唯一の経路。
物の注文は `Your Amazon Orders/Order History.csv`（1商品1行、全期間）に入る。
Kindle などのデジタル注文は別ファイルで、ここでは扱わない。

export の罠:
- `Order Date` はミリ秒付きと無しが混在する（format='ISO8601' でないと NaT になる）
- 金額はカンマ区切り、`Total Discounts` 等は `'-69'` のようにクォート付き
- `Unit Price` は税抜き。注文確認メールの金額と一致するのは `Total Amount`（税込み×数量）
- 住所・カード下4桁・配送番号の列は保存しない
"""

import io
import zipfile
from pathlib import Path

import pandas as pd

JST = 'Asia/Tokyo'
ORDER_HISTORY_MEMBER = 'Your Amazon Orders/Order History.csv'

COLUMNS = ['order_date', 'order_id', 'asin', 'item', 'quantity',
           'unit_price', 'unit_tax', 'price', 'status', 'condition', 'department']

_SOURCE_COLUMNS = {
    'Order Date': 'order_date',
    'Order ID': 'order_id',
    'ASIN': 'asin',
    'Product Name': 'item',
    'Original Quantity': 'quantity',
    'Unit Price': 'unit_price',
    'Unit Price Tax': 'unit_tax',
    'Total Amount': 'price',
    'Order Status': 'status',
    'Product Condition': 'condition',
    'Department': 'department',
}
_AMOUNT_COLUMNS = ['quantity', 'unit_price', 'unit_tax', 'price']


def read_export(path: Path) -> pd.DataFrame:
    """`Your Orders.zip` か展開済みの `Order History.csv` を読み、正規化して返す"""
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as zf:
            raw = zf.read(ORDER_HISTORY_MEMBER)
        source = io.BytesIO(raw)
    else:
        source = path
    return normalize(pd.read_csv(source, dtype=str, encoding='utf-8-sig'))


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    """export の列を保存用の列へ写す。読めない値があれば例外（推測で埋めない）"""
    missing = [c for c in _SOURCE_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f'Order History.csv に列が無い: {missing}')

    df = raw[list(_SOURCE_COLUMNS)].rename(columns=_SOURCE_COLUMNS)

    dates = pd.to_datetime(df['order_date'], utc=True, format='ISO8601')
    df['order_date'] = dates.dt.tz_convert(JST).map(
        lambda t: t.isoformat(timespec='seconds'))

    for col in _AMOUNT_COLUMNS:
        cleaned = df[col].str.replace(',', '', regex=False).str.strip("'")
        df[col] = pd.to_numeric(cleaned, errors='raise').astype('int64')

    # 商品名の末尾にゼロ幅スペースが混ざる行がある
    df['item'] = df['item'].str.replace('​', '', regex=False).str.strip()

    if df.duplicated(['order_id', 'asin']).any():
        raise ValueError('order_id と asin の組が重複している')

    return (df.sort_values(['order_date', 'order_id', 'asin'])
              .reset_index(drop=True)[COLUMNS])

