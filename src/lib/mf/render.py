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

BUCKET_LABEL = {'month': '月', 'week': '週', 'day': '日'}
UNIT_LABEL = {'month': '月次', 'week': '週次', 'day': '日次'}

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


def add_bucket(df: pd.DataFrame, unit: str) -> pd.DataFrame:
    """集計単位の列 bucket を付与する"""
    df = df.copy()
    if unit == 'month':
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


def render_balance(df: pd.DataFrame, unit: str) -> str:
    """集計単位ごとの収入・支出・収支（月次では貯蓄率も）"""
    grouped = df.groupby('bucket').agg(
        income=(COL_AMOUNT, lambda s: s[s > 0].sum()),
        expense=(COL_AMOUNT, lambda s: -s[s < 0].sum()),
    )
    balance = grouped['income'] - grouped['expense']

    out = pd.DataFrame({
        '収入': grouped['income'].map(format_yen),
        '支出': grouped['expense'].map(format_yen),
        '収支': balance.map(format_yen),
    }, index=grouped.index)

    # 収入は月1回まとめて入るのに支出は毎日出るため、週次・日次の貯蓄率は
    # -60000% のような無意味な値になる。月次でだけ出す
    if unit == 'month':
        rate = (balance / grouped['income'] * 100).where(grouped['income'] > 0)
        out['貯蓄率'] = rate.map(lambda v: '-' if pd.isna(v) else f"{v:.1f}%")

    out.index.name = bucket_label(unit)
    return out.to_markdown()


def render_category_matrix(df: pd.DataFrame, unit: str) -> str:
    """bucket × 大項目 のクロス集計（支出）"""
    pivot = df.pivot_table(
        index='bucket', columns=COL_CATEGORY,
        values=COL_AMOUNT, aggfunc='sum',
    )
    # 合計の多いカテゴリを左に
    order = pivot.sum().sort_values(ascending=False).index
    pivot = pivot[order]
    pivot.index.name = bucket_label(unit)
    return pivot.map(format_yen).fillna('-').to_markdown()


def render_totals(df: pd.DataFrame, by, index_name: str, top: int = None) -> str:
    """期間全体の合計と構成比（支出）。by は列名または列名のリスト"""
    grouped = df.groupby(by)[COL_AMOUNT].sum().sort_values(ascending=False)
    total = grouped.sum()
    counts = df.groupby(by).size()

    if top is not None:
        grouped = grouped.head(top)

    out = pd.DataFrame({
        '合計': grouped.map(format_yen),
        '構成比': (grouped / total * 100).map('{:.1f}%'.format) if total > 0 else '-',
        '件数': counts.reindex(grouped.index),
    }, index=grouped.index)

    if isinstance(by, list):
        out.index = [' > '.join(map(str, k)) for k in out.index]
    out.index = [truncate(v) for v in out.index]
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
