"""
Toggl タイムエントリの markdown 出力

pandas 以外の外部依存を持たない。CSV の読み込みは store.py が担う。
"""

import pandas as pd

WEEKDAY_JA = ['月', '火', '水', '木', '金', '土', '日']


def format_duration(seconds) -> str:
    """秒を 3h25m 形式に。1時間未満は 25m"""
    if pd.isna(seconds):
        return '-'
    total_min = int(round(seconds / 60))
    hours, minutes = divmod(total_min, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


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
