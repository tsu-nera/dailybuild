"""
Gmail の注文確認からの購入履歴（scripts/purchases.py fetch / lib.purchases.gmail）のテスト（Issue #219）

守るもの: 複数商品の注文を1商品1行にする・message_id で冪等・窓外の既存行を消さない・
書式が合わないメールで行を捏造しない・API 失敗で CSV を変えない・
private 未マウントで API を叩く前に落ちる。実 API は叩かない（フェイクの service を使う）。
"""

import argparse
import base64
import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / 'src'))

from lib.clients import gmail_client
from lib.purchases import gmail


def _load_script():
    path = BASE_DIR / 'scripts' / 'purchases.py'
    spec = importlib.util.spec_from_file_location('purchases_script_gmail', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['purchases_script_gmail'] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

SINCE = dt.datetime(2026, 10, 1, tzinfo=gmail.JST)

AMAZON_BODY = """
    ご注文ありがとうございます。
注文番号
250-0000000-0000001

注文内容の表示と変更
https://www.amazon.co.jp/your-orders/order-details?orderID=250-0000000-0000001

* LED電球 E26 (2個パック)
  数量: 1
  3780 JPY

* ブレーキシュー
  数量: 2
  847 JPY

合計
5474 JPY
"""

AMAZON_OLD_BODY = """Amazon.co.jp ご注文の確認
注文番号： 250-0000000-0000009
              注文合計： ￥ 652
"""

RAKUTEN_BODY = """この度は楽天市場内のショップ「架空商店」を
ご利用いただきまして、誠にありがとうございます。

[ショップ名]   架空商店 (39ショップ)
==========
[商品]
お米 5kg
精米日：選択しない
価格  2,500(円) x 2(個) = 5,000(円) ※税込
ふりかけ
価格 300(円) x 1(個) = 300(円) ※税込
*********************************************************************
送料計 0(円)
支払い金額 5,300(円)

[受注番号]     000000-20261005-0000000001
"""


def message(id_, sender, body, received='2026-10-05T09:09:26+00:00'):
    millis = int(dt.datetime.fromisoformat(received).timestamp() * 1000)
    data = base64.urlsafe_b64encode(body.encode()).decode()
    return {
        'id': id_, 'internalDate': str(millis),
        'payload': {
            'mimeType': 'multipart/alternative',
            'headers': [{'name': 'From', 'value': f'Shop <{sender}>'}],
            'parts': [{'mimeType': 'text/plain', 'body': {'data': data}},
                      {'mimeType': 'text/html', 'body': {'data': ''}}],
        },
    }


class FakeService:
    """users().messages().list/get(...).execute() だけを模す"""

    def __init__(self, messages=None, error=None):
        self.store = {m['id']: m for m in messages or []}
        self.error, self.queries = error, []
        self._next = None

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self.queries.append(kwargs['q'])
        self._next = {'messages': [{'id': i} for i in self.store]}
        return self

    def get(self, **kwargs):
        self._next = self.store[kwargs['id']]
        return self

    def execute(self):
        if self.error:
            raise self.error
        return self._next


def run(service, csv):
    return script.fetch_to_csv(service, csv, SINCE)


def test_multi_item_orders_become_one_row_per_item(tmp_path):
    csv = tmp_path / 'gmail.csv'
    svc = FakeService([message('m1', gmail.AMAZON_SENDER, AMAZON_BODY),
                       message('m2', gmail.RAKUTEN_SENDER, RAKUTEN_BODY)])
    assert run(svc, csv) == 0
    df = pd.read_csv(csv, dtype=str)
    assert list(df.columns) == gmail.COLUMNS
    amazon = df[df['message_id'] == 'm1']
    assert amazon['item'].tolist() == ['LED電球 E26 (2個パック)', 'ブレーキシュー']
    assert amazon['quantity'].tolist() == ['1', '2']
    assert amazon['price'].tolist() == ['3780', '1694']
    assert set(amazon['order_id']) == {'250-0000000-0000001'}
    assert set(amazon['order_date']) == {'2026-10-05T18:09:26+09:00'}
    rakuten = df[df['message_id'] == 'm2']
    assert rakuten['item'].tolist() == ['お米 5kg', 'ふりかけ']
    assert rakuten['price'].tolist() == ['5000', '300']
    assert set(rakuten['shop']) == {'架空商店'}


def test_query_is_limited_to_allowlisted_senders(tmp_path):
    svc = FakeService([])
    run(svc, tmp_path / 'gmail.csv')
    q = svc.queries[0]
    assert gmail.AMAZON_SENDER in q and gmail.RAKUTEN_SENDER in q
    assert 'category:' not in q
    assert f'after:{int(SINCE.timestamp())}' in q


def test_refetch_is_idempotent(tmp_path):
    csv = tmp_path / 'gmail.csv'
    svc = FakeService([message('m1', gmail.AMAZON_SENDER, AMAZON_BODY)])
    run(svc, csv)
    first = csv.read_text()
    assert run(svc, csv) == 0
    assert csv.read_text() == first


def test_rows_outside_the_window_are_kept(tmp_path):
    csv = tmp_path / 'gmail.csv'
    run(FakeService([message('m1', gmail.AMAZON_SENDER, AMAZON_BODY)]), csv)
    run(FakeService([message('m2', gmail.RAKUTEN_SENDER, RAKUTEN_BODY)]), csv)
    assert set(pd.read_csv(csv, dtype=str)['message_id']) == {'m1', 'm2'}


def test_unparseable_mail_makes_no_row_and_exits_zero(tmp_path, caplog):
    csv = tmp_path / 'gmail.csv'
    svc = FakeService([message('old', gmail.AMAZON_SENDER, AMAZON_OLD_BODY),
                       message('m1', gmail.AMAZON_SENDER, AMAZON_BODY)])
    assert run(svc, csv) == 0
    assert set(pd.read_csv(csv, dtype=str)['message_id']) == {'m1'}
    assert 'old' in caplog.text


def test_unknown_sender_makes_no_row(tmp_path):
    csv = tmp_path / 'gmail.csv'
    run(FakeService([message('x', 'someone@example.com', AMAZON_BODY)]), csv)
    assert pd.read_csv(csv, dtype=str).empty


def test_api_failure_leaves_csv_untouched(tmp_path):
    csv = tmp_path / 'gmail.csv'
    run(FakeService([message('m1', gmail.AMAZON_SENDER, AMAZON_BODY)]), csv)
    before = csv.read_text()
    assert run(FakeService(error=RuntimeError('boom')), csv) == 1
    assert csv.read_text() == before


def test_unmounted_private_dir_fails_before_api(tmp_path, monkeypatch):
    monkeypatch.setattr(script, 'GMAIL_CSV', BASE_DIR / 'no-such-private' / 'gmail.csv')

    def boom(**_):
        raise AssertionError('API を叩いてはいけない')

    monkeypatch.setattr(gmail_client, 'create_service', boom)
    args = argparse.Namespace(since=None, days=7, login=False)
    with pytest.raises(FileNotFoundError):
        script.cmd_fetch(args)
