#!/usr/bin/env python
# coding: utf-8
"""
手動記録データの表示スクリプト

config/manual_metrics_def.yaml のメタ情報（active/unit）を活用し、
スコア表とコメント時系列を分離して読みやすく出力する。
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lib.utils.report_args import filter_dataframe_by_period

BASE_DIR = Path(__file__).parent.parent
METRICS_DEF_FILE = BASE_DIR / 'config/manual_metrics_def.yaml'
DATA_FILE = BASE_DIR / 'data/manual.csv'


def load_metrics_def():
    with open(METRICS_DEF_FILE) as f:
        return yaml.safe_load(f)


def format_header(metric, unit):
    if unit:
        return f"{metric} ({unit})"
    return metric


def render_scores(df, metrics_def):
    active = [d for d in metrics_def if d.get('active') and d['metric'] != 'comment']

    cols = [d['metric'] for d in active if d['metric'] in df.columns]
    score_df = df[cols].dropna(axis=1, how='all')

    if score_df.empty or len(score_df.columns) == 0:
        return "（スコアデータなし）"

    units = {d['metric']: d.get('unit', '') for d in active}
    score_df = score_df.rename(columns={c: format_header(c, units[c]) for c in score_df.columns})
    score_df.index = score_df.index.strftime('%Y-%m-%d')

    return score_df.to_markdown()


def render_comments(df):
    if 'comment' not in df.columns:
        return "（コメント列なし）"

    comments = df['comment'].dropna()
    if comments.empty:
        return "（コメントなし）"

    lines = []
    for date, text in comments.items():
        date_str = date.strftime('%Y-%m-%d')
        text_clean = str(text).replace('\n', ' / ').strip()
        lines.append(f"- **{date_str}**: {text_clean}")
    return '\n'.join(lines)


def render_inactive_warning(df, metrics_def):
    """active=true なのにデータが無い指標を警告"""
    active_metrics = [d['metric'] for d in metrics_def
                      if d.get('active') and d['metric'] != 'comment']
    missing = []
    for m in active_metrics:
        if m not in df.columns or df[m].dropna().empty:
            missing.append(m)
    if not missing:
        return None
    return f"⚠️ 記録運用が停止している可能性のある指標: {', '.join(missing)}"


def main():
    parser = argparse.ArgumentParser(description='手動記録データを表示')
    parser.add_argument('--days', type=int, default=7, help='表示日数（デフォルト: 7）')
    args = parser.parse_args()

    if not DATA_FILE.exists():
        print(f"エラー: {DATA_FILE} が存在しません", file=sys.stderr)
        sys.exit(1)

    metrics_def = load_metrics_def()
    df = pd.read_csv(DATA_FILE, index_col='date', parse_dates=True).sort_index()
    df_recent = filter_dataframe_by_period(
        df=df, date_column='date',
        week=None, month=None, year=None, days=args.days,
        is_index=True
    )

    print(f"# 手動記録（直近{args.days}日）\n")

    print("## 主観・参考スコア\n")
    print(render_scores(df_recent, metrics_def))
    print()

    print("## コメント\n")
    print(render_comments(df_recent))
    print()

    warning = render_inactive_warning(df_recent, metrics_def)
    if warning:
        print(warning)


if __name__ == '__main__':
    main()
