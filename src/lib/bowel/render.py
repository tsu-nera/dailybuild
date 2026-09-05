"""
排便記録の markdown 出力

pandas 以外の外部依存を持たない。CSV の読み込みは store.py が担う。

analyze 目的ではなくデータ主権の回収が主目的（Issue #109）のため、
「目標」「達成率」に類する評価は出さない。被覆（記録のあった日数）は
但し書きとしてのみ出す。
"""

import pandas as pd

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']

# 3分類の境界。硬い(1-2) / 正常(3-5) / ゆるい(6-7)
CATEGORY_BOUNDS = {'硬い': (1, 2), '正常': (3, 5), 'ゆるい': (6, 7)}


def _day_label(ts) -> str:
    return f"{ts.strftime('%m-%d')} ({WEEKDAY_JA[ts.weekday()]})"


def render_distribution(df: pd.DataFrame) -> str:
    """1〜7 それぞれの件数と割合"""
    valid = df['bristol'].dropna()
    if valid.empty:
        return '（記録なし）'
    counts = valid.value_counts().reindex(range(1, 8), fill_value=0).sort_index()
    total = len(valid)
    out = pd.DataFrame({
        '型': [int(v) for v in counts.index],
        '件数': list(counts.values),
        '割合': [f'{round(100 * c / total)}%' for c in counts.values],
    })
    return out.to_markdown(index=False)


def render_category(df: pd.DataFrame) -> str:
    """硬い(1-2) / 正常(3-5) / ゆるい(6-7) の3分類"""
    valid = df['bristol'].dropna()
    if valid.empty:
        return '（記録なし）'
    total = len(valid)
    rows = []
    for name, (lo, hi) in CATEGORY_BOUNDS.items():
        c = int(((valid >= lo) & (valid <= hi)).sum())
        rows.append({'分類': f'{name}（{lo}-{hi}）', '件数': c,
                     '割合': f'{round(100 * c / total)}%'})
    return pd.DataFrame(rows).to_markdown(index=False)


def render_daily(df: pd.DataFrame) -> str:
    """日別の一覧。日付・時刻・型を時系列で並べる"""
    if df.empty:
        return '（この期間に記録がありません）'
    out = pd.DataFrame({
        '日': [_day_label(t) for t in df['timestamp']],
        '時刻': [t.strftime('%H:%M') for t in df['timestamp']],
        '型': ['-' if pd.isna(v) else str(int(v)) for v in df['bristol']],
    })
    return out.to_markdown(index=False)
