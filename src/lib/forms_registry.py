"""
config/forms.yaml（Google Forms のレジストリ）の読み込みと検証

フォームは2週間程度で追加・廃止が起きる。以前はフォーム1つの状態変更が
journal_skeleton.py・daily-fetch.sh・スキル・docs に散ったコード修正になり、
直し漏れは例外を出さずに残った（入力をやめたフォームの「陽性感情なし」の
継続日数が毎日伸び続けた）。登録はこの yaml に寄せ、解釈はコードに残す。

検証は読み込み時に全件行い、1件でも壊れていれば例外にする。黙って
そのエントリを飛ばすと、fetch が止まったことに誰も気づかない。
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

FORMS_YAML = Path(__file__).resolve().parents[2] / 'config' / 'forms.yaml'

STATUSES = ('active', 'deprecated')
CADENCES = ('daily', 'sparse', 'weekly')
REVIEWS = ('daily', 'weekly')

REQUIRED = ('key', 'name', 'csv', 'date_column', 'status', 'cadence',
            'stale_after_days', 'note', 'review', 'fetch', 'show')


class RegistryError(ValueError):
    """レジストリのエントリが壊れている"""


@dataclass(frozen=True)
class Form:
    key: str
    name: str
    csv: str
    date_column: str
    status: str
    cadence: str
    stale_after_days: int | None
    note: str
    review: str | None
    fetch: tuple[str, ...]
    show: tuple[str, ...] | None
    short_name: str

    @property
    def active(self) -> bool:
        return self.status == 'active'


def _argv(entry, field, where):
    value = entry[field]
    if value is None and field == 'show':
        return None
    if (not isinstance(value, list) or not value
            or not all(isinstance(v, str) and v for v in value)):
        raise RegistryError(f'{where}: {field} は空でない文字列のリスト')
    return tuple(value)


def _parse(entry, index) -> Form:
    where = f'forms[{index}]'
    if not isinstance(entry, dict):
        raise RegistryError(f'{where}: マッピングではない')
    where = f"forms[{index}]（{entry.get('key', '?')}）"
    missing = [f for f in REQUIRED if f not in entry]
    if missing:
        raise RegistryError(f"{where}: 必須項目が無い: {', '.join(missing)}")
    unknown = set(entry) - set(REQUIRED) - {'short_name'}
    if unknown:
        raise RegistryError(f"{where}: 未知の項目: {', '.join(sorted(unknown))}")
    for field in ('key', 'name', 'csv', 'date_column'):
        if not isinstance(entry[field], str) or not entry[field]:
            raise RegistryError(f'{where}: {field} は空でない文字列')
    if entry['status'] not in STATUSES:
        raise RegistryError(f"{where}: 未知の status: {entry['status']!r}")
    if entry['cadence'] not in CADENCES:
        raise RegistryError(f"{where}: 未知の cadence: {entry['cadence']!r}")
    if entry['review'] is not None and entry['review'] not in REVIEWS:
        raise RegistryError(f"{where}: 未知の review: {entry['review']!r}")
    stale = entry['stale_after_days']
    if stale is not None and (isinstance(stale, bool) or not isinstance(stale, int)
                              or stale < 0):
        raise RegistryError(f'{where}: stale_after_days は0以上の整数か null')
    note = entry['note'] or ''
    if not isinstance(note, str):
        raise RegistryError(f'{where}: note は文字列')
    show = _argv(entry, 'show', where)
    if entry['review'] is not None and show is None:
        raise RegistryError(f'{where}: review があるのに show が無い')
    short_name = entry.get('short_name') or entry['name']
    return Form(key=entry['key'], name=entry['name'], csv=entry['csv'],
                date_column=entry['date_column'], status=entry['status'],
                cadence=entry['cadence'], stale_after_days=stale, note=note,
                review=entry['review'], fetch=_argv(entry, 'fetch', where),
                show=show, short_name=short_name)


def load_forms(path: Path = FORMS_YAML) -> list[Form]:
    """レジストリを yaml の順に返す。壊れたエントリがあれば RegistryError"""
    with Path(path).open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    entries = data.get('forms') if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise RegistryError(f'{path}: forms のリストが無い')
    forms = [_parse(e, i) for i, e in enumerate(entries)]
    for field in ('key', 'csv'):
        seen = set()
        for form in forms:
            value = getattr(form, field)
            if value in seen:
                raise RegistryError(f'{field} が重複している: {value}')
            seen.add(value)
    return forms


def fetch_forms(forms: list[Form]) -> list[Form]:
    """日次で fetch するフォーム。deprecated も含む（入力されたら CSV に入る）"""
    return list(forms)


def pipeline_forms(forms: list[Form]) -> list[Form]:
    """鮮度表に出すフォーム"""
    return [f for f in forms if f.active and f.stale_after_days is not None]


def sparse_forms(forms: list[Form]) -> list[Form]:
    """最終記録（疎な指標）に出すフォーム"""
    return [f for f in forms if f.active and f.cadence == 'sparse']


def review_forms(forms: list[Form], review: str) -> list[Form]:
    """review が読むフォーム"""
    return [f for f in forms if f.active and f.review == review]
