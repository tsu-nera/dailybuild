"""
メルカリの取引通知からの売買履歴（scripts/purchases.py fetch-mercari / lib.purchases.mercari）のテスト

守るもの: 購入確認と発送通知を同じ1行にまとめる（二重にしない）・キャンセルを行に当てる・
キャンセル後の再取引を cancelled にしない・本文が読めないメールで行を捏造しない・
取引通知でない件名を読まない・既存の行が消える取得では書かない・API 失敗で CSV を変えない・
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
from lib.purchases import mercari


def _load_script():
    path = BASE_DIR / 'scripts' / 'purchases.py'
    spec = importlib.util.spec_from_file_location('purchases_script_mercari', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['purchases_script_mercari'] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()

BUY_SUBJECT = '【メルカリ】ご購入ありがとうございます'
BUY_BODY = """テストさん

下記の商品の購入が完了しました。

■商品情報
商品ID : m00000000001
商品名 : 架空の小説 (全3巻)
出品者 : seller01
■支払い金額
商品代金 : ￥2,800
"""

SHIPPED_SUBJECT = '【メルカリ】seller01さんから「架空の小説 (全3巻)」が発送されました'
SHIPPED_BODY = """下記の商品がseller01さんより発送されました。

■商品情報
商品ID : m00000000001
商品名 : 架空の小説 (全3巻)
商品価格 : 2,800円
出品者 : seller01
"""

SHIPPED_ONLY_SUBJECT = '【メルカリ】うめさんから「架空の測定器」が発送されました'
SHIPPED_ONLY_BODY = """下記の商品がうめさんより発送されました。

■商品情報
商品ID : m00000000002
商品名 : 架空の測定器
商品価格 : 2,800円
出品者 : うめ
"""

SELL_SUBJECT = '【メルカリ】「架空のスピーカー」の発送をお願いします'
SELL_BODY = """下記の商品を買い手Aさんが購入しました。

■商品情報
商品ID : m00000000003
商品名 : 架空のスピーカー
商品価格 : 6,000円

商品の発送をお願いします。
"""

CANCEL_SUBJECT = '【メルカリ】取引キャンセル完了のお知らせ'
CANCEL_BODY = """下記の取引は、キャンセル申請成立によりキャンセルいたしました。

■商品情報
商品ID：m00000000003
商品名：架空のスピーカー
商品価格：¥6,000
"""


def message(id_, subject, body, received, html=''):
    millis = int(dt.datetime.fromisoformat(received).timestamp() * 1000)
    parts = []
    if body:
        parts.append({'mimeType': 'text/plain',
                      'body': {'data': base64.urlsafe_b64encode(body.encode()).decode()}})
    if html:
        parts.append({'mimeType': 'text/html',
                      'body': {'data': base64.urlsafe_b64encode(html.encode()).decode()}})
    return {
        'id': id_, 'internalDate': str(millis),
        'payload': {
            'mimeType': 'multipart/alternative',
            'headers': [{'name': 'From', 'value': f'メルカリ <{mercari.SENDER}>'},
                        {'name': 'Subject', 'value': subject}],
            'parts': parts,
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


def read(csv):
    return pd.read_csv(csv, dtype=str, keep_default_na=False)


def test_purchase_confirmation_and_shipping_notice_make_one_row(tmp_path):
    csv = tmp_path / 'mercari.csv'
    svc = FakeService([
        message('b1', BUY_SUBJECT, BUY_BODY, '2025-06-19T12:13:37+00:00'),
        message('b2', SHIPPED_SUBJECT, SHIPPED_BODY, '2025-06-20T09:00:00+00:00'),
        message('s1', SELL_SUBJECT, SELL_BODY, '2020-10-30T15:00:56+00:00'),
    ])
    assert script.fetch_mercari_to_csv(svc, csv) == 0
    df = read(csv)
    assert list(df.columns) == mercari.COLUMNS
    assert df[['direction', 'item_id', 'counterparty', 'price', 'message_id']].values.tolist() == [
        ['sell', 'm00000000003', '買い手A', '6000', 's1'],
        ['buy', 'm00000000001', 'seller01', '2800', 'b1'],
    ]
    assert df['date'].tolist()[1] == '2025-06-19T21:13:37+09:00'


def test_shipping_notice_alone_is_a_purchase(tmp_path):
    csv = tmp_path / 'mercari.csv'
    svc = FakeService([message('k', SHIPPED_ONLY_SUBJECT, SHIPPED_ONLY_BODY,
                               '2026-02-12T11:28:45+00:00')])
    assert script.fetch_mercari_to_csv(svc, csv) == 0
    assert read(csv)[['direction', 'item_id', 'counterparty']].values.tolist() == [
        ['buy', 'm00000000002', 'うめ']]


def test_cancellation_marks_the_row(tmp_path):
    csv = tmp_path / 'mercari.csv'
    svc = FakeService([
        message('s1', SELL_SUBJECT, SELL_BODY, '2020-10-30T15:00:00+00:00'),
        message('c1', CANCEL_SUBJECT, CANCEL_BODY, '2020-11-02T00:00:00+00:00'),
    ])
    assert script.fetch_mercari_to_csv(svc, csv) == 0
    df = read(csv)
    assert len(df) == 1
    assert df['status'].tolist() == ['cancelled']


def test_trade_after_cancellation_is_alive(tmp_path):
    csv = tmp_path / 'mercari.csv'
    svc = FakeService([
        message('s1', SELL_SUBJECT, SELL_BODY, '2020-10-30T15:00:00+00:00'),
        message('c1', CANCEL_SUBJECT, CANCEL_BODY, '2020-11-02T00:00:00+00:00'),
        message('s2', SELL_SUBJECT, SELL_BODY.replace('買い手A', '買い手B'),
                '2020-11-05T00:00:00+00:00'),
    ])
    assert script.fetch_mercari_to_csv(svc, csv) == 0
    df = read(csv)
    assert df[['status', 'counterparty', 'message_id']].values.tolist() == [['', '買い手B', 's2']]


def test_unreadable_body_makes_no_row(tmp_path, caplog):
    csv = tmp_path / 'mercari.csv'
    broken = BUY_BODY.replace('商品ID : m00000000001', '商品ID : ')
    svc = FakeService([message('b1', BUY_SUBJECT, broken, '2025-06-19T12:13:37+00:00'),
                       message('s1', SELL_SUBJECT, SELL_BODY, '2020-10-30T15:00:56+00:00')])
    assert script.fetch_mercari_to_csv(svc, csv) == 0
    assert read(csv)['item_id'].tolist() == ['m00000000003']
    assert 'b1' in caplog.text


def test_html_only_mail_is_read(tmp_path):
    csv = tmp_path / 'mercari.csv'
    html = '<div>' + SELL_BODY.replace('\n', '<br>') + '</div>'
    svc = FakeService([message('s1', SELL_SUBJECT, '', '2020-10-30T15:00:56+00:00', html=html)])
    assert script.fetch_mercari_to_csv(svc, csv) == 0
    assert read(csv)[['item_id', 'price']].values.tolist() == [['m00000000003', '6000']]


@pytest.mark.parametrize('subject', [
    '【メルカリ】seller01さんがあなたを評価しました',
    '《ご登録記念》¥1,000の商品を【実質1円】でご購入いただけます！',
    '【メルカリストア】商品を発送しました',
])
def test_non_trade_subjects_are_ignored(tmp_path, subject):
    csv = tmp_path / 'mercari.csv'
    svc = FakeService([message('x', subject, BUY_BODY, '2025-06-19T12:13:37+00:00')])
    assert script.fetch_mercari_to_csv(svc, csv) == 0
    assert read(csv).empty


def test_fetch_that_loses_existing_rows_does_not_write(tmp_path):
    csv = tmp_path / 'mercari.csv'
    both = [message('b1', BUY_SUBJECT, BUY_BODY, '2025-06-19T12:13:37+00:00'),
            message('s1', SELL_SUBJECT, SELL_BODY, '2020-10-30T15:00:56+00:00')]
    assert script.fetch_mercari_to_csv(FakeService(both), csv) == 0
    before = csv.read_text()

    partial = FakeService(both[:1])
    assert script.fetch_mercari_to_csv(partial, csv) == 1
    assert csv.read_text() == before
    assert script.fetch_mercari_to_csv(partial, csv, force=True) == 0
    assert len(read(csv)) == 1


def test_refetch_is_idempotent(tmp_path):
    csv = tmp_path / 'mercari.csv'
    svc = FakeService([message('b1', BUY_SUBJECT, BUY_BODY, '2025-06-19T12:13:37+00:00')])
    script.fetch_mercari_to_csv(svc, csv)
    first = csv.read_text()
    script.fetch_mercari_to_csv(svc, csv)
    assert csv.read_text() == first


def test_api_failure_leaves_csv_untouched(tmp_path):
    csv = tmp_path / 'mercari.csv'
    script.fetch_mercari_to_csv(
        FakeService([message('b1', BUY_SUBJECT, BUY_BODY, '2025-06-19T12:13:37+00:00')]), csv)
    before = csv.read_text()
    assert script.fetch_mercari_to_csv(FakeService(error=RuntimeError('boom')), csv) == 1
    assert csv.read_text() == before


def test_unmounted_private_dir_fails_before_api(tmp_path, monkeypatch):
    monkeypatch.setattr(script, 'MERCARI_CSV', BASE_DIR / 'data_not_mounted' / 'mercari.csv')

    def boom(**_):
        raise AssertionError('API を叩いてはいけない')

    monkeypatch.setattr(gmail_client, 'create_service', boom)
    with pytest.raises(FileNotFoundError):
        script.cmd_fetch_mercari(argparse.Namespace(login=False, force=False))
