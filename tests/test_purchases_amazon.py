"""
Amazon の開示データの取り込み（scripts/purchases.py import-amazon）のテスト

守るもの: ミリ秒有無が混在する日付を落とさない・住所とカードを書かない・
既存の注文が消える export では書き込まない・同じ export の再取り込みで変わらない。
"""

import importlib.util
import sys
import zipfile
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.purchases import amazon_export


def _load_script():
    path = BASE_DIR / 'scripts' / 'purchases.py'
    spec = importlib.util.spec_from_file_location('purchases_script', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['purchases_script'] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def export_row(order_id, asin, date, name='商品', qty='1', unit='1,255', tax='125',
               total='1,380'):
    return {
        'ASIN': asin, 'Billing Address': '架空 太郎 東京都 100-0000', 'Currency': 'JPY',
        'Department': 'Kitchen', 'Order Date': date, 'Order ID': order_id,
        'Order Status': 'Closed', 'Original Quantity': qty,
        'Payment Method Type': 'Visa - 0000', 'Product Condition': 'New',
        'Product Name': name, 'Shipping Address': '架空 太郎 東京都 100-0000',
        'Total Amount': total, 'Total Discounts': "'-69'", 'Unit Price': unit,
        'Unit Price Tax': tax, 'Website': 'Amazon.co.jp',
    }


def write_export(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False, encoding='utf-8-sig')
    return path


ROWS = [
    export_row('250-0000000-0000001', 'B000000001', '2020-03-02T11:25:29Z'),
    export_row('250-0000000-0000002', 'B000000002', '2026-10-05T09:09:17.117Z',
               name='電球​', qty='2', unit='770', tax='77', total='1,694'),
]


def test_mixed_date_formats_and_amounts_are_parsed(tmp_path):
    df = amazon_export.read_export(write_export(tmp_path / 'oh.csv', ROWS))
    assert list(df.columns) == amazon_export.COLUMNS
    assert df['order_date'].tolist() == ['2020-03-02T20:25:29+09:00',
                                         '2026-10-05T18:09:17+09:00']
    last = df.iloc[-1]
    assert (last['quantity'], last['unit_price'], last['price']) == (2, 770, 1694)
    assert last['item'] == '電球'


def test_private_columns_are_not_written(tmp_path):
    dest = tmp_path / 'amazon.csv'
    assert script.import_amazon(write_export(tmp_path / 'oh.csv', ROWS), dest) == 0
    text = dest.read_text()
    assert '架空' not in text and 'Visa' not in text


def test_reads_order_history_from_zip(tmp_path):
    csv = write_export(tmp_path / 'oh.csv', ROWS)
    zpath = tmp_path / 'Your Orders.zip'
    with zipfile.ZipFile(zpath, 'w') as zf:
        zf.write(csv, amazon_export.ORDER_HISTORY_MEMBER)
    assert len(amazon_export.read_export(zpath)) == 2


def test_reimport_is_idempotent(tmp_path):
    src = write_export(tmp_path / 'oh.csv', ROWS)
    dest = tmp_path / 'amazon.csv'
    script.import_amazon(src, dest)
    first = dest.read_text()
    assert script.import_amazon(src, dest) == 0
    assert dest.read_text() == first


def test_export_missing_existing_orders_is_refused(tmp_path):
    dest = tmp_path / 'amazon.csv'
    script.import_amazon(write_export(tmp_path / 'full.csv', ROWS), dest)
    before = dest.read_text()

    partial = write_export(tmp_path / 'partial.csv', ROWS[1:])
    assert script.import_amazon(partial, dest) == 1
    assert dest.read_text() == before

    assert script.import_amazon(partial, dest, force=True) == 0
    assert len(pd.read_csv(dest)) == 1


def test_unreadable_amount_raises_without_writing(tmp_path):
    rows = [export_row('250-0000000-0000003', 'B000000003', '2026-01-01T00:00:00Z',
                       total='Not Available')]
    dest = tmp_path / 'amazon.csv'
    with pytest.raises(ValueError):
        script.import_amazon(write_export(tmp_path / 'oh.csv', rows), dest)
    assert not dest.exists()
