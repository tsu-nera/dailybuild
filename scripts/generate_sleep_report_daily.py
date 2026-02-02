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

from lib.analytics import sleep
from lib.utils.report_args import add_common_report_args, parse_period_args, determine_output_dir

# データファイルパス
BASE_DIR = project_root
MASTER_CSV = BASE_DIR / 'data/fitbit/sleep.csv'
LEVELS_CSV = BASE_DIR / 'data/fitbit/sleep_levels.csv'
HRV_CSV = BASE_DIR / 'data/fitbit/hrv.csv'
HRV_INTRADAY_CSV = BASE_DIR / 'data/fitbit/hrv_intraday.csv'
HR_INTRADAY_CSV = BASE_DIR / 'data/fitbit/heart_rate_intraday.csv'
HR_DAILY_CSV = BASE_DIR / 'data/fitbit/heart_rate.csv'
SUN_TIMES_CSV = BASE_DIR / 'data/sun_times.csv'
NUTRITION_CSV = BASE_DIR / 'data/fitbit/nutrition.csv'


def prepare_sleep_report_data(results):
    """
    睡眠レポート用のコンテキストデータを準備

    Parameters
    ----------
    results : dict
        分析結果を格納した辞書

    Returns
    -------
    dict
        テンプレートコンテキスト
    """
    stats = results['stats']
    debt = stats['sleep_debt']
    debt_hours = debt['total_hours']

    # 睡眠負債テキスト（旧形式）
    if debt_hours >= 0:
        debt_text = f"+{debt_hours:.1f}時間（余裕あり）"
    else:
        debt_text = f"{debt_hours:.1f}時間（不足）"

    # 睡眠負債分析データ（新形式）
    sleep_debt_data = None
    if results.get('sleep_debt') is not None and results.get('sleep_need') is not None:
        debt_result = results['sleep_debt']
        need_result = results['sleep_need']

        # 睡眠負債履歴テーブルの作成
        debt_table = None
        if results.get('debt_history') is not None:
            table_data = sleep.format_debt_history_table(results['debt_history'])
            debt_table = table_data.to_markdown(index=False)

        # 睡眠リバウンド法の詳細データ
        rebound_method_data = None
        potential_debt_hours = 0.0
        if 'sleep_rebound' in need_result.estimates:
            rebound_est = need_result.estimates['sleep_rebound']
            if rebound_est.value_hours > 0:
                # リバウンド法の推定値から潜在的睡眠負債を計算
                potential_debt_hours = max(0, rebound_est.value_hours - need_result.habitual_hours)
                rebound_method_data = {
                    'value_hours': f'{rebound_est.value_hours:.1f}',
                    'sample_size': rebound_est.sample_size,
                    'percentile': f'{results.get("rebound_percentile", 4.0):.1f}',
                    'note': rebound_est.note
                }

        sleep_debt_data = {
            'habitual_hours': f'{need_result.habitual_hours:.1f}',
            'potential_debt_hours': f'{potential_debt_hours:.1f}',
            'rebound_method': rebound_method_data,
            'sleep_debt_hours': f'{debt_result.sleep_debt_hours:.1f}',
            'avg_sleep_hours': f'{debt_result.avg_sleep_hours:.1f}',
            'avg_total_sleep_hours': f'{results.get("avg_total_sleep_hours", 0):.1f}' if results.get('avg_total_sleep_hours') else None,
            'recovery_days': debt_result.recovery_days_estimate,
            'debt_table': debt_table,
            'trend_image': f'img/{results["debt_trend_img"]}' if results.get('debt_trend_img') else None
        }

    # サイクル分析データ（条件付き）
    cycles_data = None
    if results.get('cycle_stats') and results.get('cycle_table') is not None:
        cs = results['cycle_stats']
        df_cycles = results['cycle_table']

        # サイクルテーブル
        cycle_display = df_cycles[['dateOfSleep', 'cycle_count', 'avg_cycle_length',
                                    'avg_rem_interval', 'deep_latency', 'first_rem_latency', 'deep_in_first_half']].copy()
        cycle_display.columns = ['日付', 'サイクル数', '平均長', 'REM間隔', '深い潜時', 'REM潜時', '前半深い(%)']
        cycle_display['日付'] = pd.to_datetime(cycle_display['日付']).dt.strftime('%m/%d')
        cycle_display = cycle_display.round(0)

        # REM開始時刻テーブル
        rem_display = pd.DataFrame()
        rem_display['日付'] = pd.to_datetime(df_cycles['dateOfSleep']).dt.strftime('%m/%d')
        for i in range(1, 5):
            col = f'rem{i}_onset'
            if col in df_cycles.columns:
                rem_display[f'REM{i}'] = df_cycles[col].apply(
                    lambda x: f'{int(x)}' if pd.notna(x) else '-'
                )
        if 'bedtime' in df_cycles.columns:
            rem_display['就寝'] = df_cycles['bedtime']
        for i in range(1, 5):
            time_col = f'rem{i}_time'
            if time_col in df_cycles.columns:
                rem_display[f'REM{i}時'] = df_cycles[time_col].fillna('-')

        cycles_data = {
            'avg_cycle_count': f"{cs['avg_cycle_count']:.1f}",
            'avg_cycle_length': f"{cs['avg_cycle_length']:.0f}",
            'avg_rem_interval': f"{cs['avg_rem_interval']:.0f}",
            'avg_deep_latency': f"{cs['avg_deep_latency']:.0f}",
            'avg_first_rem_latency': f"{cs['avg_first_rem_latency']:.0f}",
            'avg_deep_in_first_half': f"{cs['avg_deep_in_first_half']:.0f}",
            'cycle_table': cycle_display.to_markdown(index=False),
            'rem_table': rem_display.to_markdown(index=False)
        }

    # 栄養データ（条件付き）
    nutrition_data = None
    if results.get('nutrition_table') is not None:
        nutr_table = results['nutrition_table']
        nutrition_data = {
            'table': nutr_table.to_dict('records'),
        }

    # 心拍数データ（条件付き）
    heart_rate_data = None
    if results.get('heart_rate_stats') is not None:
        hr_stats = results['heart_rate_stats']
        baseline = results.get('hr_baseline')
        advanced_hr = results.get('advanced_hr_metrics')

        # HRV daily dataを読み込む（心拍数テーブルに追加）
        df_hrv_daily = None
        if results.get('df_hrv_daily') is not None:
            df_hrv_daily = results['df_hrv_daily']

        # テーブルデータ作成
        hr_table = []
        for date in sorted(hr_stats.keys()):
            stats_day = hr_stats[date]
            advanced_day = advanced_hr.get(date, {}) if advanced_hr else {}

            # HRVデータを取得
            daily_rmssd = '-'
            deep_rmssd = '-'
            if df_hrv_daily is not None:
                hrv_row = df_hrv_daily[df_hrv_daily['date'] == date]
                if len(hrv_row) > 0:
                    daily_rmssd = f"{hrv_row['daily_rmssd'].iloc[0]:.1f}"
                    deep_rmssd = f"{hrv_row['deep_rmssd'].iloc[0]:.1f}"

            # 最低HR: 入眠からの経過分を表示
            time_to_min_hr_display = '-'
            if advanced_day and advanced_day.get('time_to_min_hr') is not None:
                time_to_min_hr_display = f"{advanced_day['time_to_min_hr']:.0f}"

            hr_table.append({
                'date': pd.to_datetime(date).strftime('%m/%d'),
                'avg_hr': f"{stats_day['avg_hr']:.0f}",
                'min_hr': stats_day['min_hr'],
                'max_hr': stats_day['max_hr'],
                'daily_resting_hr': stats_day.get('daily_resting_hr', '-'),
                'above_baseline_pct': f"{stats_day.get('above_baseline_pct', 0):.0f}",
                'below_baseline_pct': f"{stats_day.get('below_baseline_pct', 0):.0f}",
                'dip_rate': f"{advanced_day.get('dip_rate_avg', 0):.1f}" if advanced_day else '-',
                'time_to_min_hr': time_to_min_hr_display,
                'min_hr_time': advanced_day.get('min_hr_time', '-') if advanced_day else '-',
                'daily_rmssd': daily_rmssd,
                'deep_rmssd': deep_rmssd,
            })

        # 高度な指標の平均を計算
        avg_dip_rate = None
        avg_time_to_min_hr = None
        if advanced_hr:
            dip_rates = [m['dip_rate_avg'] for m in advanced_hr.values()]
            time_to_mins = [m['time_to_min_hr'] for m in advanced_hr.values()]
            if dip_rates:
                avg_dip_rate = sum(dip_rates) / len(dip_rates)
            if time_to_mins:
                avg_time_to_min_hr = sum(time_to_mins) / len(time_to_mins)

        heart_rate_data = {
            'table': hr_table,
            'baseline': baseline,
            'avg_dip_rate': f"{avg_dip_rate:.1f}" if avg_dip_rate is not None else None,
            'avg_time_to_min_hr': f"{avg_time_to_min_hr:.0f}" if avg_time_to_min_hr is not None else None,
        }

    # timing_tableに最低HR時刻を追加
    timing_table = results['timing_table'].copy()
    if results.get('advanced_hr_metrics') is not None:
        advanced_hr = results['advanced_hr_metrics']

        # 日付をキーにして最低HR時刻を取得
        min_hr_times = []
        for idx, row in timing_table.iterrows():
            date_str = row['日付']
            # mm/dd形式からyyyy-mm-dd形式に変換
            year = stats['period']['end'].split('-')[0]
            month, day = date_str.split('/')
            full_date = f"{year}-{month}-{day}"

            min_hr_time = advanced_hr.get(full_date, {}).get('min_hr_time', '-')
            min_hr_times.append(min_hr_time)

        # 最低HRカラムを日出の前に挿入
        timing_table.insert(timing_table.columns.get_loc('日出'), '最低HR', min_hr_times)

        # 最低HR時刻の統計を計算
        valid_times = [t for t in min_hr_times if t != '-']
        min_hr_mean = '-'
        min_hr_earliest = '-'
        min_hr_latest = '-'
        min_hr_std = '-'

        if valid_times:
            # HH:MM形式を分単位に変換
            times_in_minutes = []
            for t in valid_times:
                h, m = map(int, t.split(':'))
                times_in_minutes.append(h * 60 + m)

            mean_minutes = sum(times_in_minutes) / len(times_in_minutes)
            min_hr_mean = f"{int(mean_minutes // 60):02d}:{int(mean_minutes % 60):02d}"

            earliest_minutes = min(times_in_minutes)
            min_hr_earliest = f"{int(earliest_minutes // 60):02d}:{int(earliest_minutes % 60):02d}"

            latest_minutes = max(times_in_minutes)
            min_hr_latest = f"{int(latest_minutes // 60):02d}:{int(latest_minutes % 60):02d}"

            # 標準偏差を計算
            if len(times_in_minutes) > 1:
                variance = sum((t - mean_minutes) ** 2 for t in times_in_minutes) / len(times_in_minutes)
                std_minutes = variance ** 0.5
                min_hr_std = f"{std_minutes:.0f}"
    else:
        min_hr_mean = '-'
        min_hr_earliest = '-'
        min_hr_latest = '-'
        min_hr_std = '-'

    context = {
        'report_title': '日次睡眠レポート',
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'period': {
            'start': stats['period']['start'],
            'end': stats['period']['end'],
            'days': stats['period']['days']
        },
        'summary': {
            'time_in_bed_hours': f"{stats['weekly_total']['time_in_bed_hours']:.1f}",
            'hours_asleep': f"{stats['weekly_total']['hours_asleep']:.1f}",
            'avg_sleep_hours': f"{stats['duration']['mean_hours']:.1f}"
        },
        'sleep_debt': sleep_debt_data,
        'efficiency': {
            'mean': f"{stats['efficiency']['mean']:.1f}",
            'min': stats['efficiency']['min'],
            'max': stats['efficiency']['max'],
            'avg_fall_asleep': f"{stats.get('timing', {}).get('avg_fall_asleep', 0):.0f}",
            'avg_after_wakeup': f"{stats.get('timing', {}).get('avg_after_wakeup', 0):.0f}",
            'image': f"img/{results['time_in_bed_img']}",
            'table': results['efficiency_table'].to_markdown(index=False)
        },
        'stages': {
            'mean_hours': f"{stats['duration']['mean_hours']:.1f}",
            'mean_minutes': f"{stats['duration']['mean_minutes']:.0f}",
            'min_hours': f"{stats['duration']['min_hours']:.1f}",
            'max_hours': f"{stats['duration']['max_hours']:.1f}",
            'std_hours': f"{stats['duration']['std_hours']:.1f}",
            'deep_minutes': f"{stats['stages']['deep_minutes']:.0f}",
            'deep_pct': f"{stats['stages'].get('deep_pct', 0):.1f}",
            'deep_count': f"{stats['stages']['deep_count']:.0f}",
            'light_minutes': f"{stats['stages']['light_minutes']:.0f}",
            'light_pct': f"{stats['stages'].get('light_pct', 0):.1f}",
            'light_count': f"{stats['stages']['light_count']:.0f}",
            'rem_minutes': f"{stats['stages']['rem_minutes']:.0f}",
            'rem_pct': f"{stats['stages'].get('rem_pct', 0):.1f}",
            'rem_count': f"{stats['stages']['rem_count']:.0f}",
            'wake_minutes': f"{stats['stages']['wake_minutes']:.0f}",
            'stacked_image': f"img/{results['stages_stacked_img']}",
            'table': results['stages_table'].to_markdown(index=False),
            'timeline_image': f"img/{results['timeline_img']}"
        },
        'timing': {
            'bedtime_mean': stats['bedtime']['mean'],
            'bedtime_earliest': stats['bedtime']['earliest'],
            'bedtime_latest': stats['bedtime']['latest'],
            'bedtime_std': f"{stats['bedtime']['std_minutes']:.0f}",
            'fallasleep_mean': stats.get('fallasleep', {}).get('mean', '-'),
            'fallasleep_earliest': stats.get('fallasleep', {}).get('earliest', '-'),
            'fallasleep_latest': stats.get('fallasleep', {}).get('latest', '-'),
            'fallasleep_std': f"{stats.get('fallasleep', {}).get('std_minutes', 0):.0f}",
            'wakeup_mean': stats.get('wakeup', {}).get('mean', '-'),
            'wakeup_earliest': stats.get('wakeup', {}).get('earliest', '-'),
            'wakeup_latest': stats.get('wakeup', {}).get('latest', '-'),
            'wakeup_std': f"{stats.get('wakeup', {}).get('std_minutes', 0):.0f}",
            'waketime_mean': stats['waketime']['mean'],
            'waketime_earliest': stats['waketime']['earliest'],
            'waketime_latest': stats['waketime']['latest'],
            'waketime_std': f"{stats['waketime']['std_minutes']:.0f}",
            'min_hr_mean': min_hr_mean,
            'min_hr_earliest': min_hr_earliest,
            'min_hr_latest': min_hr_latest,
            'min_hr_std': min_hr_std,
            'sunrise_mean': timing_table['日出'].iloc[0] if len(timing_table) > 0 and '日出' in timing_table.columns else '-',
            'sunset_mean': timing_table['日入'].iloc[0] if len(timing_table) > 0 and '日入' in timing_table.columns else '-',
            'table': timing_table.to_markdown(index=False)
        },
        'nutrition': nutrition_data,
        'heart_rate': heart_rate_data,
        'cycles': cycles_data
    }

    return context


def generate_markdown_report(output_dir, results):
    """
    マークダウンレポートを生成（Jinja2テンプレート版）

    Parameters
    ----------
    output_dir : Path
        出力ディレクトリ
    results : dict
        分析結果を格納した辞書
    """
    from lib.templates.renderer import SleepReportRenderer

    # コンテキストデータ準備
    context = prepare_sleep_report_data(results)

    # テンプレートレンダリング
    renderer = SleepReportRenderer()
    report_content = renderer.render_daily_report(context)

    # レポート出力
    report_path = output_dir / 'REPORT.md'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)

    print(f'✓ レポート生成完了: {report_path}')
    return report_path


def run_analysis(output_dir, days=None, week=None, month=None, year=None):
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
    month : int, optional
        月番号（指定時はその月のデータのみ）
    year : int, optional
        年（週番号/月番号指定時に使用、Noneの場合は現在の年）
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
    df_all_sleep = pd.read_csv(MASTER_CSV)

    # 日出・日入データ読み込み
    df_sun = pd.read_csv(SUN_TIMES_CSV) if SUN_TIMES_CSV.exists() else pd.DataFrame()

    # 主睡眠のみを抽出（ほとんどの分析で使用）
    df_main_sleep_full = df_all_sleep[df_all_sleep['isMainSleep'] == True].copy()

    # 共通フィルタリング関数を使用
    from lib.utils.report_args import filter_dataframe_by_period
    df_master = filter_dataframe_by_period(
        df_main_sleep_full.copy(), 'dateOfSleep', week, month, year, days, is_index=False
    )

    # 全睡眠（主睡眠+昼寝）もフィルタリング（睡眠負債計算用）
    df_all_sleep_filtered = filter_dataframe_by_period(
        df_all_sleep.copy(), 'dateOfSleep', week, month, year, days, is_index=False
    )

    # フィルタリング結果を表示
    if week is not None:
        print(f'{year}年 第{week}週に絞り込み')
    elif month is not None:
        print(f'{year}年 {month}月に絞り込み')
    elif days is not None:
        print(f'直近{days}日分に絞り込み')

    # 日付を文字列に戻す（後続処理との互換性のため）
    df_master['dateOfSleep'] = pd.to_datetime(df_master['dateOfSleep']).dt.strftime('%Y-%m-%d')

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

        # 日出・日入をCSVから取得
        if not df_sun.empty and date in df_sun['date'].values:
            sun_row = df_sun[df_sun['date'] == date].iloc[0]
            sunrise_time = sun_row['sunrise']
            sunset_time = sun_row['sunset']
        else:
            sunrise_time = '-'
            sunset_time = '-'

        # 就寝・起床テーブル（時刻のばらつき）
        timing_data.append({
            '日付': date_short,
            '就寝': bedtime,
            '入眠': fall_asleep_time,
            '起床': wakeup_time,
            '離床': waketime,
            '日出': sunrise_time,
            '日入': sunset_time,
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

        # 主睡眠のlogIdでフィルタ（昼寝を除外）
        if 'logId' in df_master.columns:
            target_log_ids = df_master['logId'].tolist()
            df_levels = df_levels[df_levels['logId'].isin(target_log_ids)]
        else:
            # logIdがない場合は日付でフィルタ（後方互換性）
            target_dates = df_master['dateOfSleep'].tolist() if 'dateOfSleep' in df_master.columns else df_master.index.tolist()
            df_levels = df_levels[df_levels['dateOfSleep'].isin(target_dates)]

        # タイムライン画像は最新7日分のみ表示
        df_levels_timeline = df_levels.copy()
        if len(df_master) > 7:
            # 最新7日分の日付を取得
            latest_dates = df_master.sort_values('dateOfSleep', ascending=False).head(7)['dateOfSleep'].tolist()
            df_levels_timeline = df_levels[df_levels['dateOfSleep'].isin(latest_dates)]
            print(f'タイムライン表示: 最新7日分に制限（全体: {len(df_master)}日）')

        print('プロット中: 睡眠タイムライン...')
        timeline_img = 'sleep_timeline.png'
        sleep.plot_sleep_timeline(df_levels_timeline, save_path=img_dir / timeline_img)
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

    # 心拍数データの読み込みと分析
    if HR_INTRADAY_CSV.exists() and HR_DAILY_CSV.exists():
        print(f'Loading: {HR_INTRADAY_CSV}')
        df_hr_intraday = pd.read_csv(HR_INTRADAY_CSV)

        print(f'Loading: {HR_DAILY_CSV}')
        df_hr_daily = pd.read_csv(HR_DAILY_CSV)

        print('計算中: 睡眠中の心拍数...')
        hr_stats = sleep.calc_sleep_heart_rate_stats(
            df_master, df_hr_intraday, df_hr_daily, baseline_days=7
        )
        results['heart_rate_stats'] = hr_stats

        # ベースライン計算
        hr_baseline = sleep.calc_resting_hr_baseline(df_hr_daily, lookback_days=7)
        results['hr_baseline'] = hr_baseline

        # 高度な心拍数指標を計算
        print('計算中: 高度な心拍数指標（ディップ率、最低HR到達時間）...')
        advanced_hr = sleep.calc_advanced_hr_metrics(df_master, df_hr_intraday)
        results['advanced_hr_metrics'] = advanced_hr
    else:
        print(f'警告: 心拍数データが見つかりません。心拍数分析をスキップします。')
        results['heart_rate_stats'] = None
        results['hr_baseline'] = None
        results['advanced_hr_metrics'] = None

    # 栄養データの読み込みと分析
    if NUTRITION_CSV.exists():
        print(f'Loading: {NUTRITION_CSV}')
        df_nutrition = pd.read_csv(NUTRITION_CSV)
        df_nutrition['date'] = pd.to_datetime(df_nutrition['date'])

        # カロリーが0より大きい日のみ（記録がある日）
        df_nutrition = df_nutrition[df_nutrition['calories'] > 0].copy()

        # GLスコアを計算
        from lib.analytics import nutrition as nutr
        df_nutrition = nutr.add_glycemic_scores(df_nutrition)

        # 栄養データと睡眠心拍数データを結合（栄養日の翌日の睡眠データ）
        print('計算中: 栄養データと睡眠心拍数の結合...')
        nutrition_table = []
        for _, nutr_row in df_nutrition.iterrows():
            nutrition_date = nutr_row['date']
            sleep_date = nutrition_date + pd.Timedelta(days=1)

            # 対応する睡眠データを検索
            sleep_date_str = sleep_date.strftime('%Y-%m-%d')
            sleep_rows = df_master[df_master['dateOfSleep'] == sleep_date_str]

            # フィルタリング期間内の睡眠データのみを対象
            if len(sleep_rows) > 0:
                sleep_row = sleep_rows.iloc[0]
                # 心拍数データを取得
                hr_stat = hr_stats.get(sleep_date_str, {}) if hr_stats else {}
                adv_hr = advanced_hr.get(sleep_date_str, {}) if advanced_hr else {}

                nutrition_table.append({
                    'date': pd.to_datetime(nutrition_date).strftime('%m/%d'),
                    'carbs': f"{nutr_row['carbs']:.0f}",
                    'fiber': f"{nutr_row['fiber']:.0f}",
                    'predicted_gl': f"{nutr_row['predicted_gl']:.1f}",
                    'gl_category': nutr_row['gl_category'],
                    'deep_minutes': int(sleep_row['deepMinutes']),
                    'efficiency': int(sleep_row['efficiency']),
                    'min_hr': hr_stat.get('min_hr', '-'),
                    'min_hr_time': adv_hr.get('min_hr_time', '-'),
                    'dip_rate': f"{adv_hr.get('dip_rate_avg', 0):.1f}" if adv_hr.get('dip_rate_avg') else '-',
                })

        if nutrition_table:
            results['nutrition_table'] = pd.DataFrame(nutrition_table)
        else:
            results['nutrition_table'] = None
    else:
        print(f'警告: {NUTRITION_CSV} が見つかりません。栄養分析をスキップします。')
        results['nutrition_table'] = None

    # 睡眠負債分析（全データを使用）
    df_hrv = None
    if HRV_CSV.exists():
        print(f'Loading: {HRV_CSV}')
        df_hrv = pd.read_csv(HRV_CSV)
        df_hrv['date'] = pd.to_datetime(df_hrv['date'])
        # HRVデータをresultsに保存（心拍数テーブルで使用）
        results['df_hrv_daily'] = df_hrv
    else:
        results['df_hrv_daily'] = None

    print('計算中: 最適睡眠時間推定...')
    rebound_percentile = 4.0  # RISE式推奨値
    estimator = sleep.SleepNeedEstimator(
        sleep_data=df_main_sleep_full.copy(),  # 主睡眠のみで推定
        hrv_data=df_hrv,
        lookback_days=365,  # RISEアプリは約1年分のデータを使用（Issue #004参照）
        rebound_top_percentile=rebound_percentile
    )
    sleep_need_result = estimator.estimate()
    results['sleep_need'] = sleep_need_result
    results['rebound_percentile'] = rebound_percentile

    # 睡眠リバウンド法の推定値を使用して睡眠負債を計算
    sleep_need_for_debt = sleep_need_result.recommended_hours
    if 'sleep_rebound' in sleep_need_result.estimates:
        rebound_est = sleep_need_result.estimates['sleep_rebound']
        if rebound_est.value_hours > 0:
            sleep_need_for_debt = rebound_est.value_hours
            print(f'  → 睡眠リバウンド法推定値: {rebound_est.value_hours:.1f}h を睡眠負債計算に使用')

    # 日別に全睡眠時間（主睡眠+昼寝）を集計
    print('計算中: 睡眠負債...')
    df_daily_total_sleep = df_all_sleep.groupby('dateOfSleep', as_index=False).agg({
        'minutesAsleep': 'sum',  # 同じ日の全睡眠時間を合計
        'timeInBed': 'sum'
    })

    calculator = sleep.SleepDebtCalculator(
        sleep_data=df_daily_total_sleep,  # 日別総睡眠時間（昼寝込み）
        sleep_need_hours=sleep_need_for_debt,
        window_days=14,
        min_data_points=5
    )

    # フィルタリング期間の睡眠負債履歴を取得
    try:
        # フィルタリング期間の開始日と終了日
        filtered_dates = pd.to_datetime(df_master['dateOfSleep'])
        start_date = filtered_dates.min()
        latest_date = filtered_dates.max()

        # 最新日時点の睡眠負債（RISE方式）
        sleep_debt_result = calculator.calculate(end_date=latest_date, weight_method='rise')
        results['sleep_debt'] = sleep_debt_result

        # フィルタリング期間の履歴を取得してグラフ用データを作成（RISE方式）
        debt_history = calculator.get_history(start_date, latest_date, weight_method='rise')
        results['debt_history'] = debt_history

        # フィルタリング期間の日別総睡眠時間（昼寝込み）の平均を計算
        df_filtered_daily = df_all_sleep_filtered.groupby('dateOfSleep', as_index=False).agg({
            'minutesAsleep': 'sum'
        })
        avg_total_sleep_hours = df_filtered_daily['minutesAsleep'].mean() / 60
        results['avg_total_sleep_hours'] = avg_total_sleep_hours
    except ValueError as e:
        print(f'警告: 睡眠負債の計算をスキップ - {e}')
        results['sleep_debt'] = None
        results['debt_history'] = None
        results['avg_total_sleep_hours'] = None

    # 睡眠負債トレンドグラフ
    if results.get('debt_history') is not None:
        print('プロット中: 睡眠負債トレンド...')
        sleep.plot_sleep_debt_trend(
            results['debt_history'],
            save_path=img_dir / 'sleep_debt_trend.png'
        )
        results['debt_trend_img'] = 'sleep_debt_trend.png'
    else:
        results['debt_trend_img'] = None

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

    parser = argparse.ArgumentParser(description='日次睡眠レポートの生成')
    add_common_report_args(parser, default_output=BASE_DIR / 'tmp/sleep_report', default_days=None)
    args = parser.parse_args()

    # Parse period arguments
    week, month, year = parse_period_args(args)

    # 出力ディレクトリの決定
    output_dir = determine_output_dir(BASE_DIR, 'sleep', args.output, week, month, year)
    output_dir.mkdir(parents=True, exist_ok=True)

    run_analysis(output_dir, days=args.days, week=week, month=month, year=year)

    return 0


if __name__ == '__main__':
    exit(main())
