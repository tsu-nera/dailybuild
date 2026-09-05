"""
日次記録の markdown 出力

pandas 以外の外部依存を持たない。CSV の読み込みは store.py が担う。

bowel/render.py・emotion/render.py と同じ方針で、「目標」「達成率」
「streak」に類する評価は出さない（データ主権の回収が主目的で、分析は
別レポート側の役割）。
"""

import pandas as pd

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']


def _day_label(d) -> str:
    return f"{d.strftime('%m-%d')} ({WEEKDAY_JA[d.weekday()]})"


def render_scores(df: pd.DataFrame) -> str:
    """日付 × mind/body/head/sleep のスコア表。欠測は '-'"""
    if df.empty:
        return '（この期間に記録がありません）'

    def fmt(v):
        return '-' if pd.isna(v) else str(int(v))

    out = pd.DataFrame({
        '日': [_day_label(d) for d in df['date']],
        '気分': [fmt(v) for v in df['mind_score']],
        '身体': [fmt(v) for v in df['body_score']],
        '頭': [fmt(v) for v in df['head_score']],
        '睡眠': [fmt(v) for v in df['sleep_score']],
        '出所': list(df['source']),
    })
    return out.to_markdown(index=False)


def render_comments(df: pd.DataFrame) -> str:
    """コメントのある行だけ箇条書きで並べる"""
    rows = df[df['comment'].astype(str).str.len() > 0]
    if rows.empty:
        return '（この期間にコメントがありません）'
    lines = [f"- **{d:%Y-%m-%d}**: {c}"
             for d, c in zip(rows['date'], rows['comment'])]
    return '\n'.join(lines)
