"""
MF 口座別残高（/bs/portfolio・/bs/liability → data/mf/balances.csv）のテスト

balances.csv は変わった行だけを積むので、1度書き損じると以後の日次がすべてずれる。
「欠測を捏造しない（–円を0にしない・取れなかったページの口座を消えた扱いにしない）」と
「二重に入れない（同じ日の取り直し・同名の口座）」をここで固定する。HTML は実ページの形を真似た合成。
"""

import datetime as dt
import io

import pandas as pd

from lib import balances as daily_balances
from lib.mf import store
from lib.mf.balances import Balance, parse_liability, parse_pages, parse_portfolio

DEPO_HEAD = '<tr><th>種類・名称<a href="#"></a></th><th>残高</th><th>保有金融機関</th><th>変更</th></tr>'
CALENDAR = ('<table class="table-condensed"><thead><tr><th class="prev">‹</th><th colspan="5">11月 2026</th>'
            '<th class="next">›</th></tr></thead><tbody><tr><td>1</td><td>2</td></tbody></table>')


def _depo_rows(*rows):
    return ''.join(f'<tr><td>{n}</td><td class="number">{v}</td><td>{i}</td><td class="button"></td></tr>'
                   for n, v, i in rows)


def _section(title, head, body):
    return (f'<section><h1 class="heading-normal">{title}</h1><section><h1 class="heading-small">合計：1円</h1>'
            f'</section><table><thead>{head}</thead><tbody>{body}</tbody></table></section>')


def _page(*sections):
    summary = '<h1>資産構成</h1><table><tr><th>預金・現金</th><td>1円</td></tr></table>'
    return f'<html><body>{summary}{"".join(sections)}{CALENDAR}</body></html>'


def test_種類は表の順番でなく直前の見出しで決まり_カレンダーは読まない():
    html = _page(
        _section('暗号資産', DEPO_HEAD, _depo_rows(('BTC残高', '355円', '取引所A'))),
        _section('預金・現金', DEPO_HEAD, _depo_rows(('普通', '1,000円', '銀行A'))),
        _section('ポイント',
                 '<tr><th>名称</th><th>種類</th><th>ポイント・マイル数</th><th>換算レート</th><th>現在の価値</th>'
                 '<th>有効期限</th><th>保有金融機関</th></tr>',
                 '<tr><td>P</td><td>ポイント</td><td>44ポイント</td><td>1</td><td>44円</td>'
                 '<td>2027/01/31</td><td>店A</td></tr>'),
    )
    result = parse_portfolio(html)
    assert [(r.kind, r.name, r.value) for r in result.rows] == [
        ('暗号資産', 'BTC残高', 355), ('預金・現金', '普通', 1000), ('ポイント', 'P', 44)]
    assert result.rows[2].quantity == 44 and result.rows[2].expires == '2027/01/31'


def test_表の中のモーダルの見出しで種類が変わらない():
    modal = '<div class="modal"><h3>資産の更新</h3></div>'
    body = (f'<tr><td>普通</td><td>1円</td><td>銀行A</td><td class="button">{modal}</td></tr>'
            '<tr><td>定期</td><td>2円</td><td>銀行A</td><td class="button"></td></tr>')
    result = parse_portfolio(_page(_section('預金・現金', DEPO_HEAD, body)))
    assert [(r.kind, r.name) for r in result.rows] == [('預金・現金', '普通'), ('預金・現金', '定期')]


def test_列は見出しの文字列で引く():
    head = ('<tr><th>銘柄名</th><th>保有金融機関</th><th>評価額</th><th>評価損益</th><th>保有数</th>'
            '<th>平均取得単価</th></tr>')
    body = ('<tr><td>ファンドA</td><td>証券A</td><td>830,737円</td>'
            '<td><span class="minus-color">-1,426円\n</span></td><td>262,327</td><td>1</td></tr>')
    [row] = parse_portfolio(_page(_section('投資信託', head, body))).rows
    assert (row.institution, row.value, row.unrealized_gain, row.quantity) == ('証券A', 830737, -1426, 262327)


def test_金額の_ダッシュ円_は0でなく欠測():
    body = _depo_rows(('普通', '–円', '銀行A'), ('定期', '-円', '銀行A'), ('外貨', '', '銀行A'))
    rows = parse_portfolio(_page(_section('預金・現金', DEPO_HEAD, body))).rows
    assert [r.value for r in rows] == [None, None, None]


LIABILITY_HEAD = '<tr><th>種類</th><th>名称・説明</th><th>残高</th><th>保有金融機関</th><th>変更</th></tr>'


def _liability(*rows):
    body = ''.join(f'<tr><td>カード</td><td>{n}</td><td>{v}</td><td>{i}</td><td></td></tr>' for n, v, i in rows)
    return (f'<h1>負債構成</h1><table><tr><th>カード</th><td>1円</td></tr></table>'
            f'<h1>負債詳細</h1><table><thead>{LIABILITY_HEAD}</thead><tbody>{body}</tbody></table>{CALENDAR}')


def test_同じ金融機関_同じ名称の負債は出現順の_seq_で分ける():
    rows = parse_liability(_liability(('ご利用残高', '100円', 'カードA'), ('ご利用残高', '200円', 'カードA'),
                                      ('ご利用残高', '0円', 'カードB'))).rows
    assert [(r.institution, r.seq, r.value) for r in rows] == [('カードA', 1, 100), ('カードA', 2, 200),
                                                               ('カードB', 1, 0)]
    assert {r.kind for r in rows} == {'負債'} and rows[0].category == 'カード'


def test_取れなかった_形が違う_0件のページは読めた種類に入れない():
    bad = _page(_section('預金・現金', '<tr><th>名称</th><th>保有金融機関</th></tr>', ''))
    empty = _page(_section('預金・現金', DEPO_HEAD, ''))
    for portfolio in (None, bad, empty):
        _, kinds, warnings = parse_pages(portfolio, _liability(('ご利用残高', '1円', 'カードA')))
        assert kinds == {'負債'} and warnings


# --- 保存（変わった行だけ） ---

D1, D2, D3 = dt.date(2026, 11, 14), dt.date(2026, 11, 15), dt.date(2026, 11, 16)
PORTFOLIO = {'預金・現金', '投資信託', '暗号資産', 'ポイント'}


def _b(name, value, kind='預金・現金', inst='銀行A', seq=1, **kw):
    return Balance(kind=kind, institution=inst, name=name, seq=seq, value=value, **kw)


def _save(tmp_path, monkeypatch, runs):
    monkeypatch.setattr(store, 'BALANCES_CSV', tmp_path / 'balances.csv')
    for day, rows, kinds in runs:
        store.save_balances(rows, kinds, day, io.StringIO())
    return pd.read_csv(tmp_path / 'balances.csv', dtype=str, keep_default_na=False,
                       encoding=store.OUTPUT_ENCODING).to_dict('records')


def _brief(rows):
    return [(r['date'], r['name'], r['seq'], r['status'], r['value']) for r in rows]


def test_前回と変わった行だけ書く(tmp_path, monkeypatch):
    saved = _save(tmp_path, monkeypatch, [
        (D1, [_b('普通', 100), _b('定期', 500)], PORTFOLIO),
        (D2, [_b('普通', 100), _b('定期', 600)], PORTFOLIO),
        (D3, [_b('普通', 100), _b('定期', 600)], PORTFOLIO),
    ])
    assert _brief(saved) == [('2026-11-14', '定期', '1', 'ok', '500'), ('2026-11-14', '普通', '1', 'ok', '100'),
                             ('2026-11-15', '定期', '1', 'ok', '600')]


def test_付帯の欄だけ変わっても書く(tmp_path, monkeypatch):
    saved = _save(tmp_path, monkeypatch, [
        (D1, [_b('F', 100, kind='投資信託', quantity=10)], PORTFOLIO),
        (D2, [_b('F', 100, kind='投資信託', quantity=11)], PORTFOLIO),
    ])
    assert [r['quantity'] for r in saved] == ['10', '11']


def test_同じ日に2回取ったらその日の行を置き換える(tmp_path, monkeypatch):
    saved = _save(tmp_path, monkeypatch, [
        (D1, [_b('普通', 100)], PORTFOLIO),
        (D2, [_b('普通', 200)], PORTFOLIO),
        (D2, [_b('普通', 100)], PORTFOLIO),   # 取り直したら前日と同じに戻った
    ])
    assert _brief(saved) == [('2026-11-14', '普通', '1', 'ok', '100')]


def test_同名の口座は_seq_ごとに別のキー(tmp_path, monkeypatch):
    rows = [_b('ご利用残高', 100, kind='負債', seq=1), _b('ご利用残高', 200, kind='負債', seq=2)]
    saved = _save(tmp_path, monkeypatch, [(D1, rows, {'負債'}), (D2, rows, {'負債'})])
    assert [(r['seq'], r['value']) for r in saved] == [('1', '100'), ('2', '200')]


def test_欠測は0でなく_missing_で_続く間は書かない(tmp_path, monkeypatch):
    saved = _save(tmp_path, monkeypatch, [
        (D1, [_b('普通', 100)], PORTFOLIO),
        (D2, [_b('普通', None)], PORTFOLIO),
        (D3, [_b('普通', None)], PORTFOLIO),
    ])
    assert _brief(saved) == [('2026-11-14', '普通', '1', 'ok', '100'), ('2026-11-15', '普通', '1', 'missing', '')]


def test_消えたキーは_gone_を1行_再び現れたら通常の行(tmp_path, monkeypatch):
    saved = _save(tmp_path, monkeypatch, [
        (D1, [_b('普通', 100), _b('定期', 500)], PORTFOLIO),
        (D2, [_b('普通', 100)], PORTFOLIO),
        (D3, [_b('普通', 100), _b('定期', 500)], PORTFOLIO),
    ])
    assert [r for r in _brief(saved) if r[1] == '定期'] == [
        ('2026-11-14', '定期', '1', 'ok', '500'), ('2026-11-15', '定期', '1', 'gone', ''),
        ('2026-11-16', '定期', '1', 'ok', '500')]


def test_読めなかったページの種類には_gone_を書かず今日の行も消さない(tmp_path, monkeypatch):
    card = _b('ご利用残高', 300, kind='負債', inst='カードA')
    saved = _save(tmp_path, monkeypatch, [
        (D1, [_b('普通', 100), card], PORTFOLIO | {'負債'}),
        (D2, [_b('普通', 100), _b('ご利用残高', 400, kind='負債', inst='カードA')], PORTFOLIO | {'負債'}),
        (D2, [_b('普通', 100)], PORTFOLIO),   # 同じ日の2回目は liability が取れなかった
        (D3, [], set()),                       # 両ページとも取れなかった
    ])
    assert _brief(saved) == [('2026-11-14', 'ご利用残高', '1', 'ok', '300'), ('2026-11-14', '普通', '1', 'ok', '100'),
                             ('2026-11-15', 'ご利用残高', '1', 'ok', '400')]


# --- 日次への復元（dashboard 側） ---

def _rec(date, name, status, value, kind='預金・現金'):
    return {'date': date, 'kind': kind, 'institution': '銀行A', 'name': name, 'seq': '1', 'status': status,
            'value': value, 'quantity': '', 'unrealized_gain': '', 'category': '', 'expires': ''}


def test_日次は直前の値を引き継ぎ_gone_以降は持たず_missing_は合計から外す():
    rows = [_rec('2026-11-14', '普通', 'ok', '100'), _rec('2026-11-14', '定期', 'ok', '500'),
            _rec('2026-11-14', '外貨', 'ok', '50'), _rec('2026-11-14', 'ご利用残高', 'ok', '30', kind='負債'),
            _rec('2026-11-15', '定期', 'gone', ''),
            _rec('2026-11-16', '普通', 'missing', '')]
    days = daily_balances.daily(rows, dt.date(2026, 11, 17))
    assert [(d['date'], d['cash'], d['liabilities'], d['net_worth'], d['missing_count']) for d in days] == [
        ('2026-11-14', 650, 30, 620, 0), ('2026-11-15', 150, 30, 120, 0),
        ('2026-11-16', 50, 30, 20, 1), ('2026-11-17', 50, 30, 20, 1)]
    assert days[0]['crypto'] == 0
    assert [(r['name'], r['status'], r['value']) for r in daily_balances.latest(rows)] == [
        ('外貨', 'ok', 50), ('普通', 'missing', None), ('ご利用残高', 'ok', 30)]


def test_負債のページの最初の行より前は負債も純資産も空():
    rows = [_rec('2026-11-14', '普通', 'ok', '100'), _rec('2026-11-15', 'ご利用残高', 'ok', '30', kind='負債')]
    days = daily_balances.daily(rows, dt.date(2026, 11, 15))
    assert [(d['liabilities'], d['net_worth']) for d in days] == [(None, None), (30, 70)]
