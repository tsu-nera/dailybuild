"""
定期契約の台帳の insurance キー（保険の中身）の型と検証

保険も台帳（lib.mf.contracts）が正本で、証券番号・補償・連絡先は契約1件に同居させる
（別ファイルにすると name の同期が要る）。細部の補償は書き写さず、docs の証書画像を正本にする。

このモジュールは contracts に依存しない。検証の誤りは ValueError で投げ、
契約の位置と名前を付けて ContractError にするのは contracts 側。
"""

import datetime as dt
from dataclasses import dataclass

STR_KEYS = ('insurer', 'product', 'policy_no', 'insured', 'mypage', 'docs')
LIST_KEYS = ('coverage', 'contact')
INSURANCE_KEYS = (*STR_KEYS, *LIST_KEYS, 'term_end', 'deduction')
# 控除の種類。life: 生命保険料控除、earthquake: 地震保険料控除
DEDUCTIONS = ('life', 'earthquake')
# 事故・請求のときに無いと困る欄。欠けていれば一覧で「未記入」として出す
INSURANCE_REQUIRED_FOR_CLAIM = ('insurer', 'policy_no', 'contact')


@dataclass(frozen=True)
class Insurance:
    insurer: str | None = None
    product: str | None = None
    policy_no: str | None = None     # 先頭0を落とさないよう文字列
    insured: str | None = None       # 本人なら None
    coverage: tuple[str, ...] = ()
    term_end: dt.date | None = None  # 自動更新なら None
    contact: tuple[str, ...] = ()
    mypage: str | None = None
    deduction: str | None = None     # DEDUCTIONS のどれか
    docs: str | None = None


def _date(value, key: str) -> dt.date:
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError(f"insurance.{key} は日付（YYYY-MM-DD）で書く: {value!r}")


def parse_insurance(raw) -> Insurance:
    """台帳の insurance の値を検証して Insurance にする。誤りは ValueError"""
    if not isinstance(raw, dict):
        raise ValueError(f"insurance はキーと値の組で書く: {raw!r}")

    unknown = sorted(set(raw) - set(INSURANCE_KEYS))
    if unknown:
        raise ValueError(f"insurance に未知のキー {unknown}（綴りの誤りの可能性）")

    policy_no = raw.get('policy_no')
    if isinstance(policy_no, (int, float)) and not isinstance(policy_no, bool):
        # policy_no: 0123 は YAML 1.1 で8進と解釈され 83 になる。str() しても先頭0は戻らない
        raise ValueError(
            "insurance.policy_no は引用符で囲んで文字列で書く"
            f"（数として読まれると先頭の0が落ちる）: {policy_no!r}")

    for key in STR_KEYS:
        value = raw.get(key)
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(f"insurance.{key} は空でない文字列: {value!r}")

    lists = {}
    for key in LIST_KEYS:
        value = raw.get(key)
        if value is not None and (not isinstance(value, list) or not value
                                  or not all(isinstance(v, str) and v for v in value)):
            raise ValueError(f"insurance.{key} は空でない文字列のリスト: {value!r}")
        lists[key] = tuple(value or ())

    deduction = raw.get('deduction')
    if deduction is not None and deduction not in DEDUCTIONS:
        raise ValueError(
            f"insurance.deduction は {' / '.join(DEDUCTIONS)} のどちらか"
            f"（控除が無ければ書かない）: {deduction!r}")

    term_end = raw.get('term_end')
    return Insurance(
        **{k: raw.get(k) for k in STR_KEYS},
        **lists,
        term_end=None if term_end is None else _date(term_end, 'term_end'),
        deduction=deduction,
    )


def missing_fields(ins: Insurance) -> list[str]:
    """事故・請求のときに要る欄のうち欠けているもの（INSURANCE_REQUIRED_FOR_CLAIM の順）"""
    return [k for k in INSURANCE_REQUIRED_FOR_CLAIM if not getattr(ins, k)]
