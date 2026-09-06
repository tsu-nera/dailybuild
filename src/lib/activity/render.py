"""
活動記録の markdown 出力

表は `to_markdown()`（tabulate + wcwidth）で組む。手で f-string を並べると
全角文字の幅が合わず、端末で列がずれる（他のソースの render.py と同じ理由）。
"""

import pandas as pd

from lib.activity import store


def render_entries(df: pd.DataFrame) -> str:
    """枠ごとの一覧"""
    out = pd.DataFrame({
        '日付': df['date'].dt.strftime('%m-%d'),
        '枠': df['hour'].map(store.slot_label),
        '活動': df['activity'],
        '楽しさ': df['enjoyment'],
        '重要さ': df['importance'],
    })
    # 未評定は 0 と紛れないよう空欄で出す
    for col in ('楽しさ', '重要さ'):
        out[col] = out[col].astype('object').where(out[col].notna(), '')
    return out.to_markdown(index=False)


def render_daily(df: pd.DataFrame) -> str:
    """日ごとの要約

    件数ではなく時間で出す。この帳票の主目的が「楽しくも重要でもない時間の
    長さ」の観測なので、枠の数を数えても意味が出ない（2-5 は3時間枠）。
    """
    rows = []
    for date, g in df.groupby(df['date'].dt.date):
        rated = g[g['enjoyment'].notna() & g['importance'].notna()]
        low = rated[(rated['enjoyment'] <= 3) & (rated['importance'] <= 3)]
        rows.append({
            '日付': f'{date:%m-%d}',
            '記録': f"{int(g['hours'].sum())}h",
            '楽しさ平均': (round(g['enjoyment'].mean(), 1)
                       if g['enjoyment'].notna().any() else '-'),
            '重要さ平均': (round(g['importance'].mean(), 1)
                       if g['importance'].notna().any() else '-'),
            '低評定(3以下)': f"{int(low['hours'].sum())}h",
        })
    return pd.DataFrame(rows).to_markdown(index=False)
