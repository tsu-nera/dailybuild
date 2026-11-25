"""
config/longevity.yaml（老化の指標の台帳）の読み込みと、Grafana の longevity 画面用の表の計算

台帳は「どの CSV のどの列が、どの指標か」だけを持つ。sources が空の指標は未測定で、
網羅表に空欄の行として出す（測り始めたら source を足すだけで埋まる）。
検証は measurements_registry と同じく読み込み時に全件行い、1件でも壊れていれば RegistryError。
台帳の column / date_column が CSV に無いときも例外にする（typo が黙って未測定に見えるのを防ぐ）。
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from lib.analytics.body import prepare_body_df
from lib.forms_registry import RegistryError

LONGEVITY_YAML = Path(__file__).resolve().parents[2] / 'config' / 'longevity.yaml'

CATALOG_COLUMNS = ['section', 'key', 'name', 'unit', 'last_date', 'count']
LABS_COLUMNS = ['date', 'key', 'name', 'value', 'unit', 'source']

KINDS = ('daily', 'point')
METRIC_FIELDS = ('key', 'name', 'section', 'unit', 'sources')
SOURCE_FIELDS = ('csv', 'column', 'date_column', 'kind')

# CSV ごとの前処理。台帳の column に計算列（innerscan の ffmi）を書けるようにする
PREPROCESS: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    'data/healthplanet_innerscan.csv': prepare_body_df,
}


@dataclass(frozen=True)
class Source:
    csv: str
    column: str
    date_column: str
    kind: str


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    section: int
    unit: str
    sources: tuple[Source, ...]


@dataclass(frozen=True)
class Observation:
    date: dt.date
    value: float
    kind: str
    source: str  # csv のファイル名（拡張子なし）


def _check_fields(where, entry, required):
    missing = [f for f in required if f not in entry]
    if missing:
        raise RegistryError(f"{where}: 必須項目が無い: {', '.join(missing)}")
    unknown = set(entry) - set(required)
    if unknown:
        raise RegistryError(f"{where}: 未知の項目: {', '.join(sorted(unknown))}")


def _parse_source(entry, where) -> Source:
    if not isinstance(entry, dict):
        raise RegistryError(f'{where}: マッピングではない')
    _check_fields(where, entry, SOURCE_FIELDS)
    for field in SOURCE_FIELDS:
        if not isinstance(entry[field], str) or not entry[field]:
            raise RegistryError(f'{where}: {field} は空でない文字列')
    if entry['kind'] not in KINDS:
        raise RegistryError(f"{where}: kind は {' / '.join(KINDS)} のどちらか: {entry['kind']!r}")
    return Source(**{f: entry[f] for f in SOURCE_FIELDS})


def _parse(entry, index) -> Metric:
    where = f'metrics[{index}]'
    if not isinstance(entry, dict):
        raise RegistryError(f'{where}: マッピングではない')
    where = f"metrics[{index}]（{entry.get('key', '?')}）"
    _check_fields(where, entry, METRIC_FIELDS)
    for field in ('key', 'name'):
        if not isinstance(entry[field], str) or not entry[field]:
            raise RegistryError(f'{where}: {field} は空でない文字列')
    if not isinstance(entry['unit'], str):
        raise RegistryError(f'{where}: unit は文字列（無ければ空文字）')
    section = entry['section']
    if isinstance(section, bool) or not isinstance(section, int) or not 0 <= section <= 9:
        raise RegistryError(f'{where}: section は0〜9の整数: {section!r}')
    sources = entry['sources']
    if not isinstance(sources, list):
        raise RegistryError(f'{where}: sources はリスト（未測定は空リスト）')
    parsed = tuple(_parse_source(s, f'{where}.sources[{i}]') for i, s in enumerate(sources))
    return Metric(key=entry['key'], name=entry['name'], section=section,
                  unit=entry['unit'], sources=parsed)


def load_registry(path: Path = LONGEVITY_YAML) -> list[Metric]:
    """台帳を yaml の順に返す。壊れたエントリがあれば RegistryError"""
    with Path(path).open(encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    entries = data.get('metrics') if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise RegistryError(f'{path}: metrics のリストが無い')
    items = [_parse(e, i) for i, e in enumerate(entries)]
    seen = set()
    for item in items:
        if item.key in seen:
            raise RegistryError(f'key が重複している: {item.key}')
        seen.add(item.key)
    return items


def read_observations(metrics: list[Metric],
                      resolve: Callable[[str], Path]) -> dict[str, list[Observation]]:
    """指標ごとの観測値（key → Observation のリスト）。CSV は重複なく1回だけ読む

    resolve は台帳の相対パスを実パスにする（dashboard.py は require_private_path を渡す）。
    point の source は同じ日の行が重複していても1行にする（先の行を残す）。
    """
    frames: dict[str, pd.DataFrame] = {}
    result: dict[str, list[Observation]] = {}
    for m in metrics:
        obs: list[Observation] = []
        for src in m.sources:
            if src.csv not in frames:
                df = pd.read_csv(resolve(src.csv))
                if src.csv in PREPROCESS:
                    df = PREPROCESS[src.csv](df)
                frames[src.csv] = df
            df = frames[src.csv]
            for col in (src.column, src.date_column):
                if col not in df.columns:
                    raise RegistryError(
                        f'{m.key}: {src.csv} に列 {col!r} が無い（台帳の typo か CSV の見出し変更）')
            part = pd.DataFrame({
                'date': pd.to_datetime(df[src.date_column], errors='coerce').dt.date,
                'value': pd.to_numeric(df[src.column], errors='coerce'),
            }).dropna()
            if src.kind == 'point':
                part = part.drop_duplicates('date')
            stem = Path(src.csv).stem
            obs += [Observation(d, float(v), src.kind, stem)
                    for d, v in zip(part['date'], part['value'])]
        result[m.key] = obs
    return result


def monthly_keys(metrics: list[Metric]) -> list[str]:
    """月次の表に列を持つ指標（daily の source が1つ以上）"""
    return [m.key for m in metrics if any(s.kind == 'daily' for s in m.sources)]


def build_catalog(metrics: list[Metric], observations: dict[str, list[Observation]]) -> list[dict]:
    """網羅表。未測定・観測値なしの指標は last_date / count が None（空セル）"""
    rows = []
    for m in sorted(metrics, key=lambda m: m.section):  # sorted は安定なので区画内は台帳の順
        obs = observations.get(m.key, [])
        rows.append({
            'section': m.section, 'key': m.key, 'name': m.name, 'unit': m.unit,
            'last_date': max(o.date for o in obs).isoformat() if obs else None,
            'count': len(obs) if obs else None,
        })
    return rows


def build_monthly(metrics: list[Metric], observations: dict[str, list[Observation]],
                  today: dt.date) -> list[dict]:
    """daily の観測値の月平均を横持ちで。値の無い月は None（0にしない）"""
    keys = monthly_keys(metrics)
    values: dict[tuple[str, dt.date], list[float]] = {}
    for key in keys:
        for o in observations.get(key, []):
            if o.kind == 'daily':
                values.setdefault((key, o.date.replace(day=1)), []).append(o.value)
    if not values:
        return []
    month = min(m for _, m in values)
    last = today.replace(day=1)
    rows = []
    while month <= last:
        row = {'month': month.isoformat()}
        for key in keys:
            vals = values.get((key, month))
            row[key] = round(sum(vals) / len(vals), 2) if vals else None
        rows.append(row)
        month = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return rows


def build_labs(metrics: list[Metric], observations: dict[str, list[Observation]]) -> list[dict]:
    """point の観測値を縦持ちで。同じ (source, date, key) は1行"""
    rows, seen = [], set()
    for order, m in enumerate(sorted(metrics, key=lambda m: m.section)):
        for o in observations.get(m.key, []):
            if o.kind != 'point' or (o.source, o.date, m.key) in seen:
                continue
            seen.add((o.source, o.date, m.key))
            rows.append((o.date, order, {'date': o.date.isoformat(), 'key': m.key, 'name': m.name,
                                         'value': o.value, 'unit': m.unit, 'source': o.source}))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows]
