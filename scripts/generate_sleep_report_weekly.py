#!/usr/bin/env python
# coding: utf-8
"""
週次睡眠レポート生成スクリプト

lib/sleep_analysis.py の関数を使用してマークダウンレポートを生成します。

Usage:
    python generate_sleep_report.py [--output <REPORT_DIR>] [--days <N>]
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

from lib import sleep_analysis

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

    report = f"""# 週次睡眠レポート

- **生成日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **対象期間**: {stats['period']['start']} ～ {stats['period']['end']}
- **データ日数**: {stats['period']['days']}日分

---

## 今週のサマリー

| 指標 | 値 |
|------|-----|
| ベッド時間合計 | {stats['weekly_total']['time_in_bed_hours']:.1f}時間 |
| 睡眠時間合計 | {stats['weekly_total']['hours_asleep']:.1f}時間 |
| 睡眠負債 | **{debt_text}** |
| 目標達成 | {debt['days_met_goal']}/{stats['period']['days']}日（{debt['recommended_hours']:.0f}時間以上） |

> 睡眠負債は推奨{debt['recommended_hours']:.0f}時間との差の累積です。

---

## 睡眠効率

| 指標 | 値 |
|------|-----|
| 平均効率 | **{stats['efficiency']['mean']:.1f}%** |
| 最低 | {stats['efficiency']['min']}% |
| 最高 | {stats['efficiency']['max']}% |

> 85%以上が良好な睡眠効率とされています。

![睡眠効率](img/{results['efficiency_img']})

---

## 就寝・起床時刻

| 指標 | 就寝 | 起床 |
|------|------|------|
| 平均 | **{stats['bedtime']['mean']}** | **{stats['waketime']['mean']}** |
| 最早 | {stats['bedtime']['earliest']} | {stats['waketime']['earliest']} |
| 最遅 | {stats['bedtime']['latest']} | {stats['waketime']['latest']} |
| ばらつき | ±{stats['bedtime']['std_minutes']:.0f}分 | ±{stats['waketime']['std_minutes']:.0f}分 |
| 入眠/起床後 | {stats.get('timing', {}).get('avg_fall_asleep', 0):.0f}分 | {stats.get('timing', {}).get('avg_after_wakeup', 0):.0f}分 |

> 入眠潜時は就寝から眠りにつくまで、起床後は目覚めてからベッドを出るまでの時間。

---

## 睡眠時間・ステージ推移

![睡眠時間・ステージ推移](img/{results['stages_stacked_img']})

- 緑の破線: 推奨睡眠時間（7時間）
- 赤の破線: 今週の平均睡眠時間

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

---

## 日別サマリー

{results['daily_table'].to_markdown(index=False)}

---

## 睡眠ステージ タイムライン

各日の睡眠ステージの推移を可視化しています。

![睡眠タイムライン](img/{results['timeline_img']})

**凡例**:
- 🟠 オレンジ: 覚醒（Wake）
- 🟣 紫: レム睡眠（REM）
- 🔵 水色: 浅い睡眠（Light）
- 🔷 濃紺: 深い睡眠（Deep）
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
    print('週次睡眠レポート生成')
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
    stats = sleep_analysis.calc_sleep_stats(df_master)
    results['stats'] = stats

    # 入眠潜時・起床後時間の計算（sleep_levelsが必要）
    sleep_timing = {}
    if LEVELS_CSV.exists():
        df_levels_for_timing = pd.read_csv(LEVELS_CSV)
        target_dates = df_master['dateOfSleep'].tolist()
        df_levels_for_timing = df_levels_for_timing[df_levels_for_timing['dateOfSleep'].isin(target_dates)]
        sleep_timing = sleep_analysis.calc_sleep_timing(df_levels_for_timing)

        # 平均を計算してstatsに追加
        if sleep_timing:
            avg_fall_asleep = sum(t['minutes_to_fall_asleep'] for t in sleep_timing.values()) / len(sleep_timing)
            avg_after_wake = sum(t['minutes_after_wakeup'] for t in sleep_timing.values()) / len(sleep_timing)
            stats['timing'] = {
                'avg_fall_asleep': avg_fall_asleep,
                'avg_after_wakeup': avg_after_wake,
            }

    # 日別サマリーテーブル作成
    daily_data = []
    for _, row in df_master.iterrows():
        date = row['dateOfSleep'] if 'dateOfSleep' in df_master.columns else row.name
        hours = row['minutesAsleep'] / 60
        # 就寝・起床時刻を抽出
        bedtime = pd.to_datetime(row['startTime']).strftime('%H:%M') if 'startTime' in row else '-'
        waketime = pd.to_datetime(row['endTime']).strftime('%H:%M') if 'endTime' in row else '-'
        # 入眠潜時・起床後時間
        timing = sleep_timing.get(date, {})
        fall_asleep = timing.get('minutes_to_fall_asleep', 0)
        after_wake = timing.get('minutes_after_wakeup', 0)
        daily_data.append({
            '日付': str(date)[-5:],
            '就寝': bedtime,
            '入眠': f"{fall_asleep:.0f}分",
            '起床': waketime,
            '起後': f"{after_wake:.0f}分",
            '睡眠': f"{hours:.1f}h",
            '効率': f"{row['efficiency']}%",
            '深い': f"{row['deepMinutes']}分",
            '浅い': f"{row['lightMinutes']}分",
            'レム': f"{row['remMinutes']}分",
            '覚醒': f"{row['wakeMinutes']}分/{row['wakeCount']}回",
        })
    results['daily_table'] = pd.DataFrame(daily_data)

    # 個別グラフ生成
    print('プロット中: 睡眠効率...')
    sleep_analysis.plot_sleep_efficiency(df_master, save_path=img_dir / 'sleep_efficiency.png')
    results['efficiency_img'] = 'sleep_efficiency.png'

    print('プロット中: 睡眠ステージ推移...')
    sleep_analysis.plot_sleep_stages_stacked(df_master, save_path=img_dir / 'sleep_stages_stacked.png')
    results['stages_stacked_img'] = 'sleep_stages_stacked.png'

    # タイムライン生成・入眠潜時計算
    if LEVELS_CSV.exists():
        print(f'Loading: {LEVELS_CSV}')
        df_levels = pd.read_csv(LEVELS_CSV)

        if days is not None:
            # 対象日付でフィルタ
            target_dates = df_master['dateOfSleep'].tolist() if 'dateOfSleep' in df_master.columns else df_master.index.tolist()
            df_levels = df_levels[df_levels['dateOfSleep'].isin(target_dates)]

        print('プロット中: 睡眠タイムライン...')
        timeline_img = 'sleep_timeline.png'
        sleep_analysis.plot_sleep_timeline(df_levels, save_path=img_dir / timeline_img)
        results['timeline_img'] = timeline_img
    else:
        print(f'警告: {LEVELS_CSV} が見つかりません。タイムラインをスキップします。')
        results['timeline_img'] = None

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
        description='週次睡眠レポートの生成'
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
