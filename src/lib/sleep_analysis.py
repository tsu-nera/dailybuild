#!/usr/bin/env python
# coding: utf-8
"""
睡眠データ分析・可視化ライブラリ

Fitbit APIから取得した睡眠データの分析と可視化を行う。
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import timedelta


# =============================================================================
# 定数
# =============================================================================

# 睡眠ステージの色設定（Fitbitアプリ風）
STAGE_COLORS = {
    'wake': '#FF9500',   # オレンジ
    'rem': '#9B59B6',    # 紫
    'light': '#5DADE2',  # 水色
    'deep': '#2E4053',   # 濃紺
}

# Y軸の位置（上から wake, rem, light, deep）
STAGE_Y_POSITION = {
    'wake': 3,
    'rem': 2,
    'light': 1,
    'deep': 0,
}


# =============================================================================
# 統計分析
# =============================================================================

def _time_to_minutes(dt):
    """datetimeを0:00からの分数に変換（深夜跨ぎ対応）"""
    minutes = dt.hour * 60 + dt.minute
    # 18時以降は前日扱い（負の値にして平均計算を正しくする）
    if minutes >= 18 * 60:
        minutes -= 24 * 60
    return minutes


def _minutes_to_time_str(minutes):
    """分数を HH:MM 形式に変換"""
    if minutes < 0:
        minutes += 24 * 60
    hours = int(minutes // 60) % 24
    mins = int(minutes % 60)
    return f"{hours:02d}:{mins:02d}"


def calc_sleep_stats(df_master, recommended_hours=7.0):
    """
    睡眠サマリーデータから基本統計を計算

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame
        recommended_hours: 推奨睡眠時間（デフォルト7時間）

    Returns:
        dict: 統計情報
    """
    df = df_master.copy()
    df['sleepHours'] = df['minutesAsleep'] / 60

    stats = {
        'period': {
            'start': df['dateOfSleep'].min() if 'dateOfSleep' in df.columns else df.index.min(),
            'end': df['dateOfSleep'].max() if 'dateOfSleep' in df.columns else df.index.max(),
            'days': len(df),
        },
        'duration': {
            'mean_hours': df['sleepHours'].mean(),
            'mean_minutes': df['minutesAsleep'].mean(),
            'min_hours': df['sleepHours'].min(),
            'max_hours': df['sleepHours'].max(),
            'std_hours': df['sleepHours'].std(),
        },
        'efficiency': {
            'mean': df['efficiency'].mean(),
            'min': df['efficiency'].min(),
            'max': df['efficiency'].max(),
        },
        'stages': {
            'deep_minutes': df['deepMinutes'].mean(),
            'light_minutes': df['lightMinutes'].mean(),
            'rem_minutes': df['remMinutes'].mean(),
            'wake_minutes': df['wakeMinutes'].mean(),
            'deep_count': df['deepCount'].mean(),
            'light_count': df['lightCount'].mean(),
            'rem_count': df['remCount'].mean(),
        },
    }

    # ステージ割合を計算
    total = stats['duration']['mean_minutes']
    if total > 0:
        stats['stages']['deep_pct'] = stats['stages']['deep_minutes'] / total * 100
        stats['stages']['light_pct'] = stats['stages']['light_minutes'] / total * 100
        stats['stages']['rem_pct'] = stats['stages']['rem_minutes'] / total * 100

    # 就寝・起床時刻の統計
    if 'startTime' in df.columns and 'endTime' in df.columns:
        df['startTime_dt'] = pd.to_datetime(df['startTime'])
        df['endTime_dt'] = pd.to_datetime(df['endTime'])

        bedtime_minutes = df['startTime_dt'].apply(_time_to_minutes)
        waketime_minutes = df['endTime_dt'].apply(_time_to_minutes)

        stats['bedtime'] = {
            'mean': _minutes_to_time_str(bedtime_minutes.mean()),
            'std_minutes': bedtime_minutes.std(),
            'earliest': _minutes_to_time_str(bedtime_minutes.min()),
            'latest': _minutes_to_time_str(bedtime_minutes.max()),
        }
        stats['waketime'] = {
            'mean': _minutes_to_time_str(waketime_minutes.mean()),
            'std_minutes': waketime_minutes.std(),
            'earliest': _minutes_to_time_str(waketime_minutes.min()),
            'latest': _minutes_to_time_str(waketime_minutes.max()),
        }

    # 睡眠負債の計算
    recommended_minutes = recommended_hours * 60
    df['sleep_debt_minutes'] = df['minutesAsleep'] - recommended_minutes
    stats['sleep_debt'] = {
        'total_minutes': df['sleep_debt_minutes'].sum(),
        'total_hours': df['sleep_debt_minutes'].sum() / 60,
        'daily_avg_minutes': df['sleep_debt_minutes'].mean(),
        'recommended_hours': recommended_hours,
        'days_met_goal': (df['minutesAsleep'] >= recommended_minutes).sum(),
    }

    # 週間合計
    stats['weekly_total'] = {
        'time_in_bed_minutes': df['timeInBed'].sum(),
        'time_in_bed_hours': df['timeInBed'].sum() / 60,
        'minutes_asleep': df['minutesAsleep'].sum(),
        'hours_asleep': df['minutesAsleep'].sum() / 60,
    }

    return stats


def calc_sleep_timing(df_levels):
    """
    睡眠レベルデータから入眠潜時と起床後時間を計算

    Args:
        df_levels: sleep_levels.csvを読み込んだDataFrame

    Returns:
        dict: 日付をキーとした入眠潜時・起床後時間の辞書
    """
    df = df_levels.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['dateTime']):
        df['dateTime'] = pd.to_datetime(df['dateTime'])

    results = {}
    for date in df['dateOfSleep'].unique():
        day = df[df['dateOfSleep'] == date].sort_values('dateTime')
        main_sleep = day[day['isShort'] == False]

        if len(main_sleep) == 0:
            continue

        # 入眠潜時: 最初がwakeなら、そのseconds
        first = main_sleep.iloc[0]
        fall_asleep = first['seconds'] / 60 if first['level'] == 'wake' else 0

        # 起床後: 最後がwakeなら、そのseconds
        last = main_sleep.iloc[-1]
        after_wake = last['seconds'] / 60 if last['level'] == 'wake' else 0

        results[date] = {
            'minutes_to_fall_asleep': fall_asleep,
            'minutes_after_wakeup': after_wake,
        }

    return results


def print_sleep_stats(stats):
    """統計情報を整形して出力"""
    print("=== 睡眠データ基本情報 ===")
    print(f"期間: {stats['period']['start']} ～ {stats['period']['end']}")
    print(f"データ件数: {stats['period']['days']}日分\n")

    print("=== 睡眠時間の統計 ===")
    print(f"平均睡眠時間: {stats['duration']['mean_hours']:.1f}時間 ({stats['duration']['mean_minutes']:.0f}分)")
    print(f"最短: {stats['duration']['min_hours']:.1f}時間")
    print(f"最長: {stats['duration']['max_hours']:.1f}時間")
    print(f"標準偏差: {stats['duration']['std_hours']:.1f}時間\n")

    print("=== 睡眠効率 ===")
    print(f"平均効率: {stats['efficiency']['mean']:.1f}%")
    print(f"最低: {stats['efficiency']['min']}%")
    print(f"最高: {stats['efficiency']['max']}%\n")

    print("=== 睡眠ステージ平均 ===")
    print(f"深い睡眠: {stats['stages']['deep_minutes']:.0f}分 ({stats['stages'].get('deep_pct', 0):.1f}%)")
    print(f"浅い睡眠: {stats['stages']['light_minutes']:.0f}分 ({stats['stages'].get('light_pct', 0):.1f}%)")
    print(f"レム睡眠: {stats['stages']['rem_minutes']:.0f}分 ({stats['stages'].get('rem_pct', 0):.1f}%)")
    print(f"覚醒: {stats['stages']['wake_minutes']:.0f}分")


# =============================================================================
# 可視化: 個別グラフ
# =============================================================================

def _prepare_df_for_plot(df_master):
    """プロット用にDataFrameを準備"""
    df = df_master.copy()
    df['sleepHours'] = df['minutesAsleep'] / 60

    if 'dateOfSleep' in df.columns:
        dates = df['dateOfSleep']
    else:
        dates = df.index

    date_labels = [pd.to_datetime(d).strftime('%m/%d') for d in dates]
    return df, date_labels


def plot_sleep_duration(df_master, save_path=None):
    """
    睡眠時間の推移グラフ

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame
        save_path: 保存先パス
    """
    df, date_labels = _prepare_df_for_plot(df_master)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(range(len(df)), df['sleepHours'], color='steelblue', alpha=0.7)
    ax.axhline(y=7, color='green', linestyle='--', label='Recommended (7h)')
    ax.axhline(y=df['sleepHours'].mean(), color='red', linestyle='--',
               label=f'Average ({df["sleepHours"].mean():.1f}h)')
    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(date_labels, rotation=45)
    ax.set_ylabel('Hours')
    ax.set_title('Sleep Duration')
    ax.legend()
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, ax


def plot_time_in_bed_stacked(df_master, save_path=None):
    """
    Time in Bedの内訳積み上げグラフ（入眠/睡眠/覚醒/起後）

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame
        save_path: 保存先パス
    """
    df, date_labels = _prepare_df_for_plot(df_master)

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(df))

    # 入眠潜時
    fall_asleep = df['minutesToFallAsleep'].fillna(0)
    # 睡眠時間
    asleep = df['minutesAsleep']
    # 中途覚醒
    wake = df['wakeMinutes'].fillna(0)
    # 起床後
    after_wakeup = df['minutesAfterWakeup'].fillna(0)

    # 積み上げグラフ
    ax.bar(x, fall_asleep, label='Fall Asleep', color='#FFB74D')  # オレンジ
    ax.bar(x, asleep, bottom=fall_asleep, label='Asleep', color='#4FC3F7')  # 水色
    ax.bar(x, wake, bottom=fall_asleep + asleep, label='Wake', color='#EF5350')  # 赤
    ax.bar(x, after_wakeup, bottom=fall_asleep + asleep + wake, label='After Wake', color='#AB47BC')  # 紫

    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(date_labels, rotation=45)
    ax.set_ylabel('Minutes')
    ax.set_title('Time in Bed Breakdown')
    ax.legend(loc='upper right')
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, ax


def plot_sleep_stages_stacked(df_master, save_path=None, show_guidelines=True):
    """
    睡眠ステージの積み上げグラフ（推奨ライン・平均ライン付き）

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame
        save_path: 保存先パス
        show_guidelines: 推奨ライン(7h)と平均ラインを表示するか
    """
    df, date_labels = _prepare_df_for_plot(df_master)

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(df))
    ax.bar(x, df['deepMinutes'], label='Deep', color=STAGE_COLORS['deep'])
    ax.bar(x, df['lightMinutes'], bottom=df['deepMinutes'],
           label='Light', color=STAGE_COLORS['light'])
    ax.bar(x, df['remMinutes'], bottom=df['deepMinutes'] + df['lightMinutes'],
           label='REM', color=STAGE_COLORS['rem'])

    if show_guidelines:
        avg_minutes = df['minutesAsleep'].mean()
        ax.axhline(y=420, color='green', linestyle='--', linewidth=2, label='Recommended (7h)')
        ax.axhline(y=avg_minutes, color='red', linestyle='--', linewidth=2,
                   label=f'Average ({avg_minutes/60:.1f}h)')

    ax.set_xticks(range(len(df)))
    ax.set_xticklabels(date_labels, rotation=45)
    ax.set_ylabel('Minutes')
    ax.set_title('Sleep Duration & Stages')
    ax.legend(loc='upper right')
    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, ax


def plot_sleep_stages_pie(df_master, save_path=None):
    """
    睡眠ステージの割合（円グラフ）

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame
        save_path: 保存先パス
    """
    df = df_master.copy()

    fig, ax = plt.subplots(figsize=(8, 8))
    stages = ['Deep', 'Light', 'REM', 'Wake']
    values = [df['deepMinutes'].mean(), df['lightMinutes'].mean(),
              df['remMinutes'].mean(), df['wakeMinutes'].mean()]
    colors = [STAGE_COLORS['deep'], STAGE_COLORS['light'],
              STAGE_COLORS['rem'], STAGE_COLORS['wake']]
    ax.pie(values, labels=stages, colors=colors, autopct='%1.1f%%', startangle=90)
    ax.set_title('Average Sleep Stage Distribution')

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, ax


def plot_sleep_dashboard(df_master, save_path=None):
    """
    睡眠サマリーのダッシュボードを作成（4パネル）

    Args:
        df_master: sleep_master.csvを読み込んだDataFrame
        save_path: 保存先パス（Noneの場合は表示のみ）

    Returns:
        fig, axes
    """
    df, date_labels = _prepare_df_for_plot(df_master)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle('Sleep Analysis', fontsize=14)

    # 1. 睡眠時間推移
    ax1 = axes[0, 0]
    ax1.bar(range(len(df)), df['sleepHours'], color='steelblue', alpha=0.7)
    ax1.axhline(y=7, color='green', linestyle='--', label='Recommended (7h)')
    ax1.axhline(y=df['sleepHours'].mean(), color='red', linestyle='--',
                label=f'Average ({df["sleepHours"].mean():.1f}h)')
    ax1.set_xticks(range(len(df)))
    ax1.set_xticklabels(date_labels, rotation=45)
    ax1.set_ylabel('Hours')
    ax1.set_title('Sleep Duration')
    ax1.legend()

    # 2. 睡眠効率
    ax2 = axes[0, 1]
    ax2.plot(range(len(df)), df['efficiency'], marker='o', color='green')
    ax2.axhline(y=85, color='orange', linestyle='--', label='Good threshold (85%)')
    ax2.set_xticks(range(len(df)))
    ax2.set_xticklabels(date_labels, rotation=45)
    ax2.set_ylabel('Efficiency (%)')
    ax2.set_title('Sleep Efficiency')
    ax2.set_ylim(60, 100)
    ax2.legend()

    # 3. 睡眠ステージ積み上げ
    ax3 = axes[1, 0]
    x = range(len(df))
    ax3.bar(x, df['deepMinutes'], label='Deep', color=STAGE_COLORS['deep'])
    ax3.bar(x, df['lightMinutes'], bottom=df['deepMinutes'],
            label='Light', color=STAGE_COLORS['light'])
    ax3.bar(x, df['remMinutes'], bottom=df['deepMinutes'] + df['lightMinutes'],
            label='REM', color=STAGE_COLORS['rem'])
    ax3.set_xticks(range(len(df)))
    ax3.set_xticklabels(date_labels, rotation=45)
    ax3.set_ylabel('Minutes')
    ax3.set_title('Sleep Stages')
    ax3.legend()

    # 4. 睡眠ステージ割合（平均）
    ax4 = axes[1, 1]
    stages = ['Deep', 'Light', 'REM', 'Wake']
    values = [df['deepMinutes'].mean(), df['lightMinutes'].mean(),
              df['remMinutes'].mean(), df['wakeMinutes'].mean()]
    colors = [STAGE_COLORS['deep'], STAGE_COLORS['light'],
              STAGE_COLORS['rem'], STAGE_COLORS['wake']]
    ax4.pie(values, labels=stages, colors=colors, autopct='%1.1f%%', startangle=90)
    ax4.set_title('Average Sleep Stage Distribution')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, axes


# =============================================================================
# 可視化: タイムライン
# =============================================================================

def _plot_single_timeline(df_day, date, ax):
    """1日分の睡眠タイムラインを描画（内部関数）"""
    df_main = df_day[df_day['isShort'] == False].copy()
    df_short = df_day[df_day['isShort'] == True].copy()

    start_time = df_day['dateTime'].min()

    # 各ステージのバーを描画
    for _, row in df_main.iterrows():
        level = row['level']
        start = (row['dateTime'] - start_time).total_seconds() / 3600
        duration = row['seconds'] / 3600
        y = STAGE_Y_POSITION[level]
        ax.barh(y, duration, left=start, height=0.7,
                color=STAGE_COLORS[level], alpha=0.9)

    # 短い覚醒をオーバーレイ
    for _, row in df_short.iterrows():
        start = (row['dateTime'] - start_time).total_seconds() / 3600
        duration = row['seconds'] / 3600
        ax.barh(STAGE_Y_POSITION['wake'], duration, left=start, height=0.3,
                color=STAGE_COLORS['wake'], alpha=0.7)

    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(['Deep', 'Light', 'REM', 'Wake'])
    ax.set_ylim(-0.5, 3.5)

    total_hours = ((df_day['dateTime'].max() - start_time).total_seconds() / 3600
                   + df_day['seconds'].iloc[-1] / 3600)
    ax.set_xlim(0, total_hours)

    xticks = np.arange(0, total_hours + 1, 2)
    xlabels = [(start_time + timedelta(hours=h)).strftime('%H:%M') for h in xticks]
    ax.set_xticks(xticks)
    ax.set_xticklabels(xlabels, rotation=45, ha='right')

    ax.set_title(f'{date}', fontsize=11, fontweight='bold')
    ax.grid(axis='x', alpha=0.3)


def plot_sleep_timeline(df_levels, dates=None, save_path=None):
    """
    睡眠ステージのタイムラインを作成

    Args:
        df_levels: sleep_levels.csvを読み込んだDataFrame
        dates: 表示する日付のリスト（Noneの場合は全日付）
        save_path: 保存先パス（Noneの場合は表示のみ）

    Returns:
        fig, axes
    """
    df = df_levels.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['dateTime']):
        df['dateTime'] = pd.to_datetime(df['dateTime'])

    if dates is None:
        dates = sorted(df['dateOfSleep'].unique())

    n_dates = len(dates)

    fig, axes = plt.subplots(n_dates, 1, figsize=(14, 2.5 * n_dates))
    if n_dates == 1:
        axes = [axes]

    fig.suptitle('Sleep Stage Timeline', fontsize=14, fontweight='bold', y=1.02)

    for ax, date in zip(axes, dates):
        df_day = df[df['dateOfSleep'] == date].sort_values('dateTime')
        _plot_single_timeline(df_day, date, ax)

    # 凡例
    legend_patches = [mpatches.Patch(color=STAGE_COLORS[k], label=k.capitalize())
                      for k in ['wake', 'rem', 'light', 'deep']]
    fig.legend(handles=legend_patches, loc='upper right', bbox_to_anchor=(0.99, 0.99))

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, axes


def plot_single_day_timeline(df_levels, date, save_path=None):
    """
    特定の1日の睡眠タイムラインを作成

    Args:
        df_levels: sleep_levels.csvを読み込んだDataFrame
        date: 表示する日付（文字列 'YYYY-MM-DD'）
        save_path: 保存先パス

    Returns:
        fig, ax
    """
    return plot_sleep_timeline(df_levels, dates=[date], save_path=save_path)
