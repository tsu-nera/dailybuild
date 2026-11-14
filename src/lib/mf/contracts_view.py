"""定期契約の台帳の表示（markdown）。

計算と照合は lib.mf.contracts、ここは表に組むだけ。
"""

import datetime as dt

import pandas as pd

from lib.mf import render
from lib.mf.contracts import (
    KIND_LABEL, KINDS, METERED_MONTHS, SPLIT_LABELS, SPLIT_VARIABLE, UNLISTED_MONTHS, Contract,
    active_contracts, classify_expenses, find_charges_after_end, find_missing_charges,
    find_unlisted_recurring, insurance_contracts, is_metered, metered_actual,
    metered_totals, missing_insurance_fields, monthly_amount, monthly_totals,
    next_renewal, upcoming_renewals,
)
from lib.mf.store import COL_AMOUNT


def render_split(expenses: pd.DataFrame, contracts: list[Contract],
                 bucket_name: str) -> str:
    """bucket ごとの生活費を 固定 / 変動 に割った表。

    expenses は render.expenses() 済み（金額が正）で bucket 列を持つもの。
    明細の「固定」は計上月がずれるので、増減は「変動」で見る。固定費の水準は台帳の月割り。
    """
    df = expenses.assign(split=classify_expenses(expenses, contracts))
    table = (df.pivot_table(index='bucket', columns='split', values=COL_AMOUNT,
                            aggfunc='sum', fill_value=0)
             .reindex(columns=list(SPLIT_LABELS), fill_value=0)
             .sort_index())
    variable = table[SPLIT_VARIABLE]
    prev = variable.shift(1)

    out = pd.DataFrame({label: table[label].map(render.format_yen) for label in SPLIT_LABELS})
    out['計'] = table.sum(axis=1).map(render.format_yen)
    out[f'{SPLIT_VARIABLE}Δ'] = (variable - prev).map(render.format_delta)
    out['Δ%'] = [render.format_delta_pct(c, p) for c, p in zip(variable, prev)]
    if len(table) == 1:
        out = out.drop(columns=[f'{SPLIT_VARIABLE}Δ', 'Δ%'])
    out.index.name = bucket_name

    fixed = monthly_totals(contracts).get(('JPY', 'living'), 0.0)
    note = (f"台帳の固定費（生活・月割り）: {render.format_yen(fixed)}/月。"
            "明細の固定は計上月がずれるので、増減は変動で見る。"
            "従量（光熱・通話料）と台帳に無い過去の契約は変動に入る")
    return f"{note}\n\n{out.to_markdown()}"


# ---- 表示 ----

def format_amount(amount: float, currency: str) -> str:
    if currency == 'JPY':
        return render.format_yen(amount)
    return f"{amount:,.2f} {currency}"


def format_cycle(months: int) -> str:
    return f"{months}ヶ月"


def _table(columns: list[str], rows: list[list], **kwargs) -> str:
    return pd.DataFrame(rows, columns=columns).to_markdown(index=False, **kwargs)


def _amount_cells(c: Contract, entries: pd.DataFrame, today: dt.date) -> list[str]:
    """一覧の「金額」「月割り」。従量は実績の中央値と月平均"""
    if not is_metered(c):
        return [format_amount(c.amount, c.currency),
                format_amount(monthly_amount(c), c.currency)]
    actual = metered_actual(c, entries, today)
    if actual is None:
        return ['従量 -', '-']
    return [f"従量 {render.format_yen(actual.median)}",
            render.format_yen(actual.monthly)]


def _kind_breakdown(totals: dict[str, float], fmt) -> str:
    return ' / '.join(f"{KIND_LABEL[k]} {fmt(totals[k])}" for k in KINDS if k in totals)


def render_contracts(contracts: list[Contract], entries: pd.DataFrame,
                     today: dt.date) -> str:
    active = active_contracts(contracts)
    if not active:
        return '# 定期契約\n\nなし'

    blocks = ['# 定期契約']
    for kind in KINDS:
        group = [c for c in active if c.kind == kind]
        if not group:
            continue
        rows = [[render.truncate(c.name),
                 *_amount_cells(c, entries, today),
                 format_cycle(c.cycle_months),
                 next_renewal(c, today).isoformat(),
                 c.payment or '-']
                for c in sorted(group, key=lambda c: c.name)]
        blocks.append(f"## {KIND_LABEL[kind]}\n\n" + _table(
            ['名前', '金額', '月割り', '周期', '次回更新', '支払い'], rows))

    totals = monthly_totals(contracts)
    lines = ['## 月割り合計', '']
    for currency in sorted({cur for cur, _ in totals}):
        by_kind = {k: v for (cur, k), v in totals.items() if cur == currency}
        lines.append(
            f"- 固定 {currency}: {format_amount(sum(by_kind.values()), currency)}"
            f"（{_kind_breakdown(by_kind, lambda v: format_amount(v, currency))}）")
    metered = metered_totals(contracts, entries, today)
    if metered:
        lines.append(
            f"- 従量 JPY: {render.format_yen(sum(metered.values()))}"
            f"（{_kind_breakdown(metered, render.format_yen)}）")
        lines += ['', f"従量の金額は直近{METERED_MONTHS}ヶ月の請求1回の中央値、"
                      "月割りは1回の平均 ÷ 周期。固定とは足さない"]
    blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def render_upcoming(contracts: list[Contract], today: dt.date, within: int) -> str:
    items = upcoming_renewals(contracts, today, within)
    head = f"## 更新が近い契約（{within}日以内）"
    if not items:
        return f"{head}\n\nなし"
    rows = [[render.truncate(c.name),
             '従量' if is_metered(c) else format_amount(c.amount, c.currency),
             nxt.isoformat(), f"{(nxt - today).days}日後", c.cancel_url or '-']
            for c, nxt in items]
    return f"{head}\n\n" + _table(
        ['名前', '金額', '更新日', '残り', '解約・管理'], rows)


def render_reconciliation(contracts: list[Contract], entries: pd.DataFrame,
                          today: dt.date) -> str:
    missing = find_missing_charges(contracts, entries, today)
    after_end = find_charges_after_end(contracts, entries)

    blocks = ['## 照合']
    body = '### 請求が無い\n\n'
    if missing:
        body += _table(['名前', '期待日', '内容の一致文字列'],
                       [[render.truncate(c.name), d.isoformat(), ' / '.join(c.patterns)]
                        for c, d in missing])
    else:
        body += 'なし'
    blocks.append(body)

    body = '### 解約後の請求\n\n'
    if after_end:
        body += _table(['名前', '解約日', '請求日', '金額'],
                       [[render.truncate(c.name), c.ended.isoformat(),
                         d.isoformat(), render.format_yen(amt)]
                        for c, d, amt in after_end])
    else:
        body += 'なし'
    blocks.append(body)
    return '\n\n'.join(blocks)


def render_unlisted(contracts: list[Contract], entries: pd.DataFrame,
                    today: dt.date) -> str:
    head = (f"## 台帳に無い繰り返し支払いの候補"
            f"（直近{UNLISTED_MONTHS}ヶ月・契約が入り得る分類のみ）")
    items = find_unlisted_recurring(contracts, entries, today)
    if not items:
        return f"{head}\n\nなし"
    rows = [[render.truncate(name), n, render.format_yen(amount), last.isoformat()]
            for name, n, amount, last in items]
    return f"{head}\n\n" + _table(['内容', '出現月数', '直近の金額', '最終請求'], rows)


# ---- 保険 ----

DEDUCTION_LABEL = {'life': '生命保険料', 'earthquake': '地震保険料'}


def _insurance_next(c: Contract, today: dt.date) -> tuple[dt.date, str]:
    """次回の日付と表示。満期（term_end）があればそちら、無ければ次回更新"""
    if c.insurance.term_end is not None:
        return c.insurance.term_end, f"満期 {c.insurance.term_end.isoformat()}"
    nxt = next_renewal(c, today)
    return nxt, f"更新 {nxt.isoformat()}"


def render_insurance(contracts: list[Contract], today: dt.date,
                     deduction_only: bool = False) -> str:
    """保険の一覧と、事故・請求に要る欄の未記入。MF の明細は使わない"""
    head = '# 保険（控除あり）' if deduction_only else '# 保険'
    items = insurance_contracts(contracts, deduction_only)
    if not items:
        what = '控除のある保険' if deduction_only else '保険（insurance 付きの契約）'
        return f"{head}\n\n台帳に{what}がない"

    items = sorted(items, key=lambda c: (_insurance_next(c, today)[0], c.name))
    rows = []
    for c in items:
        ins = c.insurance
        yearly = ('-' if is_metered(c)
                  else format_amount(c.amount * 12 / c.cycle_months, c.currency))
        rows.append([render.truncate(c.name), ins.insurer or '-', ins.policy_no or '-',
                     yearly, _insurance_next(c, today)[1],
                     DEDUCTION_LABEL.get(ins.deduction, '-')])
    # 証券番号が全行数字だけだと tabulate が数として読み、先頭の0を落とす
    blocks = [head, _table(['名前', '保険会社', '証券番号', '年額', '次回', '控除'], rows,
                           disable_numparse=True)]

    missing = [(c, m) for c in items if (m := missing_insurance_fields(c))]
    if missing:
        blocks.append('## 未記入\n\n'
                      + '\n'.join(f"- {c.name}: {', '.join(m)}" for c, m in missing))
    return '\n\n'.join(blocks)
