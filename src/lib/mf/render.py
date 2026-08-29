"""
MoneyForward ME 収入・支出の markdown 出力

CSV の読み込みは store.py が担う。lib/toggl/render.py と同じ構成・同じ表形式で
出す（time と money の対）。
"""

import pandas as pd
from wcwidth import wcswidth

from lib.mf.store import (
    COL_ACCOUNT, COL_AMOUNT, COL_CATEGORY, COL_NAME, COL_SUBCATEGORY,
)

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']

BUCKET_LABEL = {'year': '年', 'month': '月', 'week': '週', 'day': '日'}
UNIT_LABEL = {'year': '年次', 'month': '月次', 'week': '週次', 'day': '日次'}

# 店舗名（内容）は返礼品名などで際限なく長くなる。表の横伸びを止める表示幅
NAME_WIDTH = 32


def bucket_label(unit: str) -> str:
    return BUCKET_LABEL[unit]


def unit_label(unit: str) -> str:
    return UNIT_LABEL[unit]


def truncate(text, width: int = NAME_WIDTH) -> str:
    """表示幅（全角=2）で切り詰める。文字数では全角混じりの幅を測れない"""
    text = str(text)
    if wcswidth(text) <= width:
        return text
    out = ''
    used = 0
    for ch in text:
        w = max(wcswidth(ch), 0)
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + '…'


def format_yen(amount) -> str:
    """金額を ¥12,345 形式に"""
    if pd.isna(amount):
        return '-'
    return f"¥{int(round(amount)):,}"


def format_delta(diff) -> str:
    """増減額を +¥1,234 / -¥1,234 形式に。基準が無いときは '-'"""
    if pd.isna(diff):
        return '-'
    sign = '+' if diff >= 0 else '-'
    return f"{sign}¥{abs(int(round(diff))):,}"


def format_delta_pct(current, previous) -> str:
    """増減率。前期が 0 のときは率が定義できないので '-'"""
    if pd.isna(previous) or previous == 0:
        return '-'
    return f"{(current - previous) / previous * 100:+.1f}%"


def add_bucket(df: pd.DataFrame, unit: str) -> pd.DataFrame:
    """集計単位の列 bucket を付与する"""
    df = df.copy()
    if unit == 'year':
        df['bucket'] = df['date'].dt.strftime('%Y')
    elif unit == 'month':
        df['bucket'] = df['date'].dt.strftime('%Y-%m')
    elif unit == 'week':
        iso = df['date'].dt.isocalendar()
        df['bucket'] = iso['year'].astype(str) + '-W' + iso['week'].astype(int).map('{:02d}'.format)
    else:
        df['bucket'] = df['date'].dt.strftime('%Y-%m-%d')
    return df


def expenses(df: pd.DataFrame) -> pd.DataFrame:
    """支出のみを正の金額にして返す"""
    out = df[df[COL_AMOUNT] < 0].copy()
    out[COL_AMOUNT] = out[COL_AMOUNT].abs()
    return out


def render_balance(df: pd.DataFrame, unit: str,
                   excluded: list[str] = None, focus_label: str = '支出') -> str:
    """集計単位ごとの収入・支出・収支と、支出の前期比。

    excluded を渡すと支出を「対象」と「除外」に割る。除外ぶんを黙って落とすと
    収入は満額のまま支出だけ減り、収支が嘘になるため、必ず両方を列に残す。
    前期比は着目している側（除外後）に付ける。
    """
    df = df.copy()
    df['excluded'] = df[COL_CATEGORY].isin(excluded or [])

    grouped = df.groupby('bucket').agg(
        income=(COL_AMOUNT, lambda s: s[s > 0].sum()),
        expense=(COL_AMOUNT, lambda s: -s[s < 0].sum()),
    )
    off = (df[df['excluded'] & (df[COL_AMOUNT] < 0)]
           .groupby('bucket')[COL_AMOUNT].sum().mul(-1)
           .reindex(grouped.index).fillna(0))
    focus = grouped['expense'] - off

    balance = grouped['income'] - grouped['expense']
    prev = focus.shift(1)
    single = len(grouped) == 1

    columns = {'収入': grouped['income'].map(format_yen)}
    if excluded:
        columns[focus_label] = focus.map(format_yen)
        columns['除外'] = off.map(format_yen)
        columns['支出計'] = grouped['expense'].map(format_yen)
    else:
        columns['支出'] = grouped['expense'].map(format_yen)
    columns['収支'] = balance.map(format_yen)
    columns[f'{focus_label}Δ'] = (focus - prev).map(format_delta)
    columns['Δ%'] = [format_delta_pct(c, p) for c, p in zip(focus, prev)]

    out = pd.DataFrame(columns)

    # 合計と平均。増減列は行をまたいだ意味を持たないので空にする。
    # bucket が1つのときは本体行の写しにしかならないので出さない
    def summary(agg) -> list[str]:
        row = [format_yen(agg(grouped['income']))]
        if excluded:
            row += [format_yen(agg(focus)), format_yen(agg(off)),
                    format_yen(agg(grouped['expense']))]
        else:
            row.append(format_yen(agg(grouped['expense'])))
        return row + [format_yen(agg(balance)), '', '']

    if not single:
        out.loc['合計'] = summary(lambda s: s.sum())
        out.loc[f'平均/{bucket_label(unit)}'] = summary(lambda s: s.mean())
    else:
        out = out.drop(columns=[f'{focus_label}Δ', 'Δ%'])

    out.index.name = bucket_label(unit)
    return out.to_markdown()


def previous_bucket(df: pd.DataFrame, cur_bucket: str) -> str | None:
    """cur_bucket の1つ前の bucket。表示期間の外にあっても拾う。

    既定の表示が当月だけなので、期間内だけを見ると比較対象が常に存在しない。
    """
    prior = sorted(b for b in df['bucket'].unique() if b < cur_bucket)
    return prior[-1] if prior else None


def render_period_change(df: pd.DataFrame, prev_b: str, cur_b: str,
                         top: int = 5) -> str:
    """2つの bucket を中項目で突き合わせ、増えた/減った順に並べる。
    差が全く無ければ空文字を返す（呼び出し側が節ごと落とす）"""
    key = [COL_CATEGORY, COL_SUBCATEGORY]
    df = fill_keys(df, key)
    cur = df[df['bucket'] == cur_b].groupby(key)[COL_AMOUNT].sum()
    prev = df[df['bucket'] == prev_b].groupby(key)[COL_AMOUNT].sum()

    merged = pd.concat([prev.rename('prev'), cur.rename('cur')], axis=1).fillna(0)
    merged['diff'] = merged['cur'] - merged['prev']
    merged = merged.sort_values('diff', ascending=False)

    # 増加の上位と減少の上位。中間（変化の小さい項目）は落とす
    picked = pd.concat([merged.head(top), merged.tail(top)])
    picked = picked[~picked.index.duplicated()]
    picked = picked[picked['diff'] != 0]
    if picked.empty:
        return ''

    out = pd.DataFrame({
        f'{prev_b}': picked['prev'].map(format_yen),
        f'{cur_b}': picked['cur'].map(format_yen),
        'Δ': picked['diff'].map(format_delta),
        'Δ%': [format_delta_pct(c, p) for c, p in zip(picked['cur'], picked['prev'])],
    })
    out.index = [truncate(' > '.join(map(str, k))) for k in picked.index]
    out.index.name = '中項目'
    return out.to_markdown()


def render_category_matrix(df: pd.DataFrame, unit: str) -> str:
    """大項目 × bucket のクロス集計（支出）。

    カテゴリを行に置く。列に置くとカテゴリ名（全角4-6文字）が列幅を決めてしまい、
    18カテゴリある年次では端末で折り返して読めなくなる。
    """
    pivot = df.pivot_table(
        index=COL_CATEGORY, columns='bucket',
        values=COL_AMOUNT, aggfunc='sum',
    )
    # 合計の多いカテゴリを上に
    pivot = pivot.loc[pivot.sum(axis=1).sort_values(ascending=False).index]

    if len(pivot.columns) > 1:
        pivot['合計'] = pivot.sum(axis=1)
    pivot.loc['合計'] = pivot.sum()

    pivot.index.name = f'カテゴリ \\ {bucket_label(unit)}'
    return pivot.map(format_yen).fillna('-').to_markdown()


# 内容（店舗名）は現金支出などで空になる。groupby は NaN のキーを黙って落とし、
# 集計から金額ごと消える（直近3ヶ月で12件 ¥398,360、全期間 1786件）ので埋める
MISSING_KEY = '（記載なし）'


def fill_keys(df: pd.DataFrame, by) -> pd.DataFrame:
    """groupby のキー列の NaN を埋める。欠測を行ごと落とさないため"""
    cols = by if isinstance(by, list) else [by]
    out = df.copy()
    for col in cols:
        out[col] = out[col].fillna(MISSING_KEY)
    return out


def render_totals(df: pd.DataFrame, by, index_name: str, top: int = None) -> str:
    """期間全体の合計と構成比（支出）。by は列名または列名のリスト。
    top で切ったぶんは「他N件」に畳んで残す（構成比が 100% に閉じるように）"""
    df = fill_keys(df, by)
    grouped = df.groupby(by)[COL_AMOUNT].sum().sort_values(ascending=False)
    counts = df.groupby(by).size()
    total = grouped.sum()

    shown = grouped.head(top) if top is not None else grouped
    rest = grouped.iloc[len(shown):]

    if isinstance(by, list):
        labels = [' > '.join(map(str, k)) for k in shown.index]
    else:
        labels = [str(k) for k in shown.index]
    labels = [truncate(v) for v in labels]
    amounts = list(shown.values)
    sizes = [int(v) for v in counts.reindex(shown.index).values]

    if len(rest) > 0:
        labels.append(f'（他 {len(rest)}件）')
        amounts.append(rest.sum())
        sizes.append(int(counts.reindex(rest.index).sum()))

    labels.append('合計')
    amounts.append(total)
    sizes.append(int(counts.sum()))

    out = pd.DataFrame({
        '金額': [format_yen(a) for a in amounts],
        '構成比': [f'{a / total * 100:.1f}%' if total > 0 else '-' for a in amounts],
        '件数': sizes,
    }, index=labels)
    out.index.name = index_name
    return out.to_markdown()


def render_entries(df: pd.DataFrame) -> str:
    """明細を時系列に並べ、日ごとの見出しで区切って出す"""
    blocks = []
    for date, day_df in df.groupby('date', sort=True):
        heading = f"## {date.strftime('%Y-%m-%d')}（{WEEKDAY_JA[date.weekday()]}）"

        rows = pd.DataFrame({
            '内容': day_df[COL_NAME].map(truncate),
            'カテゴリ': day_df[COL_CATEGORY] + ' > ' + day_df[COL_SUBCATEGORY].fillna('-'),
            '金額': day_df[COL_AMOUNT].map(format_yen),
            '金融機関': day_df[COL_ACCOUNT].fillna('-'),
        })
        day_expense = -day_df[day_df[COL_AMOUNT] < 0][COL_AMOUNT].sum()
        blocks.append(
            f"{heading}  支出 {format_yen(day_expense)}\n\n{rows.to_markdown(index=False)}"
        )

    return '\n\n'.join(blocks)
