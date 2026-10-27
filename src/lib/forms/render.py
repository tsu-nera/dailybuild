"""
schema（def yaml だけで動くフォーム）の markdown 出力

pandas 以外の外部依存を持たない。CSV の読み込みは schema.load_entries が担う。

bowel/render.py・emotion/render.py と同じ方針で、「目標」「達成率」
「streak」に類する評価は出さない（データ主権の回収が主目的で、分析は
別レポート側の役割）。
"""

import pandas as pd

from lib.forms import schema

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']


def _day_label(d) -> str:
    return f"{d.strftime('%m-%d')} ({WEEKDAY_JA[d.weekday()]})"


def render_scores(df: pd.DataFrame, conf: dict) -> str:
    """日付（unit: response なら日付・時刻）× スコアの表。欠測は '-'

    グリッド（1〜5）は整数表示、数値設問（HRV など小数値もありうる）は
    そのまま g フォーマットで表示する。
    """
    if df.empty:
        return '（この期間に記録がありません）'

    number_cols = set(schema.number_columns(conf))

    def fmt(col, v):
        if pd.isna(v):
            return '-'
        if col in number_cols:
            return f'{v:g}'
        return str(int(v))

    out = pd.DataFrame({'日': [_day_label(d) for d in df['date']]})
    if schema.unit(conf) == 'response':
        out['時刻'] = [t.strftime('%H:%M') for t in df['timestamp']]
    for col, label in schema.display_labels(conf):
        out[label] = [fmt(col, v) for v in df[col]]
    if conf.get('source'):
        out['出所'] = list(df['source'])
    return out.to_markdown(index=False)


def render_comments(df: pd.DataFrame, conf: dict) -> str:
    """自由記述のある行だけ箇条書きで並べる（自由記述が複数あれば設問ごと）"""
    labels = schema.text_labels(conf)
    lines = []
    for col, label in labels:
        rows = df[df[col].astype(str).str.len() > 0]
        if len(labels) > 1 and not rows.empty:
            lines.append(f'### {label}\n')
        lines += [f"- **{d:%Y-%m-%d}**: {c}" for d, c in zip(rows['date'], rows[col])]
    if not lines:
        return '（この期間にコメントがありません）'
    return '\n'.join(lines)


def render_fill_rates(df: pd.DataFrame, conf: dict, period_days: int) -> str:
    """設問ごとの入力率（notna 件数 / 期間日数）。全欠測日も分母に含める

    len(df) を分母にすると、丸ごと欠測した日が存在しないだけで消え、
    入力率が見かけ上100%になる（過去の manual.csv 運用が3ヶ月気づけなかった
    失敗の再発防止。Issue #167）。unit: day 専用（1日1行が前提の率）。
    """
    lines = []
    for col, label in schema.display_labels(conf):
        filled = int(df[col].notna().sum()) if not df.empty else 0
        lines.append(f'- {label}: {filled}/{period_days} ({filled / period_days:.0%})')
    for col, label in schema.text_labels(conf):
        filled = (int((df[col].astype(str).str.len() > 0).sum())
                  if not df.empty else 0)
        lines.append(f'- {label}: {filled}/{period_days} ({filled / period_days:.0%})')
    return '\n'.join(lines)
