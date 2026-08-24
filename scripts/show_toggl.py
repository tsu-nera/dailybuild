#!/usr/bin/env python
# coding: utf-8
"""
Toggl Track タイムエントリのサマリ表示スクリプト

data/toggl/time_entries.csv（dailybuild-private への symlink）を読んで
日次・週次のサマリを標準出力に出す。Toggl API は一切叩かないので
fetch_toggl.py のレートリミット枠（/me/* 共通 30 req/h）を消費しない。

Usage:
    python scripts/show_toggl.py --days 7             # 日次（直近7日）
    python scripts/show_toggl.py --update             # 取得してから表示
    python scripts/show_toggl.py --list               # 時系列のエントリ一覧
    python scripts/show_toggl.py --unit week --days 56  # 週次
    python scripts/show_toggl.py --week current
    python scripts/show_toggl.py --month 8
"""

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lib.utils.private_data import require_private_path
from lib.utils.report_args import filter_dataframe_by_period, parse_period_args

BASE_DIR = Path(__file__).parent.parent
CSV_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'time_entries.csv')

NO_PROJECT = '(no project)'
WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']


def run_update() -> None:
    """fetch_toggl.py --update を実行して CSV を最新化する。

    取得側のログは stderr に流す。stdout は markdown だけに保ち、
    パイプやリダイレクトで表がそのまま使えるようにするため。
    """
    script = Path(__file__).with_name('fetch_toggl.py')
    result = subprocess.run(
        [sys.executable, str(script), '--update'],
        capture_output=True, text=True,
    )
    if result.stdout:
        print(result.stdout, end='', file=sys.stderr)
    if result.returncode != 0:
        print(result.stderr, end='', file=sys.stderr)
        sys.exit(result.returncode)


def format_duration(seconds) -> str:
    """秒を 3h25m 形式に。1時間未満は 25m"""
    if pd.isna(seconds):
        return '-'
    total_min = int(round(seconds / 60))
    hours, minutes = divmod(total_min, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def load_entries() -> pd.DataFrame:
    df = pd.read_csv(CSV_FILE, parse_dates=['start', 'stop'])
    df['project_name'] = df['project_name'].fillna(NO_PROJECT)
    # 日跨ぎエントリは開始日に全量を計上する（分割はしない）
    df['date'] = df['start'].dt.normalize()
    return df.sort_values('start')


def add_bucket(df: pd.DataFrame, unit: str) -> pd.DataFrame:
    """集計単位の列 bucket を付与する"""
    df = df.copy()
    if unit == 'week':
        iso = df['date'].dt.isocalendar()
        df['bucket'] = iso['year'].astype(str) + '-W' + iso['week'].astype(int).map('{:02d}'.format)
    else:
        df['bucket'] = df['date'].dt.strftime('%Y-%m-%d')
    return df


def render_totals(df: pd.DataFrame, unit: str) -> str:
    """集計単位ごとの合計（週次では稼働日数と日平均も）"""
    grouped = df.groupby('bucket').agg(
        total_sec=('duration_sec', 'sum'),
        days=('date', 'nunique'),
    )
    out = pd.DataFrame({
        '合計': grouped['total_sec'].map(format_duration),
    }, index=grouped.index)
    if unit == 'week':
        out['稼働日数'] = grouped['days']
        out['日平均'] = (grouped['total_sec'] / grouped['days']).map(format_duration)
    out.index.name = '週' if unit == 'week' else '日'
    return out.to_markdown()


def render_project_matrix(df: pd.DataFrame, unit: str) -> str:
    """bucket × project のクロス集計"""
    pivot = df.pivot_table(
        index='bucket', columns='project_name',
        values='duration_sec', aggfunc='sum',
    )
    # 合計の多いプロジェクトを左に
    order = pivot.sum().sort_values(ascending=False).index
    pivot = pivot[order]
    pivot.index.name = '週' if unit == 'week' else '日'
    return pivot.map(format_duration).fillna('-').to_markdown()


def render_entries(df: pd.DataFrame) -> str:
    """エントリを時系列に並べ、日ごとの見出しで区切って出す"""
    blocks = []
    for date, day_df in df.groupby('date', sort=True):
        heading = f"## {date.strftime('%Y-%m-%d')}（{WEEKDAY_JA[date.weekday()]}）"

        rows = pd.DataFrame({
            '時刻': (day_df['start'].dt.strftime('%H:%M') + ' - '
                     + day_df['stop'].dt.strftime('%H:%M')),
            '時間': day_df['duration_sec'].map(format_duration),
            'プロジェクト': day_df['project_name'],
            'description': day_df['description'].fillna('').replace('', '-'),
        })
        total = format_duration(day_df['duration_sec'].sum())
        blocks.append(f"{heading}  合計 {total}\n\n{rows.to_markdown(index=False)}")

    return '\n\n'.join(blocks)


def render_project_totals(df: pd.DataFrame) -> str:
    """期間全体のプロジェクト別合計と構成比"""
    grouped = df.groupby('project_name')['duration_sec'].sum()
    grouped = grouped.sort_values(ascending=False)
    total = grouped.sum()
    out = pd.DataFrame({
        '合計': grouped.map(format_duration),
        '構成比': (grouped / total * 100).map('{:.1f}%'.format),
    }, index=grouped.index)
    out.index.name = 'プロジェクト'
    return out.to_markdown()


def main():
    parser = argparse.ArgumentParser(description='Toggl タイムエントリのサマリを表示')
    parser.add_argument('--unit', choices=['day', 'week'], default='day',
                        help='集計単位（デフォルト: day）')
    parser.add_argument('--days', type=int, default=None,
                        help='直近N日（--week/--month 未指定時のデフォルト: --list=1, day=7, week=28）')
    parser.add_argument('--week', type=str, default=None,
                        help='ISO週番号（例: 34）または "current"')
    parser.add_argument('--month', type=str, default=None,
                        help='月番号（例: 8）または "current"')
    parser.add_argument('--year', type=int, default=None,
                        help='年（--week/--month 指定時に使用）')
    parser.add_argument('--list', action='store_true',
                        help='集計せずエントリを時系列で一覧表示する')
    parser.add_argument('--update', action='store_true',
                        help='表示前に fetch_toggl.py --update で最新データを取得する')
    args = parser.parse_args()

    if args.update:
        run_update()

    if not CSV_FILE.exists():
        print(f"エラー: {CSV_FILE} が存在しません", file=sys.stderr)
        sys.exit(1)

    week, month, year = parse_period_args(args)
    days = args.days
    if days is None and week is None and month is None:
        if args.list:
            days = 1
        else:
            days = 28 if args.unit == 'week' else 7

    df = load_entries()
    df = filter_dataframe_by_period(
        df=df, date_column='date',
        week=week, month=month, year=year, days=days,
    )

    if df.empty:
        print('該当期間のエントリがありません', file=sys.stderr)
        sys.exit(1)

    start = df['date'].min().strftime('%Y-%m-%d')
    end = df['date'].max().strftime('%Y-%m-%d')

    if args.list:
        print(f"# Toggl エントリ一覧（{start} 〜 {end}）\n")
        print(render_entries(df))
        return

    df = add_bucket(df, args.unit)

    unit_label = '週次' if args.unit == 'week' else '日次'
    print(f"# Toggl サマリ（{unit_label}: {start} 〜 {end}）\n")

    print(f"## {unit_label}合計\n")
    print(render_totals(df, args.unit))
    print()

    print("## プロジェクト別内訳\n")
    print(render_project_matrix(df, args.unit))
    print()

    print("## プロジェクト別合計（期間全体）\n")
    print(render_project_totals(df))


if __name__ == '__main__':
    main()
