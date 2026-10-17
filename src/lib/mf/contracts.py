"""
定期契約の台帳（config/private/contracts.yaml）の読み込み・計算・照合

台帳が正本で、MF の明細は照合（台帳の漏れ・解約済みの検出）にだけ使う。
固定費の月額は MF の明細集計ではなく「金額 ÷ 周期の月数」の合計で出す
（明細は計上ズレで暴れ、年契約は更新月にしか出ないため）。

通貨は換算せず、合計は通貨ごとに出す。税・社会保険は契約ではないので対象外。
"""

import calendar
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from lib.mf import render
from lib.mf.store import COL_AMOUNT, COL_NAME
from lib.utils.private_data import require_private_path

BASE_DIR = Path(__file__).resolve().parents[3]

# import 時には検証しない（台帳が無い環境でも他の mf.py サブコマンドを動かすため）
CONTRACTS_YAML = BASE_DIR / 'config' / 'private' / 'contracts.yaml'

KINDS = ('living', 'business')
KIND_LABEL = {'living': '生活', 'business': '事業経費'}

REQUIRED_KEYS = ('name', 'amount', 'cycle_months', 'anchor', 'kind')
OPTIONAL_KEYS = ('currency', 'payment', 'mf_match', 'cancel_url', 'ended')

# 照合の許容日数。期待日 ±N 日に明細があれば請求ありとみなす
TOLERANCE_DAYS = 10
# 台帳に無い繰り返し支払いを探す範囲（月）
UNLISTED_MONTHS = 24
# 更新が近い契約として扱う最短の周期（月次契約は毎月更新なので対象外）
UPCOMING_MIN_CYCLE = 12


class ContractError(ValueError):
    """台帳の内容の誤り。メッセージは契約の位置と名前を含む"""


@dataclass(frozen=True)
class Contract:
    name: str
    amount: float
    cycle_months: int
    anchor: dt.date
    kind: str
    currency: str = 'JPY'
    payment: str | None = None
    mf_match: str | None = None
    cancel_url: str | None = None
    ended: dt.date | None = None


# ---- 日付計算 ----

def add_months(d: dt.date, n: int) -> dt.date:
    """暦月を n ヶ月進める。移動先に同じ日が無ければ月末に丸める（1/31+1 → 2/28）"""
    total = d.year * 12 + (d.month - 1) + n
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def renewal_date(c: Contract, k: int) -> dt.date:
    """k 回目の請求日。丸めが累積しないよう必ず anchor から直接求める"""
    return add_months(c.anchor, k * c.cycle_months)


def next_renewal(c: Contract, today: dt.date) -> dt.date:
    """今日以降で最初の請求日（今日が請求日なら今日）"""
    k = 0
    if today > c.anchor:
        months = (today.year - c.anchor.year) * 12 + (today.month - c.anchor.month)
        k = max(months // c.cycle_months - 1, 0)
    while renewal_date(c, k) < today:
        k += 1
    return renewal_date(c, k)


def last_expected(c: Contract, today: dt.date) -> dt.date | None:
    """今日以前で最後の請求日。anchor が未来ならまだ請求は無い"""
    if c.anchor > today:
        return None
    nxt = next_renewal(c, today)
    if nxt == today:
        return today
    k = 0
    while renewal_date(c, k + 1) <= today:
        k += 1
    return renewal_date(c, k)


def monthly_amount(c: Contract) -> float:
    return c.amount / c.cycle_months


# ---- 読み込み・検証 ----

def _label(index: int, name) -> str:
    return f"contracts[{index}] ({name or '名前なし'})"


def _to_date(value, label: str, key: str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise ContractError(f"{label}: {key} は日付（YYYY-MM-DD）で書く: {value!r}")
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise ContractError(f"{label}: {key} は日付（YYYY-MM-DD）で書く: {value!r}")


def _parse_contract(index: int, raw) -> Contract:
    name = raw.get('name') if isinstance(raw, dict) else None
    label = _label(index, name if isinstance(name, str) else None)
    if not isinstance(raw, dict):
        raise ContractError(f"{label}: 1契約はキーと値の組で書く")

    unknown = sorted(set(raw) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if unknown:
        raise ContractError(f"{label}: 未知のキー {unknown}（綴りの誤りの可能性）")
    missing = [k for k in REQUIRED_KEYS if k not in raw or raw[k] is None]
    if missing:
        raise ContractError(f"{label}: 必須キーがない {missing}")

    if not isinstance(name, str) or not name.strip():
        raise ContractError(f"{label}: name は空でない文字列")

    amount = raw['amount']
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise ContractError(f"{label}: amount は正の数: {amount!r}")

    cycle = raw['cycle_months']
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle <= 0:
        raise ContractError(f"{label}: cycle_months は正の整数: {cycle!r}")

    kind = raw['kind']
    if kind not in KINDS:
        raise ContractError(f"{label}: kind は {' / '.join(KINDS)} のどちらか: {kind!r}")

    currency = raw.get('currency', 'JPY')
    if not isinstance(currency, str) or not currency:
        raise ContractError(f"{label}: currency は文字列: {currency!r}")

    for key in ('payment', 'mf_match', 'cancel_url'):
        value = raw.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            raise ContractError(f"{label}: {key} は空でない文字列: {value!r}")

    ended = raw.get('ended')
    return Contract(
        name=name,
        amount=amount,
        cycle_months=cycle,
        anchor=_to_date(raw['anchor'], label, 'anchor'),
        kind=kind,
        currency=currency,
        payment=raw.get('payment'),
        mf_match=raw.get('mf_match'),
        cancel_url=raw.get('cancel_url'),
        ended=None if ended is None else _to_date(ended, label, 'ended'),
    )


def load_contracts(path: Path | None = None) -> list[Contract]:
    """台帳を読んで検証する。path 省略時は config/private/contracts.yaml"""
    if path is None:
        path = require_private_path(CONTRACTS_YAML)
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"契約台帳がありません: {path}\n"
            "cp config/contracts.yaml.sample config/private/contracts.yaml "
            "で作って中身を実データに直す")

    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if data is None:
        return []
    if not isinstance(data, list):
        raise ContractError(f"{path}: 台帳の最上位は契約のリストで書く")
    return [_parse_contract(i, raw) for i, raw in enumerate(data)]


# ---- 集計 ----

def active_contracts(contracts: list[Contract]) -> list[Contract]:
    """ended が設定された契約は日付に関わらず対象外"""
    return [c for c in contracts if c.ended is None]


def monthly_totals(contracts: list[Contract]) -> dict[tuple[str, str], float]:
    """(通貨, kind) ごとの月割り合計。通貨は換算せず足さない"""
    totals: dict[tuple[str, str], float] = {}
    for c in active_contracts(contracts):
        key = (c.currency, c.kind)
        totals[key] = totals.get(key, 0.0) + monthly_amount(c)
    return totals


def upcoming_renewals(contracts: list[Contract], today: dt.date,
                      within: int) -> list[tuple[Contract, dt.date]]:
    """cycle_months >= 12 で、次回更新日が within 日以内のもの（日付順）"""
    out = []
    for c in active_contracts(contracts):
        if c.cycle_months < UPCOMING_MIN_CYCLE:
            continue
        nxt = next_renewal(c, today)
        if 0 <= (nxt - today).days <= within:
            out.append((c, nxt))
    return sorted(out, key=lambda x: (x[1], x[0].name))


# ---- MF 明細との照合 ----

def _expenses(entries: pd.DataFrame) -> pd.DataFrame:
    if entries is None or entries.empty:
        return pd.DataFrame(columns=[COL_NAME, COL_AMOUNT, 'date'])
    return entries[entries[COL_AMOUNT] < 0]


def _matching(expenses: pd.DataFrame, mf_match: str) -> pd.DataFrame:
    if expenses.empty:
        return expenses
    mask = expenses[COL_NAME].astype(str).str.contains(mf_match, regex=False)
    return expenses[mask]


def find_missing_charges(contracts: list[Contract], entries: pd.DataFrame,
                         today: dt.date,
                         tolerance_days: int = TOLERANCE_DAYS
                         ) -> list[tuple[Contract, dt.date]]:
    """直近の期待請求日の ±tolerance_days に一致する支出が無い契約。

    期待日が今日から tolerance_days 日以内だと、引き落としが遅れているだけかも
    しれないので判定しない。
    """
    expenses = _expenses(entries)
    out = []
    for c in active_contracts(contracts):
        if not c.mf_match:
            continue
        expected = last_expected(c, today)
        if expected is None or (today - expected).days < tolerance_days:
            continue
        hits = _matching(expenses, c.mf_match)
        if hits.empty:
            out.append((c, expected))
            continue
        gap = (hits['date'] - pd.Timestamp(expected)).abs()
        if not (gap <= pd.Timedelta(days=tolerance_days)).any():
            out.append((c, expected))
    return out


def find_charges_after_end(contracts: list[Contract], entries: pd.DataFrame
                           ) -> list[tuple[Contract, dt.date, float]]:
    """ended 以降に一致する支出（解約したはずの契約の請求）。金額は正"""
    expenses = _expenses(entries)
    out = []
    for c in contracts:
        if c.ended is None or not c.mf_match:
            continue
        hits = _matching(expenses, c.mf_match)
        hits = hits[hits['date'] >= pd.Timestamp(c.ended)]
        for _, row in hits.iterrows():
            out.append((c, row['date'].date(), abs(float(row[COL_AMOUNT]))))
    return out


def find_unlisted_recurring(contracts: list[Contract], entries: pd.DataFrame,
                            today: dt.date, months: int = UNLISTED_MONTHS
                            ) -> list[tuple[str, int, float]]:
    """台帳に無い繰り返し支払いの候補: (内容, 出現月数, 直近の金額)。

    固定か変動かは判定しない（出現率では判定できない）。候補を見て台帳に足す。
    解約済みの契約の mf_match も除外に使う（解約後の請求は別の節で出すため）。
    """
    expenses = _expenses(entries)
    if expenses.empty:
        return []
    start = pd.Timestamp(add_months(today, -months))
    window = expenses[(expenses['date'] > start)
                      & (expenses['date'] <= pd.Timestamp(today))]
    matches = [c.mf_match for c in contracts if c.mf_match]

    out = []
    for name, group in window.groupby(COL_NAME):
        name = str(name)
        if any(m in name for m in matches):
            continue
        n_months = group['date'].dt.strftime('%Y-%m').nunique()
        if n_months < 2:
            continue
        latest = group.sort_values('date').iloc[-1]
        out.append((name, n_months, abs(float(latest[COL_AMOUNT]))))
    return sorted(out, key=lambda x: (-x[1], x[0]))


# ---- 表示 ----

def format_amount(amount: float, currency: str) -> str:
    if currency == 'JPY':
        return render.format_yen(amount)
    return f"{amount:,.2f} {currency}"


def format_cycle(months: int) -> str:
    return f"{months}ヶ月"


def _table(columns: list[str], rows: list[list]) -> str:
    return pd.DataFrame(rows, columns=columns).to_markdown(index=False)


def render_contracts(contracts: list[Contract], today: dt.date) -> str:
    active = active_contracts(contracts)
    if not active:
        return '# 定期契約\n\nなし'

    blocks = ['# 定期契約']
    for kind in KINDS:
        group = [c for c in active if c.kind == kind]
        if not group:
            continue
        rows = [[render.truncate(c.name),
                 format_amount(c.amount, c.currency),
                 format_cycle(c.cycle_months),
                 format_amount(monthly_amount(c), c.currency),
                 next_renewal(c, today).isoformat(),
                 c.payment or '-']
                for c in sorted(group, key=lambda c: c.name)]
        blocks.append(f"## {KIND_LABEL[kind]}\n\n" + _table(
            ['名前', '金額', '周期', '月割り', '次回更新', '支払い'], rows))

    totals = monthly_totals(contracts)
    lines = ['## 月割り合計', '']
    for currency in sorted({cur for cur, _ in totals}):
        parts = [f"{KIND_LABEL[k]} {format_amount(totals[(currency, k)], currency)}"
                 for k in KINDS if (currency, k) in totals]
        total = sum(v for (cur, _), v in totals.items() if cur == currency)
        lines.append(f"- {currency}: {format_amount(total, currency)}"
                     f"（{' / '.join(parts)}）")
    blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)


def render_upcoming(contracts: list[Contract], today: dt.date, within: int) -> str:
    items = upcoming_renewals(contracts, today, within)
    head = f"## 更新が近い契約（{within}日以内）"
    if not items:
        return f"{head}\n\nなし"
    rows = [[render.truncate(c.name), format_amount(c.amount, c.currency),
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
                       [[render.truncate(c.name), d.isoformat(), c.mf_match]
                        for c, d in missing])
    else:
        body += 'なし'
    blocks.append(body)

    body = '### 解約後の請求\n\n'
    if after_end:
        body += _table(['名前', '解約日', '請求日', '金額'],
                       [[render.truncate(c.name), c.ended.isoformat(),
                         d.isoformat(), format_amount(amt, c.currency)]
                        for c, d, amt in after_end])
    else:
        body += 'なし'
    blocks.append(body)
    return '\n\n'.join(blocks)


def render_unlisted(contracts: list[Contract], entries: pd.DataFrame,
                    today: dt.date) -> str:
    head = f"## 台帳に無い繰り返し支払いの候補（直近{UNLISTED_MONTHS}ヶ月）"
    items = find_unlisted_recurring(contracts, entries, today)
    if not items:
        return f"{head}\n\nなし"
    rows = [[render.truncate(name), n, render.format_yen(amount)]
            for name, n, amount in items]
    return f"{head}\n\n" + _table(['内容', '出現月数', '直近の金額'], rows)
