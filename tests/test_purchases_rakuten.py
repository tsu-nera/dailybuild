"""
楽天市場の購入履歴の取り込み（scripts/purchases.py import-rakuten）のテスト

守るもの: UTC の注文日を JST に直す・行の金額は単価×個数・注文者名を書かない・
取得が途中で切れた出力や既存の注文が消える出力では書き込まない・再取り込みで変わらない。
"""

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.purchases import rakuten_history


def _load_script():
    path = BASE_DIR / 'scripts' / 'purchases.py'
    spec = importlib.util.spec_from_file_location('purchases_script', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['purchases_script'] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


def order(number, date, items):
    return {'orderNumber': number, 'orderDate': date, 'shopName': 'ショップ',
            'items': [{'itemName': name, 'itemPrice': price, 'itemUnits': units,
                       'itemUrl': f'https://item.rakuten.co.jp/shop/{name}/',
                       'senderName': '架空 太郎'}
                      for name, price, units in items]}


ORDERS = [
    order('100000-20260802-0000000001', '2026-08-02T13:31:31.000Z', [('寄附', 1000, 30)]),
    order('100000-20120825-0000000002', '2012-08-25T23:46:40.000Z',
          [('チョーカー', 890, 1), ('ナッツ', 1298, 2)]),
]


def write_dump(path, orders, found=None, wrapped=False):
    text = json.dumps({'ordersFound': len(orders) if found is None else found,
                       'orders': orders}, ensure_ascii=False)
    if wrapped:  # chrome-devtools-mcp の evaluate_script が付ける前後の文
        text = f'Script ran on page and returned:\n```json\n{text}\n```\n'
    path.write_text(text, encoding='utf-8')
    return path


def test_dates_are_jst_and_price_is_unit_times_quantity(tmp_path):
    df = rakuten_history.read_dump(write_dump(tmp_path / 'd.json', ORDERS))

    assert list(df.columns) == rakuten_history.COLUMNS
    assert df['order_date'].tolist() == [
        '2012-08-26T08:46:40+09:00', '2012-08-26T08:46:40+09:00', '2026-08-02T22:31:31+09:00']
    assert df['price'].tolist() == [890, 2596, 30000]
    assert '架空' not in df.to_csv()


def test_mcp_wrapped_output_is_read(tmp_path):
    df = rakuten_history.read_dump(write_dump(tmp_path / 'd.json', ORDERS, wrapped=True))
    assert len(df) == 3


def test_truncated_dump_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        rakuten_history.read_dump(write_dump(tmp_path / 'd.json', ORDERS[:1], found=2))


def test_reimport_is_idempotent(tmp_path):
    dest = tmp_path / 'rakuten.csv'
    src = write_dump(tmp_path / 'd.json', ORDERS)
    script.import_rakuten(src, dest)
    first = dest.read_text()
    assert script.import_rakuten(src, dest) == 0
    assert dest.read_text() == first


def test_dump_missing_existing_orders_is_not_written(tmp_path):
    dest = tmp_path / 'rakuten.csv'
    script.import_rakuten(write_dump(tmp_path / 'full.json', ORDERS), dest)
    before = dest.read_text()

    partial = write_dump(tmp_path / 'partial.json', ORDERS[:1])
    assert script.import_rakuten(partial, dest) == 1
    assert dest.read_text() == before

    assert script.import_rakuten(partial, dest, force=True) == 0
    assert len(pd.read_csv(dest)) == 1
