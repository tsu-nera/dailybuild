"""
定期契約の台帳（lib.mf.contracts）のテスト

固定費の月額は台帳の「金額 ÷ 周期」から出し、MF の明細は照合にだけ使う。
壊れると例外なく黙って誤った月割り・更新日が出るので、日付の丸め（月末 anchor の
ドリフト）、通貨の混算、解約済みの混入、照合の境界を固定する。
"""

import datetime as dt

import pandas as pd
import pytest

from lib.mf import contracts as ct
from lib.mf.store import COL_AMOUNT, COL_CATEGORY, COL_NAME, COL_SUBCATEGORY

D = dt.date
TODAY = D(2026, 10, 17)


def _c(name='x', amount=1000, cycle=1, anchor=D(2026, 1, 15), kind='living', **kw):
    return ct.Contract(name=name, amount=amount, cycle_months=cycle,
                       anchor=anchor, kind=kind, **kw)


def _entries(rows):
    """rows: (YYYY-MM-DD, 内容, 金額[, 大項目, 中項目])。load_entries と同じ列・正規化済み日付。
    分類を省いた行は台帳に無い繰り返しの候補になる分類（通信費 > インターネット）"""
    rows = [r if len(r) == 5 else (*r, '通信費', 'インターネット') for r in rows]
    df = pd.DataFrame(rows, columns=['d', COL_NAME, COL_AMOUNT,
                                     COL_CATEGORY, COL_SUBCATEGORY])
    df['date'] = pd.to_datetime(df['d']).dt.normalize()
    return df.drop(columns='d')


def _write(tmp_path, text):
    p = tmp_path / 'contracts.yaml'
    p.write_text(text, encoding='utf-8')
    return p


# ---- 次回更新日 ----

def test_next_renewal_monthly_month_end_does_not_drift():
    c = _c(cycle=1, anchor=D(2026, 1, 31))
    assert ct.next_renewal(c, D(2026, 2, 1)) == D(2026, 2, 28)
    # 2/28 に丸めた日から数え直すと 3/28 になってしまう
    assert ct.next_renewal(c, D(2026, 3, 1)) == D(2026, 3, 31)
    assert ct.next_renewal(c, D(2026, 4, 1)) == D(2026, 4, 30)


def test_next_renewal_leap_day_anchor():
    c = _c(cycle=12, anchor=D(2028, 2, 29))
    assert ct.next_renewal(c, D(2028, 3, 1)) == D(2029, 2, 28)
    assert ct.next_renewal(c, D(2029, 3, 1)) == D(2030, 2, 28)
    assert ct.next_renewal(c, D(2032, 3, 1)) == D(2033, 2, 28)
    assert ct.renewal_date(c, 4) == D(2032, 2, 29)


def test_next_renewal_yearly_and_biennial():
    yearly = _c(cycle=12, anchor=D(2025, 11, 20))
    assert ct.next_renewal(yearly, TODAY) == D(2026, 11, 20)
    biennial = _c(cycle=24, anchor=D(2025, 3, 1))
    assert ct.next_renewal(biennial, TODAY) == D(2027, 3, 1)


def test_next_renewal_today_counts_and_future_anchor():
    c = _c(cycle=12, anchor=D(2025, 10, 17))
    assert ct.next_renewal(c, D(2026, 10, 17)) == D(2026, 10, 17)
    future = _c(cycle=12, anchor=D(2027, 1, 5))
    assert ct.next_renewal(future, TODAY) == D(2027, 1, 5)
    assert ct.last_expected(future, TODAY) is None


def test_last_expected():
    c = _c(cycle=1, anchor=D(2026, 1, 31))
    assert ct.last_expected(c, D(2026, 3, 15)) == D(2026, 2, 28)
    assert ct.last_expected(c, D(2026, 3, 31)) == D(2026, 3, 31)


# ---- 月割り・合計 ----

def test_monthly_totals_split_by_currency_and_kind_and_skip_ended():
    cs = [
        _c('a', 1000, 1, kind='living'),
        _c('b', 12000, 12, kind='living'),
        _c('c', 24000, 24, kind='business'),
        _c('d', 20, 1, kind='business', currency='USD'),
        _c('e', 99999, 1, kind='living', ended=D(2026, 1, 1)),
    ]
    assert ct.monthly_amount(cs[1]) == 1000
    assert ct.monthly_totals(cs) == {
        ('JPY', 'living'): 2000,
        ('JPY', 'business'): 1000,
        ('USD', 'business'): 20,
    }


def test_monthly_totals_skip_metered():
    cs = [_c('a', 1000, 1), _c('電気', None, 1, billing='metered', mf_match='電気')]
    assert ct.monthly_totals(cs) == {('JPY', 'living'): 1000}


# ---- 従量 ----

def test_metered_actual_uses_median_and_last_12_months():
    c = _c('電気', None, 1, billing='metered', mf_match='デンキ')
    entries = _entries([
        ('2025-10-17', 'デンキ', -99999),    # 12ヶ月の範囲外（境界は含まない）
        ('2026-01-10', 'デンキ', -3000),
        ('2026-02-10', 'デンキ', -1000),
        ('2026-03-10', 'デンキ', -2000),
        ('2026-04-10', 'デンキ', 500),       # 返金（収入）は対象外
    ])
    got = ct.metered_actual(c, entries, TODAY)
    assert (got.charges, got.median, got.total) == (3, 2000, 6000)
    assert got.monthly == 2000


def test_metered_monthly_divides_by_cycle_not_by_window():
    # 範囲の途中で始まった2ヶ月周期の契約。合計 ÷ 12 なら 250 と過小になる
    c = _c('水道', None, 2, billing='metered', mf_match='スイドウ')
    entries = _entries([('2026-10-02', 'スイドウ', -3000)])
    assert ct.metered_actual(c, entries, TODAY).monthly == 1500
    assert ct.metered_actual(c, _entries([]), TODAY) is None


def test_metered_totals_by_kind_and_missing_actual_is_zero():
    cs = [
        _c('電気', None, 1, billing='metered', mf_match='デンキ'),
        _c('水道', None, 2, billing='metered', mf_match='スイドウ'),   # 実績なし
        _c('API', None, 1, kind='business', billing='metered', mf_match='API'),
        _c('固定', 1000, 1),
        _c('旧', None, 1, billing='metered', mf_match='デンキ', ended=D(2026, 1, 1)),
    ]
    entries = _entries([('2026-09-10', 'デンキ', -1200), ('2026-09-10', 'API', -2400)])
    assert ct.metered_totals(cs, entries, TODAY) == {'living': 1200, 'business': 2400}


def test_render_contracts_separates_metered_from_fixed():
    cs = [_c('固定', 1000, 1), _c('電気', None, 1, billing='metered', mf_match='デンキ')]
    entries = _entries([('2026-09-10', 'デンキ', -1200)])
    out = ct.render_contracts(cs, entries, TODAY)
    assert '従量 ¥1,200' in out
    assert '- 固定 JPY: ¥1,000' in out
    assert '- 従量 JPY: ¥1,200' in out
    assert '従量 -' in ct.render_contracts(cs, pd.DataFrame(), TODAY)


METERED = """
- name: 電気
  billing: metered
  cycle_months: 1
  anchor: 2026-01-10
  kind: living
  mf_match: デンキ
"""


def test_load_metered_without_amount(tmp_path):
    (c,) = ct.load_contracts(_write(tmp_path, METERED))
    assert ct.is_metered(c)
    assert c.amount is None


@pytest.mark.parametrize('extra, drop, message', [
    ('  amount: 100\n', None, 'amount を書かない'),
    ('', 'mf_match', 'mf_match'),
    ('  currency: USD\n', None, 'JPY'),
    ('  billing_typo: 1\n', None, '未知のキー'),
])
def test_metered_invalid(tmp_path, extra, drop, message):
    text = METERED + extra
    if drop:
        text = '\n'.join(l for l in text.splitlines() if not l.strip().startswith(drop))
    with pytest.raises(ct.ContractError, match=message):
        ct.load_contracts(_write(tmp_path, text))


def test_fixed_still_requires_amount_and_billing_is_checked(tmp_path):
    no_amount = METERED.replace('  billing: metered\n', '')
    with pytest.raises(ct.ContractError, match='amount'):
        ct.load_contracts(_write(tmp_path, no_amount))
    bad = METERED.replace('metered', 'usage')
    with pytest.raises(ct.ContractError, match='billing'):
        ct.load_contracts(_write(tmp_path, bad))


def test_format_amount_does_not_use_yen_for_other_currency():
    assert ct.format_amount(1234, 'JPY') == '¥1,234'
    assert ct.format_amount(20, 'USD') == '20.00 USD'


# ---- 読み込み・検証 ----

VALID = """
- name: 動画
  amount: 990
  cycle_months: 1
  anchor: 2026-01-31
  kind: living
  ended: 2026-09-30
- name: ドメイン
  amount: 1800
  currency: USD
  cycle_months: 12
  anchor: "2025-11-20"
  kind: business
"""


def test_load_contracts_parses_dates_and_defaults(tmp_path):
    cs = ct.load_contracts(_write(tmp_path, VALID))
    assert cs[0].anchor == D(2026, 1, 31)
    assert cs[0].ended == D(2026, 9, 30)
    assert cs[0].currency == 'JPY'
    assert cs[1].anchor == D(2025, 11, 20)
    assert cs[1].currency == 'USD'


def test_load_contracts_missing_file_tells_how_to_create(tmp_path):
    with pytest.raises(FileNotFoundError, match='contracts.yaml.sample'):
        ct.load_contracts(tmp_path / 'none.yaml')


def test_missing_required_key_names_the_contract(tmp_path):
    p = _write(tmp_path, """
- name: 正常
  amount: 100
  cycle_months: 1
  anchor: 2026-01-01
  kind: living
- name: 欠落くん
  amount: 100
  anchor: 2026-01-01
  kind: living
""")
    with pytest.raises(ct.ContractError) as e:
        ct.load_contracts(p)
    assert 'contracts[1]' in str(e.value)
    assert '欠落くん' in str(e.value)
    assert 'cycle_months' in str(e.value)


@pytest.mark.parametrize('cycle', ['0', '-1', '1.5', '"12"', 'true'])
def test_bad_cycle_months_rejected(tmp_path, cycle):
    p = _write(tmp_path, f"""
- name: 変な周期
  amount: 100
  cycle_months: {cycle}
  anchor: 2026-01-01
  kind: living
""")
    with pytest.raises(ct.ContractError) as e:
        ct.load_contracts(p)
    assert '変な周期' in str(e.value)
    assert 'cycle_months' in str(e.value)


@pytest.mark.parametrize('line', [
    'kind: other', 'amount: 0', 'amount: "100"', 'anchor: yesterday',
    'cycle_months_typo: 1',
])
def test_other_invalid_values_and_unknown_keys_rejected(tmp_path, line):
    key = line.split(':')[0]
    base = {'name': 'n', 'amount': '100', 'cycle_months': '1',
            'anchor': '2026-01-01', 'kind': 'living'}
    base[key] = line.split(': ', 1)[1]
    body = '\n'.join(f"  {k}: {v}" for k, v in base.items())
    p = _write(tmp_path, '- ' + body.lstrip())
    with pytest.raises(ct.ContractError, match=r'contracts\[0\] \(n\)'):
        ct.load_contracts(p)


def test_top_level_must_be_list(tmp_path):
    with pytest.raises(ct.ContractError):
        ct.load_contracts(_write(tmp_path, 'name: x\n'))


def test_nameless_entry_is_identified_by_index(tmp_path):
    p = _write(tmp_path, "- amount: 100\n")
    with pytest.raises(ct.ContractError, match=r'contracts\[0\] \(名前なし\)'):
        ct.load_contracts(p)


# ---- 更新が近い契約 ----

def test_upcoming_renewals_within_changes_the_set():
    near = _c('近い', cycle=12, anchor=D(2025, 11, 20))     # 34日後
    far = _c('遠い', cycle=12, anchor=D(2025, 12, 31))      # 75日後
    monthly = _c('月次', cycle=1, anchor=D(2026, 1, 20))    # 対象外
    ended = _c('解約', cycle=12, anchor=D(2025, 11, 1), ended=D(2026, 1, 1))
    cs = [far, near, monthly, ended]

    def names(within):
        return [c.name for c, _ in ct.upcoming_renewals(cs, TODAY, within)]

    assert names(30) == []
    assert names(45) == ['近い']
    assert names(90) == ['近い', '遠い']


# ---- 照合 ----

def test_missing_charge_detected_and_tolerance():
    c = _c('動画', cycle=1, anchor=D(2026, 1, 1), mf_match='動画')
    # 期待日は 10/01。明細が 9/20（-11日）しか無い → 請求が無い
    far = _entries([('2026-09-20', '動画サービス', -990)])
    assert ct.find_missing_charges([c], far, TODAY) == [(c, D(2026, 10, 1))]
    # ±10日以内なら請求あり
    near = _entries([('2026-10-11', '動画サービス', -990)])
    assert ct.find_missing_charges([c], near, TODAY) == []
    # 明細が全く無い場合も請求が無い
    other = _entries([('2026-10-01', '別の店', -990)])
    assert ct.find_missing_charges([c], other, TODAY) == [(c, D(2026, 10, 1))]


def test_missing_charge_skips_recent_expected_and_ledger_without_match():
    entries = _entries([('2026-01-01', '別の店', -1)])
    recent = _c('直近', cycle=1, anchor=D(2026, 1, 10), mf_match='直近')  # 期待日 10/10 (7日前)
    no_match = _c('照合なし', cycle=1, anchor=D(2026, 1, 1))
    ended = _c('解約', cycle=1, anchor=D(2026, 1, 1), mf_match='解約',
               ended=D(2026, 6, 1))
    assert ct.find_missing_charges([recent, no_match, ended], entries, TODAY) == []


def test_missing_charge_ignores_income_and_uses_plain_substring():
    c = _c('動画', cycle=1, anchor=D(2026, 1, 1), mf_match='A.B')
    entries = _entries([
        ('2026-10-01', '返金 A.B', 990),    # 収入は請求ではない
        ('2026-10-01', 'AxB', -990),         # regex なら '.' に一致してしまう
    ])
    assert ct.find_missing_charges([c], entries, TODAY) == [(c, D(2026, 10, 1))]


def test_charge_after_end_reported():
    c = _c('会員', ended=D(2026, 6, 30), mf_match='会員')
    entries = _entries([
        ('2026-06-10', '会員費', -500),    # 解約前
        ('2026-06-30', '会員費', -500),    # 解約日当日 → 以降に含める
        ('2026-08-10', '会員費', -500),
        ('2026-08-11', '別の店', -500),
    ])
    got = ct.find_charges_after_end([c], entries)
    assert [(d, a) for _, d, a in got] == [(D(2026, 6, 30), 500), (D(2026, 8, 10), 500)]


def test_charge_after_end_ignores_active_contracts():
    c = _c('会員', mf_match='会員')
    entries = _entries([('2026-08-10', '会員費', -500)])
    assert ct.find_charges_after_end([c], entries) == []


def test_unlisted_recurring_candidates():
    listed = _c('動画', mf_match='動画')
    ended = _c('旧会員', mf_match='旧会員', ended=D(2026, 1, 1))
    entries = _entries([
        # 2ヶ月に出る → 候補。直近の金額は最新の行
        ('2026-08-05', 'ジム', -8000),
        ('2026-09-05', 'ジム', -8800),
        # 同月に2回だけ → 1ヶ月扱いで候補外
        ('2026-09-01', 'コンビニ', -300),
        ('2026-09-20', 'コンビニ', -300),
        # 台帳（生きている・解約済み）に一致 → 候補外
        ('2026-08-05', '動画サービス', -990),
        ('2026-09-05', '動画サービス', -990),
        ('2025-08-05', '旧会員費', -500),
        ('2025-09-05', '旧会員費', -500),
        # 24ヶ月より前 → 候補外
        ('2024-01-05', '古い店', -100),
        ('2024-02-05', '古い店', -100),
        # 収入は対象外
        ('2026-08-05', '給与', 300000),
        ('2026-09-05', '給与', 300000),
        # 3ヶ月出る → 月数が多い方が先
        ('2026-07-07', '回線', -900),
        ('2026-08-07', '回線', -900),
        ('2026-09-07', '回線', -1000),
        # 契約の入らない分類（普段の買い物）→ 毎月でも候補外
        ('2026-07-07', '定食屋', -900, '食費', '外食'),
        ('2026-08-07', '定食屋', -900, '食費', '外食'),
        # サブスクは大項目が年で変わるので中項目で拾う
        ('2026-07-20', '音楽B', -500, '趣味・娯楽', 'サブスクリプション'),
        ('2026-08-20', '音楽B', -500, '趣味・娯楽', 'サブスクリプション'),
    ])
    got = ct.find_unlisted_recurring([listed, ended], entries, TODAY)
    assert got == [('回線', 3, 1000), ('ジム', 2, 8800), ('音楽B', 2, 500)]


def test_empty_entries_do_not_crash():
    c = _c(mf_match='x', anchor=D(2026, 1, 1))
    empty = pd.DataFrame()
    assert ct.find_unlisted_recurring([c], empty, TODAY) == []
    assert ct.find_charges_after_end([c], empty) == []
    assert ct.find_missing_charges([c], empty, TODAY) == [(c, D(2026, 10, 1))]


# ---- 生活費の固定・変動 ----

def _bucketed(rows):
    exp = _entries(rows)
    exp[COL_AMOUNT] = exp[COL_AMOUNT].abs()
    exp['bucket'] = exp['date'].dt.strftime('%Y-%m')
    return exp


def test_classify_expenses_uses_ended_contracts_and_first_match_wins():
    cs = [
        _c('家賃', 50000, mf_match='ヤチン'),
        _c('旧家賃', 40000, mf_match='家賃', ended=D(2026, 4, 1)),
        _c('電気', None, billing='metered', mf_match='デンキ'),
        _c('台帳だけ', 100),    # mf_match なしは分類に使わない
    ]
    exp = _bucketed([
        ('2026-03-10', 'エポス 3月分家賃', -40000),
        ('2026-05-27', 'SMBC(ヤチン 家賃', -50000),   # 両方に一致 → 先に書いた家賃
        ('2026-05-10', 'デンキ', -2000),               # 従量は変動
        ('2026-05-11', 'スーパー', -3000),
    ])
    assert list(ct.classify_expenses(exp, cs)) == ['固定', '固定', '変動', '変動']


def test_render_split_rows_sum_and_delta_on_variable():
    cs = [_c('家賃', 50000, mf_match='ヤチン'),
          _c('電気', None, billing='metered', mf_match='デンキ')]
    exp = _bucketed([
        ('2026-08-27', 'ヤチン', -50000),
        ('2026-08-10', 'デンキ', -2000),
        ('2026-08-11', 'スーパー', -10000),
        ('2026-09-11', 'スーパー', -15000),   # 9月は家賃の計上が無い月
    ])
    out = ct.render_split(exp, cs, '月')
    assert '台帳の固定費（生活・月割り）: ¥50,000/月' in out
    rows = {cells[0]: cells[1:] for cells in
            ([c.strip() for c in line.strip('|').split('|')]
             for line in out.splitlines() if line.startswith('| 2026'))}
    assert rows['2026-08'][:3] == ['¥50,000', '¥12,000', '¥62,000']
    # 増減は変動だけで見る（家賃の計上ズレに引きずられない）
    assert rows['2026-09'][3:] == ['+¥3,000', '+25.0%']
