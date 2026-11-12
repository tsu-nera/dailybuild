"""お金の画面の B/S: 持ち物の相場の欠測を0や買値で捏造しないこと・持っていない日に数えないこと"""

from lib.assets import build

MF = """﻿日付,合計（円）,預金・現金（円）,投資信託（円）,暗号資産（円）,FX（円）,ポイント（円）
2026/10/31,1000,600,300,100,0,0
2026/11/10,1100,600,400,100,0,0
2026/11/12,1200,700,400,100,0,0
2026/12/12,1300,800,400,100,0,0
"""
ITEMS = """key,name,category,subcategory,status,location,acquired_on,disposed_on,purchase_price,purchase_from,market_price,note
a,ヘッドホン,家電,,owned,,2020-01-01,,16000,,,
b,時計,計測機器,,disposed,,2024-01-01,2026-12-01,20000,,,
c,自転車,スポーツ用品,,owned,,2026-11-20,,100000,,,
d,相場なし,家電,,owned,,2020-01-01,,3000,,,
"""
MARKET = """date,key,name,median,count,query
2026-11-10,a,ヘッドホン,7000,100,q
2026-11-10,b,時計,11000,100,q
2026-11-10,c,自転車,90000,9,q
2026-12-12,a,ヘッドホン,,2,q
"""


def _build(tmp_path):
    for name, text in (('mf.csv', MF), ('items.csv', ITEMS), ('market.csv', MARKET)):
        (tmp_path / name).write_text(text, encoding='utf-8')
    rows, goods = build(tmp_path / 'mf.csv', tmp_path / 'items.csv', tmp_path / 'market.csv')
    return {r['date']: r for r in rows}, {g['key']: g for g in goods}


def test_before_first_market_check_goods_are_blank_not_zero(tmp_path):
    rows, _ = _build(tmp_path)
    r = rows['2026-10-31']
    assert (r['total_financial'], r['cash']) == (1000, 600)
    assert (r['goods_market'], r['goods_count'], r['total']) == (None, None, None)


def test_only_items_held_on_the_day_are_counted(tmp_path):
    rows, _ = _build(tmp_path)
    # 11-12: a と b（c はまだ買っていない）
    assert (rows['2026-11-12']['goods_market'], rows['2026-11-12']['goods_count']) == (18000, 2)
    assert rows['2026-11-12']['total'] == 1200 + 18000
    # 12-12: b は手放した、c は買った後
    assert (rows['2026-12-12']['goods_market'], rows['2026-12-12']['goods_count']) == (97000, 2)


def test_blank_median_keeps_previous_price(tmp_path):
    rows, goods = _build(tmp_path)
    assert goods['a']['market_price'] == 7000
    assert goods['a']['last_checked'] == '2026-12-12'
    assert rows['2026-12-12']['goods_market'] == 7000 + 90000


def test_item_without_market_is_listed_but_not_summed(tmp_path):
    rows, goods = _build(tmp_path)
    assert goods['d']['market_price'] is None and goods['d']['diff'] is None
    assert goods['d']['purchase_price'] == 3000
    assert 'b' not in goods  # 手放した物は今の一覧に出さない
    assert goods['a']['diff'] == 7000 - 16000
    assert rows['2026-11-12']['goods_count'] == 2
