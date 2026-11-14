"""
MoneyForward ME の口座別残高（/bs/portfolio）とカード利用残高（/bs/liability）の HTML を行にする

ブラウザから切り離した純関数。ページの HTML 文字列を受け取り、1口座（1銘柄・1ポイント）を1行にして返す。

- 資産の種類は表の**直前の見出し**で決める（表の順番に依存しない）。「合計：…」の小見出しは見出しとして数えない
- 列は見出し（th）の文字列で引く。必要な列が無い表はページごと失敗にする（列ずれのまま書かない）
- 表の中にある見出し（モーダルの「資産の更新」）と、表の中の表は数えない。`保有金融機関` 列の無い表
  （ページ末尾のカレンダー等）は口座の表として扱わない
- 金額の `–円`・空は欠測（None）。0にしない
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

PORTFOLIO_KINDS = ('預金・現金', '投資信託', '暗号資産', 'ポイント')
LIABILITY_KIND = '負債'

# balances.csv の status（保存は lib/mf/store.py、日次への復元は lib/balances.py）
STATUS_OK = 'ok'
STATUS_MISSING = 'missing'   # 金額が `–円`。値は空で、合計から外す
STATUS_GONE = 'gone'         # 取得できたページから消えた。以後は引き継がない

# 種類ごとに 見出し → 行の欄。value は円換算の金額
_PORTFOLIO_COLUMNS = {
    '預金・現金': {'name': '種類・名称', 'value': '残高', 'institution': '保有金融機関'},
    '暗号資産': {'name': '種類・名称', 'value': '残高', 'institution': '保有金融機関'},
    '投資信託': {'name': '銘柄名', 'value': '評価額', 'institution': '保有金融機関',
             'quantity': '保有数', 'unrealized_gain': '評価損益'},
    'ポイント': {'name': '名称', 'value': '現在の価値', 'institution': '保有金融機関',
             'category': '種類', 'quantity': 'ポイント・マイル数', 'expires': '有効期限'},
}
_LIABILITY_COLUMNS = {'category': '種類', 'name': '名称・説明', 'value': '残高', 'institution': '保有金融機関'}
# 口座の表の目印。持たない表（カレンダー等）は読まない。持つのに種類が分からなければ警告する
_DATA_TABLE_MARK = '保有金融機関'

_HEADINGS = {'h1', 'h2', 'h3', 'h4'}
_SKIP_TEXT = {'script', 'style'}
_NUMBER = re.compile(r'^-?\d+(\.\d+)?$')


class ParseError(ValueError):
    """ページの形が想定と違う。そのページの行は書かない（消えたキーの判定もしない）"""


@dataclass
class Balance:
    kind: str
    institution: str
    name: str
    seq: int
    value: int | float | None
    category: str = ''
    quantity: int | float | None = None
    unrealized_gain: int | float | None = None
    expires: str = ''


@dataclass
class ParseResult:
    rows: list[Balance]
    warnings: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _key(text: str) -> str:
    return re.sub(r'\s+', '', text)


class _Blocks(HTMLParser):
    """表の外の見出しと、いちばん外側の表（行 × (th か, 文字列)）を出てきた順に並べる"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, object]] = []
        self._depth = 0           # table の入れ子
        self._skip = 0            # script / style の中
        self._heading: list[str] | None = None
        self._rows: list[list[tuple[bool, str]]] = []
        self._row: list[tuple[bool, str]] | None = None
        self._cell: list[str] | None = None
        self._cell_th = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TEXT:
            self._skip += 1
        elif tag == 'table':
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif self._depth == 0 and tag in _HEADINGS:
            self._heading = []
        elif self._depth == 1 and tag == 'tr':
            self._row = []
        elif self._depth == 1 and tag in ('td', 'th') and self._row is not None:
            self._close_cell()
            self._cell, self._cell_th = [], tag == 'th'

    def handle_endtag(self, tag):
        if tag in _SKIP_TEXT:
            self._skip = max(0, self._skip - 1)
        elif tag == 'table':
            if self._depth == 1:
                self._close_row()
                self.blocks.append(('table', self._rows))
            self._depth = max(0, self._depth - 1)
        elif self._depth == 0 and tag in _HEADINGS and self._heading is not None:
            self.blocks.append(('heading', _clean(''.join(self._heading))))
            self._heading = None
        elif self._depth == 1 and tag == 'tr':
            self._close_row()
        elif self._depth == 1 and tag in ('td', 'th'):
            self._close_cell()

    def handle_data(self, data):
        if self._skip:
            return
        if self._heading is not None:
            self._heading.append(data)
        if self._cell is not None:
            self._cell.append(data)

    def _close_cell(self):
        if self._cell is not None and self._row is not None:
            self._row.append((self._cell_th, _clean(''.join(self._cell))))
        self._cell = None

    def _close_row(self):
        self._close_cell()
        if self._row:
            self._rows.append(self._row)
        self._row = None


def _blocks(html: str) -> list[tuple[str, object]]:
    parser = _Blocks()
    parser.feed(html)
    parser.close()
    return parser.blocks


def _header(rows: list[list[tuple[bool, str]]]) -> tuple[list[str], list[list[str]]] | None:
    """先頭の th だけの行を見出しにする。無ければ None（集計表のように行見出しの表）"""
    if not rows or not all(is_th for is_th, _ in rows[0]):
        return None
    return [_key(t) for _, t in rows[0]], [[t for _, t in r] for r in rows[1:]]


def parse_number(text: str) -> int | float | None:
    """`1,234円` `-1,426円` `44ポイント` `36.19%` → 数。`–円`・空は None（0にしない）。

    単位を落としたあとに数として読めない文字列は ParseError（黙って欠測にすると形の変化に気づけない）
    """
    s = re.sub(r'[\s,]', '', text).replace('−', '-')
    s = re.sub(r'\D+$', '', s)   # 単位（円・ポイント・%）。数の無い `–円` はここで空になる
    if s in ('', '-'):
        return None
    if not _NUMBER.match(s):
        raise ParseError(f'数として読めない: {text!r}')
    f = float(s)
    return int(f) if f.is_integer() else f


def _rows_from_table(kind: str, columns: dict[str, str], header: list[str], body: list[list[str]],
                     seqs: dict[tuple[str, str, str], int]) -> list[Balance]:
    missing = [col for col in columns.values() if _key(col) not in header]
    if missing:
        raise ParseError(f'{kind} の表に列が無い: {", ".join(missing)}（見出し: {" | ".join(header)}）')
    index = {f: header.index(_key(col)) for f, col in columns.items()}
    out = []
    for cells in body:
        if len(cells) < len(header):
            continue
        get = {f: cells[i] for f, i in index.items()}
        key = (kind, get['institution'], get['name'])
        seqs[key] = seqs.get(key, 0) + 1
        out.append(Balance(
            kind=kind, institution=get['institution'], name=get['name'], seq=seqs[key],
            value=parse_number(get['value']), category=get.get('category', ''),
            quantity=parse_number(get['quantity']) if 'quantity' in get else None,
            unrealized_gain=parse_number(get['unrealized_gain']) if 'unrealized_gain' in get else None,
            expires=get.get('expires', ''),
        ))
    return out


def parse_portfolio(html: str) -> ParseResult:
    """/bs/portfolio。表の種類は直前の見出しで決める"""
    result = ParseResult(rows=[])
    seqs: dict[tuple[str, str, str], int] = {}
    kind: str | None = None
    for block, payload in _blocks(html):
        if block == 'heading':
            if payload and not payload.startswith('合計'):
                kind = payload if payload in PORTFOLIO_KINDS else None
            continue
        parsed = _header(payload)
        if parsed is None:
            continue
        header, body = parsed
        if _key(_DATA_TABLE_MARK) not in header:
            continue   # カレンダーなど、口座の表ではない
        if kind is None:
            result.warnings.append(f'種類の分からない資産の表を読み飛ばした（見出し: {" | ".join(header)}）')
            continue
        result.rows += _rows_from_table(kind, _PORTFOLIO_COLUMNS[kind], header, body, seqs)
    return result


def parse_liability(html: str) -> ParseResult:
    """/bs/liability。`種類 | 名称・説明 | 残高 | 保有金融機関` の表だけを読む（見出しは見ない）"""
    result = ParseResult(rows=[])
    seqs: dict[tuple[str, str, str], int] = {}
    wanted = {_key(c) for c in _LIABILITY_COLUMNS.values()}
    for block, payload in _blocks(html):
        parsed = _header(payload) if block == 'table' else None
        if parsed is None or not wanted <= set(parsed[0]):
            continue
        result.rows += _rows_from_table(LIABILITY_KIND, _LIABILITY_COLUMNS, *parsed, seqs)
    return result


def parse_pages(portfolio_html: str | None, liability_html: str | None) -> tuple[list[Balance], set[str], list[str]]:
    """2ページぶんの (行, 読めたページの種類, 警告)。

    取得できなかった（None）・形が違った・行が0件だったページの種類は「読めた」に入れない。
    保存側はこの種類にしか触らないので、ページ単位の失敗で全キーが一斉に消えた扱いにはならない
    """
    rows: list[Balance] = []
    kinds: set[str] = set()
    warnings: list[str] = []
    pages = [('portfolio', portfolio_html, parse_portfolio, set(PORTFOLIO_KINDS)),
             ('liability', liability_html, parse_liability, {LIABILITY_KIND})]
    for name, html, parse, page_kinds in pages:
        if html is None:
            warnings.append(f'{name}: 取得できなかった')
            continue
        try:
            result = parse(html)
        except ParseError as e:
            warnings.append(f'{name}: {e}')
            continue
        warnings += [f'{name}: {w}' for w in result.warnings]
        if not result.rows:
            warnings.append(f'{name}: 行が0件')
            continue
        rows += result.rows
        kinds |= page_kinds
    return rows, kinds, warnings
