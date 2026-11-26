"""消耗品の正本（Notion「消耗品DB」）を consumables.csv・stocktake.csv へ写す

Notion の列: 品目(title) key(text) 分類(select) 単位(select) 量(number) メモ(text) 更新(last_edited_time)。

- key が空のページには `n_` + ページ ID 先頭8桁を振り、Notion の key 列へ書き戻す。振った key は変えない
- key が重複していたら、どの CSV も書かずに SyncError（どちらの購入履歴か決められない）
- Notion が0行なら SyncError（取りこぼしで全品目に ended_on が付くのを防ぐ）
- consumables.csv: Notion が持つ列（name category unit note）は Notion の値で上書きし、
  持たない列（location keep subscription ended_on）は CSV の値を保つ。新しい key は末尾に足す。
  Notion から消えた key は行を残し、ended_on が空なら同期日を入れる
- stocktake.csv: 量のある品目について、その key の最後の記録と量が違うときだけ `更新` の JST 日付で1行足す。
  最後の記録が `更新` より後の日付なら足さない（後から書かれた棚卸しの方が新しい）
"""

import csv
import datetime as dt
import io
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')
KEY_PREFIX = 'n_'
# Notion の列名 → consumables.csv の列名（Notion が正本の列）
NOTION_COLUMNS = {'品目': 'name', '分類': 'category', '単位': 'unit', 'メモ': 'note'}
STOCKTAKE_HEADER = ['date', 'key', 'quantity', 'note']


class SyncError(RuntimeError):
    """CSV を書かずに止めるべき状態"""


@dataclass
class NotionItem:
    page_id: str
    key: str            # 書き戻す前の空の key は auto_key で埋めた値
    key_assigned: bool  # この同期で振った key か
    values: dict[str, str]
    quantity: float | None
    edited_on: dt.date


def _text(prop: dict | None) -> str:
    if not prop:
        return ''
    kind = prop.get('type')
    if kind in ('title', 'rich_text'):
        return ''.join(t.get('plain_text', '') for t in prop.get(kind) or []).strip()
    if kind == 'select':
        return (prop.get('select') or {}).get('name', '')
    raise ValueError(f'未対応のプロパティ型: {kind}')


def auto_key(page_id: str) -> str:
    return KEY_PREFIX + page_id.replace('-', '')[:8]


def parse_page(page: dict) -> NotionItem:
    props = page['properties']
    key = _text(props.get('key'))
    edited = (props.get('更新') or {}).get('last_edited_time') or page['last_edited_time']
    edited_on = dt.datetime.fromisoformat(edited.replace('Z', '+00:00')).astimezone(JST).date()
    quantity = (props.get('量') or {}).get('number')
    return NotionItem(
        page_id=page['id'],
        key=key or auto_key(page['id']),
        key_assigned=not key,
        values={col: _text(props.get(name)) for name, col in NOTION_COLUMNS.items()},
        quantity=None if quantity is None else float(quantity),
        edited_on=edited_on,
    )


def parse_pages(pages: list[dict]) -> list[NotionItem]:
    pages = [p for p in pages if not p.get('in_trash') and not p.get('archived')]
    if not pages:
        raise SyncError('Notion から1行も取れなかった（CSV は書かない）')
    items = [parse_page(p) for p in pages]
    by_key: dict[str, list[str]] = {}
    for it in items:
        by_key.setdefault(it.key, []).append(it.values['name'] or it.page_id)
    dups = {k: names for k, names in by_key.items() if len(names) > 1}
    if dups:
        lines = [f'  key={k}: {"、".join(names)}' for k, names in dups.items()]
        raise SyncError('key が重複している（CSV は書かない。Notion で片方の key を空にすると同期が振り直す）\n'
                        + '\n'.join(lines))
    return items


def _read(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    raw = path.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8'), newline=''))
    return list(reader.fieldnames or []), list(reader), newline


def _render(header: list[str], rows: list[dict[str, str]], newline: str) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator=newline)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, '') for c in header})
    return buf.getvalue()


def _write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return False
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8', newline='')
    os.replace(tmp, path)
    return True


def merge_consumables(header: list[str], rows: list[dict[str, str]],
                      items: list[NotionItem], today: dt.date) -> list[dict[str, str]]:
    out = [dict(r) for r in rows]
    index = {r['key']: r for r in out}
    notion_keys = set()
    for it in items:
        notion_keys.add(it.key)
        row = index.get(it.key)
        if row is None:
            row = {c: '' for c in header}
            row['key'] = it.key
            out.append(row)
            index[it.key] = row
        row.update(it.values)
    for r in out:
        if r['key'] not in notion_keys and not r.get('ended_on'):
            r['ended_on'] = today.isoformat()
    return out


def format_quantity(q: float) -> str:
    return str(int(q)) if q.is_integer() else repr(q)


def merge_stocktake(rows: list[dict[str, str]], items: list[NotionItem]) -> list[dict[str, str]]:
    """その key の最後の記録より Notion の量が新しく、かつ違うときだけ1行足す。
    最後の記録が `更新` より後の日付なら（agent が後から書いた棚卸し）、Notion の量は古いので足さない"""
    last: dict[str, tuple[str, float]] = {}
    for r in sorted(rows, key=lambda r: r['date']):  # sorted は安定なので同日はファイル順
        if r.get('quantity', '') != '':
            last[r['key']] = (r['date'], float(r['quantity']))
    out = [dict(r) for r in rows]
    for it in items:
        if it.quantity is None:
            continue
        date = it.edited_on.isoformat()
        prev = last.get(it.key)
        if prev and (prev[0] > date or prev[1] == it.quantity):
            continue
        out.append({'date': date, 'key': it.key, 'quantity': format_quantity(it.quantity), 'note': ''})
        last[it.key] = (date, it.quantity)
    return out


def sync(client, data_source_id: str, consumables_csv: Path, stocktake_csv: Path,
         today: dt.date, log=print) -> None:
    """Notion → CSV。止めるべき状態は SyncError（CSV は書かない）。key の書き戻しは CSV を書いた後"""
    items = parse_pages(client.query_data_source(data_source_id))
    log(f'Notion: {len(items)} 品目')

    header, rows, newline = _read(consumables_csv)
    merged = merge_consumables(header, rows, items, today)
    if _write_if_changed(consumables_csv, _render(header, merged, newline)):
        log(f'更新: {consumables_csv}（{len(rows)} → {len(merged)} 行）')

    if stocktake_csv.exists():
        st_header, st_rows, st_newline = _read(stocktake_csv)
    else:
        st_header, st_rows, st_newline = STOCKTAKE_HEADER, [], '\n'
    st_merged = merge_stocktake(st_rows, items)
    if _write_if_changed(stocktake_csv, _render(st_header, st_merged, st_newline)):
        log(f'更新: {stocktake_csv}（+{len(st_merged) - len(st_rows)} 行）')

    for it in items:
        if it.key_assigned:
            client.set_rich_text(it.page_id, 'key', it.key)
            log(f'key を振った: {it.values["name"]} → {it.key}')
