#!/usr/bin/env python
# coding: utf-8
"""
日次睡眠レポート生成スクリプト

lib/sleep.py の関数を使用してマークダウンレポートを生成します。

Usage:
    python generate_sleep_report_daily.py [--output <REPORT_DIR>] [--days <N>]
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

from lib import sleep

# データファイルパス
BASE_DIR = project_root
MASTER_CSV = BASE_DIR / 'data/sleep_master.csv'
LEVELS_CSV = BASE_DIR / 'data/sleep_levels.csv'


def generate_markdown_report(output_dir, results):
    """
    マークダウンレポートを生成

    Parameters
    ----------
    output_dir : Path
        出力ディレクトリ
    results : dict
        分析結果を格納した辞書
    """
    report_path = output_dir / 'REPORT.md'
    stats = results['stats']

    # 睡眠負債の表示用テキスト
    debt = stats['sleep_debt']
    debt_hours = debt['total_hours']
    if debt_hours >= 0:
        debt_text = f"+{debt_hours:.1f}時間（余裕あり）"
    else:
        debt_text = f"{debt_hours:.1f}時間（不足）"

    report = f"""# 日次睡眠レポート

- **生成日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **対象期間**: {stats['period']['start']} ～ {stats['period']['end']}
- **データ日数**: {stats['period']['days']}日分

---

## サマリー

| 指標 | 値 |
|------|-----|
| ベッド時間合計 | {stats['weekly_total']['time_in_bed_hours']:.1f}時間 |
| 睡眠時間合計 | {stats['weekly_total']['hours_asleep']:.1f}時間 |
| 睡眠負債 | **{debt_text}** |
| 目標達成 | {debt['days_met_goal']}/{stats['period']['days']}日（{debt['recommended_hours']:.0f}時間以上） |

> 睡眠負債は推奨{debt['recommended_hours']:.0f}時間との差の累積です。

---

## Time in Bed分析

> ベッド時間の使い方を分析。効率 = 睡眠 / ベッド × 100。85%以上が良好。

| 指標 | 値 |
|------|-----|
| 平均効率 | **{stats['efficiency']['mean']:.1f}%** |
| 最低〜最高 | {stats['efficiency']['min']}% 〜 {stats['efficiency']['max']}% |
| 平均入眠 | {stats.get('timing', {}).get('avg_fall_asleep', 0):.0f}分 |
| 平均起床後 | {stats.get('timing', {}).get('avg_after_wakeup', 0):.0f}分 |

![Time in Bed](img/{results['time_in_bed_img']})

{results['efficiency_table'].to_markdown(index=False)}

---

## Total Sleep Time分析

> 睡眠時間の質を分析。各ステージのバランスを確認。

### 睡眠時間

| 指標 | 値 |
|------|-----|
| 平均 | **{stats['duration']['mean_hours']:.1f}時間** ({stats['duration']['mean_minutes']:.0f}分) |
| 最短〜最長 | {stats['duration']['min_hours']:.1f} 〜 {stats['duration']['max_hours']:.1f}時間 |
| 標準偏差 | {stats['duration']['std_hours']:.1f}時間 |

### 睡眠ステージ（平均）

| ステージ | 時間 | 割合 | 回数 | 推奨範囲 |
|----------|------|------|------|----------|
| 深い睡眠 | {stats['stages']['deep_minutes']:.0f}分 | {stats['stages'].get('deep_pct', 0):.1f}% | {stats['stages']['deep_count']:.0f}回 | 13-23% |
| 浅い睡眠 | {stats['stages']['light_minutes']:.0f}分 | {stats['stages'].get('light_pct', 0):.1f}% | {stats['stages']['light_count']:.0f}回 | 45-55% |
| レム睡眠 | {stats['stages']['rem_minutes']:.0f}分 | {stats['stages'].get('rem_pct', 0):.1f}% | {stats['stages']['rem_count']:.0f}回 | 20-25% |
| 覚醒 | {stats['stages']['wake_minutes']:.0f}分 | - | - | - |

![睡眠時間・ステージ推移](img/{results['stages_stacked_img']})

{results['stages_table'].to_markdown(index=False)}

### 睡眠ステージ タイムライン

![睡眠タイムライン](img/{results['timeline_img']})

- 🟠 覚醒 / 🟣 レム / 🔵 浅い / 🔷 深い

---

## 就寝・起床時刻

> 睡眠リズムの規則性を分析。ばらつきが大きいと社会的時差ボケの原因に。

| 指標 | 就寝 | 入眠 | 起床 | 離床 |
|------|------|------|------|------|
| 平均 | **{stats['bedtime']['mean']}** | **{stats.get('fallasleep', {}).get('mean', '-')}** | **{stats.get('wakeup', {}).get('mean', '-')}** | **{stats['waketime']['mean']}** |
| 最早 | {stats['bedtime']['earliest']} | {stats.get('fallasleep', {}).get('earliest', '-')} | {stats.get('wakeup', {}).get('earliest', '-')} | {stats['waketime']['earliest']} |
| 最遅 | {stats['bedtime']['latest']} | {stats.get('fallasleep', {}).get('latest', '-')} | {stats.get('wakeup', {}).get('latest', '-')} | {stats['waketime']['latest']} |
| ばらつき | ±{stats['bedtime']['std_minutes']:.0f}分 | ±{stats.get('fallasleep', {}).get('std_minutes', 0):.0f}分 | ±{stats.get('wakeup', {}).get('std_minutes', 0):.0f}分 | ±{stats['waketime']['std_minutes']:.0f}分 |

{results['timing_table'].to_markdown(index=False)}
"""

    # サイクル分析セクションを追加
    if results.get('cycle_stats') and results.get('cycle_table') is not None:
        cs = results['cycle_stats']
        df_cycles = results['cycle_table']

        # 表示用のサイクルテーブルを作成
        cycle_display = df_cycles[['dateOfSleep', 'cycle_count', 'avg_cycle_length',
                                    'avg_rem_interval', 'deep_latency', 'first_rem_latency', 'deep_in_first_half']].copy()
        cycle_display.columns = ['日付', 'サイクル数', '平均長', 'REM間隔', '深い潜時', 'REM潜時', '前半深い(%)']
        cycle_display['日付'] = pd.to_datetime(cycle_display['日付']).dt.strftime('%m/%d')
        cycle_display = cycle_display.round(0)

        # REM開始時刻テーブル（夢想起用）
        rem_display = pd.DataFrame()
        rem_display['日付'] = pd.to_datetime(df_cycles['dateOfSleep']).dt.strftime('%m/%d')

        # REM1-4の開始時刻（入眠からの分数）
        for i in range(1, 5):
            col = f'rem{i}_onset'
            if col in df_cycles.columns:
                rem_display[f'REM{i}'] = df_cycles[col].apply(
                    lambda x: f'{int(x)}' if pd.notna(x) else '-'
                )

        # 就寝時刻（ライブラリで計算済み）
        if 'bedtime' in df_cycles.columns:
            rem_display['就寝'] = df_cycles['bedtime']

        # REM1-4の実時刻
        for i in range(1, 5):
            time_col = f'rem{i}_time'
            if time_col in df_cycles.columns:
                rem_display[f'REM{i}時'] = df_cycles[time_col].fillna('-')

        report += f"""
---

## 睡眠サイクル分析

> 睡眠は約90分のサイクルで構成。深い睡眠は前半、REMは後半に集中するのが理想。

### サイクル構造の質

| 指標 | 平均値 | 正常範囲 |
|------|--------|----------|
| サイクル数 | {cs['avg_cycle_count']:.1f}回 | 3-5回 |
| サイクル長 | {cs['avg_cycle_length']:.0f}分 | 90分前後 |
| REM間隔 | {cs['avg_rem_interval']:.0f}分 | 90分前後 |
| 深い睡眠潜時 | {cs['avg_deep_latency']:.0f}分 | 15-30分 |
| REM潜時 | {cs['avg_first_rem_latency']:.0f}分 | 60-90分 |
| 前半の深い睡眠 | {cs['avg_deep_in_first_half']:.0f}% | 70-80%以上 |

### 日別サイクル

{cycle_display.to_markdown(index=False)}

### REM開始時刻（夢想起用）

> 入眠からの経過時間。夢を覚えて起きたい場合、REM中に起床すると夢想起率が高い。

{rem_display.to_markdown(index=False)}
"""

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f'✓ レポート生成完了: {report_path}')
    return report_path


def run_analysis(output_dir, days=None, week=None, year=None):
    """
    睡眠データの分析を実行

    Parameters
    ----------
    output_dir : Path
        出力ディレクトリ
    days : int, optional
        分析対象の日数（Noneの場合は全データ）
    week : int, optional
        ISO週番号（指定時はその週のデータのみ）
    year : int, optional
        年（週番号指定時に使用、Noneの場合は現在の年）
    """
    print('='*60)
    print('日次睡眠レポート生成')
    print('='*60)
    print()

    # 画像出力ディレクトリ
    img_dir = output_dir / 'img'
    img_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # データ読み込み
    print(f'Loading: {MASTER_CSV}')
    df_master = pd.read_csv(MASTER_CSV)

    # 週番号でフィルタリング
    if week is not None:
        if year is None:
            year = datetime.now().year
        df_master['dateOfSleep'] = pd.to_datetime(df_master['dateOfSleep'])
        df_master['iso_week'] = df_master['dateOfSleep'].dt.isocalendar().week
        df_master['iso_year'] = df_master['dateOfSleep'].dt.isocalendar().year
        df_master = df_master[(df_master['iso_week'] == week) & (df_master['iso_year'] == year)]
        df_master['dateOfSleep'] = df_master['dateOfSleep'].dt.strftime('%Y-%m-%d')
        df_master = df_master.drop(columns=['iso_week', 'iso_year'])
        print(f'{year}年 第{week}週に絞り込み')
    elif days is not None:
        df_master = df_master.tail(days)
        print(f'直近{days}日分に絞り込み')

    print(f'データ件数: {len(df_master)}日分')

    # 統計計算
    print('計算中: 睡眠統計...')
    stats = sleep.calc_sleep_stats(df_master)
    results['stats'] = stats

    # 入眠潜時・起床後時間の計算（sleep_levelsが必要）
    sleep_timing = {}
    if LEVELS_CSV.exists():
        df_levels_for_timing = pd.read_csv(LEVELS_CSV)
        target_dates = df_master['dateOfSleep'].tolist()
        df_levels_for_timing = df_levels_for_timing[df_levels_for_timing['dateOfSleep'].isin(target_dates)]
        sleep_timing = sleep.calc_sleep_timing(df_levels_for_timing)

        # 平均を計算してstatsに追加
        if sleep_timing:
            avg_fall_asleep = sum(t['minutes_to_fall_asleep'] for t in sleep_timing.values()) / len(sleep_timing)
            avg_after_wake = sum(t['minutes_after_wakeup'] for t in sleep_timing.values()) / len(sleep_timing)
            stats['timing'] = {
                'avg_fall_asleep': avg_fall_asleep,
                'avg_after_wakeup': avg_after_wake,
            }

            # 入眠時刻・起床時刻の統計を計算
            fall_asleep_times = []
            wakeup_times = []
            for _, row in df_master.iterrows():
                date = row['dateOfSleep']
                timing = sleep_timing.get(date, {})
                fall_asleep_min = timing.get('minutes_to_fall_asleep', 0)
                after_wake_min = timing.get('minutes_after_wakeup', 0)
                if 'startTime' in row and fall_asleep_min > 0:
                    fall_asleep_times.append(pd.to_datetime(row['startTime']) + pd.Timedelta(minutes=fall_asleep_min))
                if 'endTime' in row and after_wake_min > 0:
                    wakeup_times.append(pd.to_datetime(row['endTime']) - pd.Timedelta(minutes=after_wake_min))

            # 入眠時刻統計
            if fall_asleep_times:
                stats['fallasleep'] = sleep.calc_time_stats(fall_asleep_times)

            # 起床時刻統計
            if wakeup_times:
                stats['wakeup'] = sleep.calc_time_stats(wakeup_times)

    # 日別サマリーテーブル作成（3分割：効率・ステージ・時刻）
    efficiency_data = []
    stages_data = []
    timing_data = []
    for _, row in df_master.iterrows():
        date = row['dateOfSleep'] if 'dateOfSleep' in df_master.columns else row.name
        sleep_hours = row['minutesAsleep'] / 60
        bed_hours = row['timeInBed'] / 60
        # 就寝・起床時刻を抽出
        bedtime = pd.to_datetime(row['startTime']).strftime('%H:%M') if 'startTime' in row else '-'
        waketime = pd.to_datetime(row['endTime']).strftime('%H:%M') if 'endTime' in row else '-'
        # 入眠潜時・起床後時間
        timing = sleep_timing.get(date, {})
        fall_asleep = timing.get('minutes_to_fall_asleep', 0)
        after_wake = timing.get('minutes_after_wakeup', 0)

        date_short = pd.to_datetime(date).strftime('%m/%d')

        # 睡眠効率テーブル（Time in Bedの詳細）
        efficiency_data.append({
            '日付': date_short,
            '効率': f"{row['efficiency']}%",
            '睡眠': f"{sleep_hours:.1f}h",
            'ベッド': f"{bed_hours:.1f}h",
            '入眠': f"{fall_asleep:.0f}分",
            '起後': f"{after_wake:.0f}分",
            '覚醒': f"{row['wakeMinutes']}分",
            '回数': f"{row['wakeCount']}回",
        })

        # 睡眠ステージテーブル（Total Sleep Timeの分析）
        stages_data.append({
            '日付': date_short,
            '睡眠': f"{sleep_hours:.1f}h",
            '深い': f"{row['deepMinutes']}分",
            '浅い': f"{row['lightMinutes']}分",
            'レム': f"{row['remMinutes']}分",
        })

        # 入眠時刻・起床時刻を計算
        if 'startTime' in row and fall_asleep > 0:
            fall_asleep_time = (pd.to_datetime(row['startTime']) + pd.Timedelta(minutes=fall_asleep)).strftime('%H:%M')
        else:
            fall_asleep_time = '-'
        if 'endTime' in row and after_wake > 0:
            wakeup_time = (pd.to_datetime(row['endTime']) - pd.Timedelta(minutes=after_wake)).strftime('%H:%M')
        else:
            wakeup_time = '-'

        # 就寝・起床テーブル（時刻のばらつき）
        timing_data.append({
            '日付': date_short,
            '就寝': bedtime,
            '入眠': fall_asleep_time,
            '起床': wakeup_time,
            '離床': waketime,
        })

    results['efficiency_table'] = pd.DataFrame(efficiency_data)
    results['stages_table'] = pd.DataFrame(stages_data)
    results['timing_table'] = pd.DataFrame(timing_data)

    # 個別グラフ生成
    print('プロット中: Time in Bed...')
    sleep.plot_time_in_bed_stacked(df_master, save_path=img_dir / 'time_in_bed.png')
    results['time_in_bed_img'] = 'time_in_bed.png'

    print('プロット中: 睡眠ステージ推移...')
    sleep.plot_sleep_stages_stacked(df_master, save_path=img_dir / 'sleep_stages_stacked.png')
    results['stages_stacked_img'] = 'sleep_stages_stacked.png'

    # タイムライン生成・入眠潜時計算
    if LEVELS_CSV.exists():
        print(f'Loading: {LEVELS_CSV}')
        df_levels = pd.read_csv(LEVELS_CSV)

        # 対象日付でフィルタ（days指定時も week指定時も適用）
        target_dates = df_master['dateOfSleep'].tolist() if 'dateOfSleep' in df_master.columns else df_master.index.tolist()
        df_levels = df_levels[df_levels['dateOfSleep'].isin(target_dates)]

        print('プロット中: 睡眠タイムライン...')
        timeline_img = 'sleep_timeline.png'
        sleep.plot_sleep_timeline(df_levels, save_path=img_dir / timeline_img)
        results['timeline_img'] = timeline_img

        # サイクル分析
        print('計算中: 睡眠サイクル...')
        df_cycles = sleep.cycles_to_dataframe(
            df_levels, df_master=df_master, max_cycle_length=180
        )
        results['cycle_table'] = df_cycles

        # サイクル統計
        cycle_stats = {
            'avg_cycle_length': df_cycles['avg_cycle_length'].mean(),
            'avg_rem_interval': df_cycles['avg_rem_interval'].mean(),
            'avg_deep_latency': df_cycles['deep_latency'].mean(),
            'avg_first_rem_latency': df_cycles['first_rem_latency'].mean(),
            'avg_deep_in_first_half': df_cycles['deep_in_first_half'].mean(),
            'avg_cycle_count': df_cycles['cycle_count'].mean(),
        }
        results['cycle_stats'] = cycle_stats
    else:
        print(f'警告: {LEVELS_CSV} が見つかりません。タイムラインをスキップします。')
        results['timeline_img'] = None
        results['cycle_table'] = None
        results['cycle_stats'] = None

    # レポート生成
    generate_markdown_report(output_dir, results)

    print()
    print('='*60)
    print('レポート生成完了!')
    print('='*60)
    print(f'レポート: {output_dir / "REPORT.md"}')
    print(f'画像: {img_dir}/')


def main():
    """メイン処理"""
    import argparse

    parser = argparse.ArgumentParser(
        description='日次睡眠レポートの生成'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=BASE_DIR / 'tmp/sleep_report',
        help='出力ディレクトリ（デフォルト: tmp/sleep_report）'
    )
    parser.add_argument(
        '--days',
        type=int,
        default=None,
        help='分析対象の日数（デフォルト: 全データ）'
    )
    parser.add_argument(
        '--week',
        type=str,
        default=None,
        help='ISO週番号（例: 48）または "current" で今週を指定'
    )
    parser.add_argument(
        '--year',
        type=int,
        default=None,
        help='年（--week指定時に使用、デフォルト: 今年）'
    )

    args = parser.parse_args()

    # 週番号の処理
    week = None
    year = args.year
    if args.week is not None:
        if args.week.lower() == 'current':
            iso_cal = datetime.now().isocalendar()
            week = iso_cal[1]
            if year is None:
                year = iso_cal[0]
            print(f'今週（第{week}週）を指定')
        else:
            week = int(args.week)
            if year is None:
                year = datetime.now().year

    # 出力ディレクトリの決定
    if week is not None:
        output_dir = BASE_DIR / f'reports/sleep/weekly/{year}-W{week:02d}'
    else:
        output_dir = args.output

    output_dir.mkdir(parents=True, exist_ok=True)

    run_analysis(output_dir, days=args.days, week=week, year=year)

    return 0


if __name__ == '__main__':
    exit(main())
