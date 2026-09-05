#!/usr/bin/env python
# coding: utf-8
"""
週次隔（Interval）睡眠レポート生成スクリプト
7日間ごとの平均値を算出し、前週比の変化を可視化する。

Usage:
    python generate_sleep_report_interval.py [--weeks <N>]
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# プロジェクトルートをパスに追加
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / 'src'))

from lib.analytics import sleep
from lib.utils.private_data import ensure_dir

# データファイルパス
BASE_DIR = project_root
MASTER_CSV = BASE_DIR / 'data/wearable/sleep.csv'
LEVELS_CSV = BASE_DIR / 'data/wearable/sleep_levels.csv'


def calc_weekday_stats(df):
    """
    曜日別の睡眠統計を計算

    Parameters
    ----------
    df : DataFrame
        主睡眠データ（index: dateOfSleep）

    Returns
    -------
    dict
        曜日別統計（weekday_stats, weekday_vs_weekend）
    """
    df_copy = df.copy()
    df_copy['weekday'] = df_copy.index.dayofweek  # 0=月曜, 6=日曜
    df_copy['weekday_name'] = df_copy.index.day_name()
    df_copy['is_weekend'] = df_copy['weekday'].isin([5, 6])  # 土日

    # 曜日ごとの集計
    weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    weekday_stats = []

    for day_name in weekday_order:
        day_data = df_copy[df_copy['weekday_name'] == day_name]
        if len(day_data) == 0:
            continue

        total_sleep = day_data['minutesAsleep'].mean()
        stats = {
            'weekday': day_name,
            'weekday_ja': ['月', '火', '水', '木', '金', '土', '日'][weekday_order.index(day_name)],
            'count': len(day_data),
            'sleep_hours': day_data['minutesAsleep'].mean() / 60,
            'efficiency': day_data['efficiency'].mean(),
            'deep_pct': (day_data['deepMinutes'].mean() / total_sleep * 100) if total_sleep > 0 else 0,
            'rem_pct': (day_data['remMinutes'].mean() / total_sleep * 100) if total_sleep > 0 else 0,
            'light_pct': (day_data['lightMinutes'].mean() / total_sleep * 100) if total_sleep > 0 else 0,
        }
        weekday_stats.append(stats)

    # 平日 vs 週末
    weekday_data = df_copy[~df_copy['is_weekend']]
    weekend_data = df_copy[df_copy['is_weekend']]

    weekday_vs_weekend = None
    if len(weekday_data) > 0 and len(weekend_data) > 0:
        weekday_total = weekday_data['minutesAsleep'].mean()
        weekend_total = weekend_data['minutesAsleep'].mean()

        weekday_vs_weekend = {
            'weekday': {
                'sleep_hours': weekday_data['minutesAsleep'].mean() / 60,
                'efficiency': weekday_data['efficiency'].mean(),
                'deep_pct': (weekday_data['deepMinutes'].mean() / weekday_total * 100) if weekday_total > 0 else 0,
                'rem_pct': (weekday_data['remMinutes'].mean() / weekday_total * 100) if weekday_total > 0 else 0,
            },
            'weekend': {
                'sleep_hours': weekend_data['minutesAsleep'].mean() / 60,
                'efficiency': weekend_data['efficiency'].mean(),
                'deep_pct': (weekend_data['deepMinutes'].mean() / weekend_total * 100) if weekend_total > 0 else 0,
                'rem_pct': (weekend_data['remMinutes'].mean() / weekend_total * 100) if weekend_total > 0 else 0,
            },
            'diff': {
                'sleep_hours': weekend_data['minutesAsleep'].mean() / 60 - weekday_data['minutesAsleep'].mean() / 60,
                'efficiency': weekend_data['efficiency'].mean() - weekday_data['efficiency'].mean(),
            }
        }

    return {
        'weekday_stats': weekday_stats,
        'weekday_vs_weekend': weekday_vs_weekend
    }


def prepare_interval_report_data(weekly, sleep_debt_weekly, weekday_data=None):
    """
    週次隔レポート用のコンテキストデータを準備

    Parameters
    ----------
    weekly : DataFrame
        週次集計データ（index: (iso_year, iso_week)）
    sleep_debt_weekly : DataFrame or None
        週次睡眠負債データ（index: (iso_year, iso_week)）
    weekday_data : dict or None
        曜日別統計データ

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    from lib.templates.filters import format_change

    # 週次データを降順でソート（最新が上）
    weekly_desc = weekly.sort_index(ascending=False)

    # 週次データリストを構築
    weekly_data = []
    for (year, week), row in weekly_desc.iterrows():
        # 週の開始日（月曜）を計算
        try:
            d = str(year) + '-W' + str(week) + '-1'
            start_date_obj = datetime.strptime(d, "%G-W%V-%u")
            week_label = f"{year}-W{week:02d}"
        except:
            week_label = f"{year}-W{week:02d}"

        # 睡眠負債データを取得
        debt_value = '-'
        debt_diff = '-'
        if sleep_debt_weekly is not None and (year, week) in sleep_debt_weekly.index:
            debt_row = sleep_debt_weekly.loc[(year, week)]
            debt_value = f"{debt_row['sleep_debt_hours']:.1f}h"
            if pd.notna(debt_row['debt_diff']):
                debt_diff = format_change(debt_row['debt_diff'], 'h', positive_is_good=False)

        weekly_data.append({
            'week_label': week_label,
            'sleep_hours': f"{row['sleep_hours']:.1f}h",
            'sleep_diff': format_change(row['sleep_diff'], 'h'),
            'efficiency': f"{row['efficiency']:.0f}%",
            'efficiency_diff': format_change(row['efficiency_diff'], '%'),
            'deep_pct': f"{row['deep_pct']:.1f}%",
            'deep_diff': format_change(row['deep_diff'], '%'),
            'rem_pct': f"{row['rem_pct']:.1f}%",
            'rem_diff': format_change(row['rem_diff'], '%'),
            'debt_value': debt_value,
            'debt_diff': debt_diff,
            'bedtime_std': f"{row['bedtime_std']:.0f}分",
            'wakeup_std': f"{row['wakeup_std']:.0f}分" if pd.notna(row.get('wakeup_std')) else '-',
        })

    context = {
        'report_title': '😴 睡眠週次レポート',
        'description': '7日間平均値の推移。前週比でトレンドを確認。',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'weekly_data': weekly_data,
        'trend_image': 'img/sleep_trend.png',
        'debt_trend_image': 'img/debt_trend.png' if sleep_debt_weekly is not None else None,
        'weekday_stats': weekday_data.get('weekday_stats') if weekday_data else None,
        'weekday_vs_weekend': weekday_data.get('weekday_vs_weekend') if weekday_data else None,
        'weekday_image': 'img/weekday_comparison.png' if weekday_data else None,
    }

    return context


def main():
    import argparse

    parser = argparse.ArgumentParser(description='睡眠週次隔レポート生成')
    parser.add_argument('--weeks', type=int, default=8, help='表示する週数')
    parser.add_argument('--output', type=Path, default=BASE_DIR / 'reports/sleep/interval/REPORT.md')
    args = parser.parse_args()

    # データ読み込み
    if not MASTER_CSV.exists():
        print(f"Error: {MASTER_CSV} not found")
        return 1

    print('='*60)
    print('睡眠週次隔レポート生成')
    print('='*60)
    print()

    df_all = pd.read_csv(MASTER_CSV)

    # 主睡眠のみを抽出
    df = df_all[df_all['isMainSleep'] == True].copy()
    df['dateOfSleep'] = pd.to_datetime(df['dateOfSleep'])
    df = df.set_index('dateOfSleep').sort_index()

    # ISO週番号でグルーピング（月曜始まり〜日曜終わり）
    df['iso_year'] = df.index.isocalendar().year
    df['iso_week'] = df.index.isocalendar().week

    # 就寝・起床時刻を時刻型に変換
    df['bedtime'] = pd.to_datetime(df['startTime'])
    if 'endTime' in df.columns:
        df['wakeup_time'] = pd.to_datetime(df['endTime'])

    # 週ごとの集計
    weekly_list = []
    for (year, week), group in df.groupby(['iso_year', 'iso_week']):
        # 睡眠時間（分→時間）
        sleep_hours = group['minutesAsleep'].mean() / 60

        # 効率
        efficiency = group['efficiency'].mean()

        # ステージ割合
        total_sleep = group['minutesAsleep'].mean()
        deep_pct = (group['deepMinutes'].mean() / total_sleep * 100) if total_sleep > 0 else 0
        rem_pct = (group['remMinutes'].mean() / total_sleep * 100) if total_sleep > 0 else 0

        # 時刻のばらつき（標準偏差を分単位で計算）
        bedtime_std = 0
        if len(group['bedtime']) > 1:
            # 時刻を分単位に変換して標準偏差を計算
            bedtime_minutes = group['bedtime'].dt.hour * 60 + group['bedtime'].dt.minute
            # 深夜の時刻（0-4時）は24時間後として扱う
            bedtime_minutes = bedtime_minutes.apply(lambda x: x + 24*60 if x < 4*60 else x)
            bedtime_std = bedtime_minutes.std()

        wakeup_std = None
        if 'wakeup_time' in group.columns and len(group['wakeup_time'].dropna()) > 1:
            wakeup_minutes = group['wakeup_time'].dt.hour * 60 + group['wakeup_time'].dt.minute
            wakeup_std = wakeup_minutes.std()

        weekly_list.append({
            'iso_year': year,
            'iso_week': week,
            'sleep_hours': sleep_hours,
            'efficiency': efficiency,
            'deep_pct': deep_pct,
            'rem_pct': rem_pct,
            'bedtime_std': bedtime_std,
            'wakeup_std': wakeup_std,
            'days_count': len(group)
        })

    weekly = pd.DataFrame(weekly_list)
    weekly = weekly.set_index(['iso_year', 'iso_week']).sort_index()

    # 指標ごとの前週差分（Delta）を計算
    weekly['sleep_diff'] = weekly['sleep_hours'].diff()
    weekly['efficiency_diff'] = weekly['efficiency'].diff()
    weekly['deep_diff'] = weekly['deep_pct'].diff()
    weekly['rem_diff'] = weekly['rem_pct'].diff()

    # 睡眠負債の週次集計（全睡眠データを使用）
    sleep_debt_weekly = None
    try:
        # 日別総睡眠時間を集計（主睡眠+昼寝）
        df_all['dateOfSleep'] = pd.to_datetime(df_all['dateOfSleep'])
        df_daily_total = df_all.groupby('dateOfSleep', as_index=False).agg({
            'minutesAsleep': 'sum'
        })

        # 最適睡眠時間を推定（簡易版：直近データから計算）
        sleep_need_hours = df_daily_total['minutesAsleep'].quantile(0.96) / 60  # 上位4%の平均的な値

        # 週ごとに睡眠負債を計算
        debt_list = []
        for (year, week) in weekly.index:
            # その週のデータを取得
            week_dates = df_daily_total[
                (df_daily_total['dateOfSleep'].dt.isocalendar().year == year) &
                (df_daily_total['dateOfSleep'].dt.isocalendar().week == week)
            ]

            if len(week_dates) > 0:
                # 週末時点での累積負債を簡易計算（過去14日分の不足累積）
                end_date = week_dates['dateOfSleep'].max()
                recent_14d = df_daily_total[
                    (df_daily_total['dateOfSleep'] <= end_date) &
                    (df_daily_total['dateOfSleep'] > end_date - pd.Timedelta(days=14))
                ]

                if len(recent_14d) >= 5:  # 最低5日分のデータが必要
                    avg_sleep = recent_14d['minutesAsleep'].mean() / 60
                    sleep_debt = (sleep_need_hours - avg_sleep) * 14  # 14日分の累積

                    debt_list.append({
                        'iso_year': year,
                        'iso_week': week,
                        'sleep_debt_hours': sleep_debt
                    })

        if debt_list:
            sleep_debt_weekly = pd.DataFrame(debt_list)
            sleep_debt_weekly = sleep_debt_weekly.set_index(['iso_year', 'iso_week']).sort_index()
            sleep_debt_weekly['debt_diff'] = sleep_debt_weekly['sleep_debt_hours'].diff()
    except Exception as e:
        print(f'警告: 睡眠負債の計算をスキップ - {e}')
        sleep_debt_weekly = None

    # 直近N週間に絞る
    weekly = weekly.tail(args.weeks)
    if sleep_debt_weekly is not None:
        sleep_debt_weekly = sleep_debt_weekly.loc[weekly.index]

    # 曜日別統計を計算
    weekday_data = calc_weekday_stats(df)

    # トレンドグラフ生成
    img_dir = args.output.parent / 'img'
    ensure_dir(img_dir)

    print('プロット中: 睡眠トレンド...')
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle('Sleep Weekly Trend', fontsize=14, fontweight='bold')

    # 週ラベル作成
    week_labels = [f"{year}-W{week:02d}" for year, week in weekly.index]

    # 睡眠時間
    axes[0, 0].plot(week_labels, weekly['sleep_hours'], marker='o', linewidth=2)
    axes[0, 0].set_title('Average Sleep Hours')
    axes[0, 0].set_ylabel('Hours')
    axes[0, 0].grid(True, alpha=0.3)
    axes[0, 0].tick_params(axis='x', rotation=45)

    # 睡眠効率
    axes[0, 1].plot(week_labels, weekly['efficiency'], marker='o', linewidth=2, color='green')
    axes[0, 1].axhline(y=85, color='red', linestyle='--', alpha=0.5, label='Target 85%')
    axes[0, 1].set_title('Average Sleep Efficiency')
    axes[0, 1].set_ylabel('%')
    axes[0, 1].grid(True, alpha=0.3)
    axes[0, 1].legend()
    axes[0, 1].tick_params(axis='x', rotation=45)

    # 深い睡眠割合
    axes[1, 0].plot(week_labels, weekly['deep_pct'], marker='o', linewidth=2, color='blue')
    axes[1, 0].set_title('Deep Sleep %')
    axes[1, 0].set_ylabel('%')
    axes[1, 0].grid(True, alpha=0.3)
    axes[1, 0].tick_params(axis='x', rotation=45)

    # REM睡眠割合
    axes[1, 1].plot(week_labels, weekly['rem_pct'], marker='o', linewidth=2, color='purple')
    axes[1, 1].set_title('REM Sleep %')
    axes[1, 1].set_ylabel('%')
    axes[1, 1].grid(True, alpha=0.3)
    axes[1, 1].tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.savefig(img_dir / 'sleep_trend.png', dpi=100, bbox_inches='tight')
    plt.close()

    # 睡眠負債トレンド
    if sleep_debt_weekly is not None:
        print('プロット中: 睡眠負債トレンド...')
        plt.figure(figsize=(10, 5))
        plt.plot(week_labels, sleep_debt_weekly['sleep_debt_hours'], marker='o', linewidth=2, color='red')
        plt.axhline(y=0, color='green', linestyle='--', alpha=0.5, label='No Debt')
        plt.title('Sleep Debt Trend', fontsize=14, fontweight='bold')
        plt.ylabel('Debt Hours')
        plt.xlabel('Week')
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig(img_dir / 'debt_trend.png', dpi=100, bbox_inches='tight')
        plt.close()

    # 曜日別比較グラフ
    if weekday_data and weekday_data['weekday_stats']:
        print('プロット中: 曜日別比較...')
        stats = weekday_data['weekday_stats']
        # 英語の曜日短縮形を使用（Mon, Tue, Wed, Thu, Fri, Sat, Sun）
        days_en = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        sleep_hours = [s['sleep_hours'] for s in stats]
        efficiency = [s['efficiency'] for s in stats]
        deep_pct = [s['deep_pct'] for s in stats]
        rem_pct = [s['rem_pct'] for s in stats]

        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        fig.suptitle('Weekday Comparison', fontsize=14, fontweight='bold')

        # 睡眠時間
        axes[0, 0].bar(days_en, sleep_hours, color='steelblue', alpha=0.7)
        axes[0, 0].axhline(y=7, color='red', linestyle='--', alpha=0.5, label='Target 7h')
        axes[0, 0].set_title('Average Sleep Hours by Weekday')
        axes[0, 0].set_ylabel('Hours')
        axes[0, 0].legend()
        axes[0, 0].grid(True, alpha=0.3, axis='y')

        # 睡眠効率
        axes[0, 1].bar(days_en, efficiency, color='green', alpha=0.7)
        axes[0, 1].axhline(y=85, color='red', linestyle='--', alpha=0.5, label='Target 85%')
        axes[0, 1].set_title('Average Sleep Efficiency by Weekday')
        axes[0, 1].set_ylabel('%')
        axes[0, 1].legend()
        axes[0, 1].grid(True, alpha=0.3, axis='y')

        # 深い睡眠割合
        axes[1, 0].bar(days_en, deep_pct, color='blue', alpha=0.7)
        axes[1, 0].set_title('Deep Sleep % by Weekday')
        axes[1, 0].set_ylabel('%')
        axes[1, 0].grid(True, alpha=0.3, axis='y')

        # REM睡眠割合
        axes[1, 1].bar(days_en, rem_pct, color='purple', alpha=0.7)
        axes[1, 1].set_title('REM Sleep % by Weekday')
        axes[1, 1].set_ylabel('%')
        axes[1, 1].grid(True, alpha=0.3, axis='y')

        plt.tight_layout()
        plt.savefig(img_dir / 'weekday_comparison.png', dpi=100, bbox_inches='tight')
        plt.close()

    # コンテキストデータ準備
    context = prepare_interval_report_data(
        weekly=weekly,
        sleep_debt_weekly=sleep_debt_weekly,
        weekday_data=weekday_data
    )

    # テンプレートレンダリング
    from lib.templates.renderer import SleepReportRenderer
    renderer = SleepReportRenderer()
    report_content = renderer.render_interval_report(context)

    # レポート出力
    output_path = args.output
    ensure_dir(output_path.parent)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print()
    print('='*60)
    print('レポート生成完了!')
    print('='*60)
    print(f'レポート: {output_path}')
    print(f'画像: {img_dir}/')

    return 0


if __name__ == "__main__":
    sys.exit(main())
