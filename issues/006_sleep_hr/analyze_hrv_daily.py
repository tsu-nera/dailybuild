#!/usr/bin/env python
# coding: utf-8
"""
HRV日別統計分析スクリプト

各日の睡眠ステージ別HRV指標を日別テーブルで表示
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")

# プロジェクトルート
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / 'src'))

# データファイルパス
DATA_DIR = project_root / 'data/fitbit'
SLEEP_CSV = DATA_DIR / 'sleep.csv'
LEVELS_CSV = DATA_DIR / 'sleep_levels.csv'
HRV_INTRADAY_CSV = DATA_DIR / 'hrv_intraday.csv'

# 出力先
OUTPUT_DIR = Path(__file__).parent
OUTPUT_CSV = OUTPUT_DIR / 'hrv_daily_stats.csv'
OUTPUT_REPORT = OUTPUT_DIR / 'HRV_DAILY_REPORT.md'
OUTPUT_IMG = OUTPUT_DIR / 'hrv_daily_trends.png'


def load_data():
    """データを読み込む"""
    print('データ読み込み中...')

    df_sleep = pd.read_csv(SLEEP_CSV)
    df_levels = pd.read_csv(LEVELS_CSV)
    df_hrv = pd.read_csv(HRV_INTRADAY_CSV)

    # 日付型に変換
    df_hrv['datetime'] = pd.to_datetime(df_hrv['datetime'])
    df_levels['dateTime'] = pd.to_datetime(df_levels['dateTime'])

    # sleep_levelsのendTimeを計算
    df_levels['startTime'] = df_levels['dateTime']
    df_levels['endTime'] = df_levels['startTime'] + pd.to_timedelta(df_levels['seconds'], unit='s')

    # LF/HF比を計算
    df_hrv['lf_hf_ratio'] = df_hrv['lf'] / df_hrv['hf']

    print(f'  睡眠記録: {len(df_sleep)}日')
    print(f'  HRV Intraday: {len(df_hrv)}ポイント')

    return df_sleep, df_levels, df_hrv


def analyze_daily_hrv(df_sleep, df_levels, df_hrv, days=30):
    """
    日別HRV統計を計算

    Returns:
        DataFrame: 日別統計
    """
    print(f'\n最近{days}日分を分析中...')

    # 最近のデータに絞る
    end_date = pd.to_datetime(df_sleep['dateOfSleep'].max())
    start_date = end_date - pd.Timedelta(days=days-1)

    df_sleep_filtered = df_sleep[
        (pd.to_datetime(df_sleep['dateOfSleep']) >= start_date) &
        (pd.to_datetime(df_sleep['dateOfSleep']) <= end_date) &
        (df_sleep['isMainSleep'] == True)
    ].copy()

    results = []

    for _, sleep_row in df_sleep_filtered.iterrows():
        date = sleep_row['dateOfSleep']
        sleep_start = pd.to_datetime(sleep_row['startTime'])
        sleep_end = pd.to_datetime(sleep_row['endTime'])

        print(f'  分析中: {date}')

        # 睡眠時間帯のHRVデータ
        sleep_hrv = df_hrv[
            (df_hrv['datetime'] >= sleep_start) &
            (df_hrv['datetime'] <= sleep_end)
        ].copy()

        if len(sleep_hrv) == 0:
            continue

        # 全体統計
        overall_rmssd = sleep_hrv['rmssd'].mean()
        overall_hf = sleep_hrv['hf'].mean()
        overall_lf = sleep_hrv['lf'].mean()
        overall_lf_hf = sleep_hrv['lf_hf_ratio'].mean()

        # 入眠時（最初の30分）
        onset_period = sleep_hrv[
            sleep_hrv['datetime'] <= sleep_start + pd.Timedelta(minutes=30)
        ]
        onset_lf_hf = onset_period['lf_hf_ratio'].mean() if len(onset_period) > 0 else None

        # 起床時（最後の30分）
        wakeup_period = sleep_hrv[
            sleep_hrv['datetime'] >= sleep_end - pd.Timedelta(minutes=30)
        ]
        wakeup_lf_hf = wakeup_period['lf_hf_ratio'].mean() if len(wakeup_period) > 0 else None

        # 最高RMSSD到達時間（副交感神経活動が最も活発になる時間）
        max_rmssd_idx = sleep_hrv['rmssd'].idxmax()
        max_rmssd_value = sleep_hrv.loc[max_rmssd_idx, 'rmssd']
        max_rmssd_time = sleep_hrv.loc[max_rmssd_idx, 'datetime']
        time_to_max_rmssd = (max_rmssd_time - sleep_start).total_seconds() / 60  # 分単位

        # 該当日の睡眠ステージデータ
        date_levels = df_levels[df_levels['dateOfSleep'] == date].copy()

        # 各睡眠ステージのHRV
        stage_stats = {}
        for stage in ['deep', 'light', 'rem', 'wake']:
            stage_segments = date_levels[date_levels['level'] == stage]

            if len(stage_segments) == 0:
                stage_stats[stage] = {
                    'rmssd': None,
                    'lf_hf_ratio': None,
                    'hf': None,
                }
                continue

            # 各ステージのHRVデータを収集
            stage_hrv_list = []
            for _, segment in stage_segments.iterrows():
                segment_hrv = sleep_hrv[
                    (sleep_hrv['datetime'] >= segment['startTime']) &
                    (sleep_hrv['datetime'] < segment['endTime'])
                ]
                if len(segment_hrv) > 0:
                    stage_hrv_list.append(segment_hrv)

            if len(stage_hrv_list) == 0:
                stage_stats[stage] = {
                    'rmssd': None,
                    'lf_hf_ratio': None,
                    'hf': None,
                }
                continue

            # ステージ全体のHRVデータを結合
            stage_hrv = pd.concat(stage_hrv_list, ignore_index=True)

            stage_stats[stage] = {
                'rmssd': stage_hrv['rmssd'].mean(),
                'lf_hf_ratio': stage_hrv['lf_hf_ratio'].mean(),
                'hf': stage_hrv['hf'].mean(),
            }

        results.append({
            'date': date,
            # 全体
            'overall_rmssd': overall_rmssd,
            'overall_hf': overall_hf,
            'overall_lf': overall_lf,
            'overall_lf_hf': overall_lf_hf,
            # 入眠・起床
            'onset_lf_hf': onset_lf_hf,
            'wakeup_lf_hf': wakeup_lf_hf,
            # 最高RMSSD到達時間
            'max_rmssd_value': max_rmssd_value,
            'max_rmssd_time': max_rmssd_time.strftime('%H:%M'),
            'time_to_max_rmssd': time_to_max_rmssd,
            # 深睡眠
            'deep_rmssd': stage_stats['deep']['rmssd'],
            'deep_lf_hf': stage_stats['deep']['lf_hf_ratio'],
            'deep_hf': stage_stats['deep']['hf'],
            # 浅睡眠
            'light_rmssd': stage_stats['light']['rmssd'],
            'light_lf_hf': stage_stats['light']['lf_hf_ratio'],
            # REM睡眠
            'rem_rmssd': stage_stats['rem']['rmssd'],
            'rem_lf_hf': stage_stats['rem']['lf_hf_ratio'],
            # 覚醒
            'wake_lf_hf': stage_stats['wake']['lf_hf_ratio'],
        })

    df_results = pd.DataFrame(results)
    df_results['date'] = pd.to_datetime(df_results['date'])
    return df_results


def plot_daily_trends(df_results):
    """日別トレンドのグラフを作成"""
    print('\nグラフ作成中...')

    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    fig.suptitle('HRV日別トレンド', fontsize=16, fontweight='bold')

    dates = df_results['date']
    x = range(len(dates))
    date_labels = [d.strftime('%m/%d') for d in dates]

    # 1. 睡眠ステージ別LF/HF比
    ax = axes[0]
    ax.plot(x, df_results['deep_lf_hf'], marker='o', label='Deep sleep', linewidth=2, color='#2196F3')
    ax.plot(x, df_results['light_lf_hf'], marker='s', label='Light sleep', linewidth=2, color='#03A9F4')
    ax.plot(x, df_results['rem_lf_hf'], marker='^', label='REM sleep', linewidth=2, color='#9C27B0')
    ax.axhline(y=1.22, color='red', linestyle='--', linewidth=1.5, alpha=0.7, label='Healthy baseline (1.22)')
    ax.set_ylabel('LF/HF Ratio', fontsize=11)
    ax.set_title('Sleep Stage LF/HF Ratio (Lower is better for deep sleep)', fontsize=12, fontweight='bold')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(alpha=0.3)
    ax.set_xticks(x)
    ax.set_xticklabels(date_labels, rotation=45, fontsize=9)

    # 2. RMSSD（副交感神経活動）
    ax = axes[1]
    ax.plot(x, df_results['overall_rmssd'], marker='o', label='Overall', linewidth=2, color='#607D8B')
    ax.plot(x, df_results['deep_rmssd'], marker='o', label='Deep sleep', linewidth=2, color='#2196F3')
    ax.plot(x, df_results['light_rmssd'], marker='s', label='Light sleep', linewidth=2, color='#03A9F4')
    ax.plot(x, df_results['rem_rmssd'], marker='^', label='REM sleep', linewidth=2, color='#9C27B0')
    ax.set_ylabel('RMSSD (ms)', fontsize=11)
    ax.set_title('RMSSD - Parasympathetic Activity (Higher is better)', fontsize=12, fontweight='bold')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(alpha=0.3)
    ax.set_xticks(x)
    ax.set_xticklabels(date_labels, rotation=45, fontsize=9)

    # 3. 入眠・起床時のLF/HF比
    ax = axes[2]
    ax.plot(x, df_results['onset_lf_hf'], marker='o', label='Sleep onset (first 30min)', linewidth=2, color='#4CAF50')
    ax.plot(x, df_results['wakeup_lf_hf'], marker='s', label='Wake-up (last 30min)', linewidth=2, color='#FF9800')
    ax.set_ylabel('LF/HF Ratio', fontsize=11)
    ax.set_title('Sleep Onset & Wake-up LF/HF Ratio', fontsize=12, fontweight='bold')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(alpha=0.3)
    ax.set_xticks(x)
    ax.set_xticklabels(date_labels, rotation=45, fontsize=9)

    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=150, bbox_inches='tight')
    print(f'  保存: {OUTPUT_IMG}')


def generate_report(df_results):
    """Markdownレポートを生成"""
    print('\nレポート生成中...')

    report = []
    report.append('# HRV日別統計レポート')
    report.append('')
    report.append(f'**分析日**: {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}')
    report.append(f'**データ期間**: {df_results["date"].min().strftime("%Y-%m-%d")} ~ {df_results["date"].max().strftime("%Y-%m-%d")}')
    report.append(f'**分析日数**: {len(df_results)}日')
    report.append('')
    report.append('---')
    report.append('')

    # サマリー統計
    report.append('## サマリー統計')
    report.append('')
    report.append('### 深睡眠LF/HF比（回復の質の指標）')
    report.append('')
    deep_lf_hf = df_results['deep_lf_hf'].dropna()
    report.append(f'- **平均**: {deep_lf_hf.mean():.2f}')
    report.append(f'- **最小（最良）**: {deep_lf_hf.min():.2f}')
    report.append(f'- **最大（最悪）**: {deep_lf_hf.max():.2f}')
    report.append(f'- **健康基準**: 1.22 ± 0.33')
    report.append('')

    good_days = (deep_lf_hf < 2.0).sum()
    total_days = len(deep_lf_hf)
    report.append(f'- **良好な日数（<2.0）**: {good_days}/{total_days}日 ({good_days/total_days*100:.1f}%)')
    report.append('')

    # 最高RMSSD到達時間統計
    report.append('### 最高RMSSD到達時間（副交感神経活性化速度）')
    report.append('')
    time_to_max = df_results['time_to_max_rmssd']
    report.append(f'- **平均**: {time_to_max.mean():.0f}分')
    report.append(f'- **最速**: {time_to_max.min():.0f}分')
    report.append(f'- **最遅**: {time_to_max.max():.0f}分')
    report.append(f'- **健康範囲**: 60-180分')
    report.append('')

    good_speed = ((time_to_max >= 60) & (time_to_max <= 180)).sum()
    report.append(f'- **健康範囲内の日数**: {good_speed}/{len(time_to_max)}日 ({good_speed/len(time_to_max)*100:.1f}%)')
    report.append('')

    # 日別テーブル
    report.append('## 日別データ')
    report.append('')
    report.append('### 睡眠ステージ別LF/HF比')
    report.append('')

    table_data = []
    for _, row in df_results.iterrows():
        date_str = row['date'].strftime('%m/%d')

        # 評価
        deep_eval = ''
        if pd.notna(row['deep_lf_hf']):
            if row['deep_lf_hf'] < 2.0:
                deep_eval = '✅'
            elif row['deep_lf_hf'] < 3.0:
                deep_eval = '⚠️'
            else:
                deep_eval = '❌'

        table_data.append({
            '日付': date_str,
            '深睡眠': f"{row['deep_lf_hf']:.2f}" if pd.notna(row['deep_lf_hf']) else '-',
            '浅睡眠': f"{row['light_lf_hf']:.2f}" if pd.notna(row['light_lf_hf']) else '-',
            'REM': f"{row['rem_lf_hf']:.2f}" if pd.notna(row['rem_lf_hf']) else '-',
            '全体': f"{row['overall_lf_hf']:.2f}",
            '評価': deep_eval,
        })

    df_table = pd.DataFrame(table_data)
    report.append(df_table.to_markdown(index=False))
    report.append('')
    report.append('**評価基準（深睡眠）**: ✅ <2.0（良好）, ⚠️ 2.0-3.0（やや高い）, ❌ >3.0（要注意）')
    report.append('')

    # RMSSD テーブル
    report.append('### 睡眠ステージ別RMSSD（副交感神経活動）')
    report.append('')

    rmssd_table = []
    for _, row in df_results.iterrows():
        date_str = row['date'].strftime('%m/%d')

        rmssd_table.append({
            '日付': date_str,
            '深睡眠': f"{row['deep_rmssd']:.1f}" if pd.notna(row['deep_rmssd']) else '-',
            '浅睡眠': f"{row['light_rmssd']:.1f}" if pd.notna(row['light_rmssd']) else '-',
            'REM': f"{row['rem_rmssd']:.1f}" if pd.notna(row['rem_rmssd']) else '-',
            '全体': f"{row['overall_rmssd']:.1f}",
        })

    df_rmssd = pd.DataFrame(rmssd_table)
    report.append(df_rmssd.to_markdown(index=False))
    report.append('')
    report.append('**単位**: ms（ミリ秒） - 高いほど副交感神経が活発（リラックス）')
    report.append('')

    # 最高RMSSD到達時間テーブル
    report.append('### 最高RMSSD到達時間（副交感神経活性化速度）')
    report.append('')

    max_rmssd_table = []
    for _, row in df_results.iterrows():
        date_str = row['date'].strftime('%m/%d')

        max_rmssd_table.append({
            '日付': date_str,
            '最高RMSSD': f"{row['max_rmssd_value']:.1f}ms",
            '到達時刻': row['max_rmssd_time'],
            '入眠からの時間': f"{row['time_to_max_rmssd']:.0f}分",
        })

    df_max_rmssd = pd.DataFrame(max_rmssd_table)
    report.append(df_max_rmssd.to_markdown(index=False))
    report.append('')
    report.append('**健康範囲**: 60-180分程度（心拍数の最低HR到達時間と同様）')
    report.append('')

    # 統計
    time_to_max = df_results['time_to_max_rmssd']
    report.append(f'- **平均到達時間**: {time_to_max.mean():.0f}分')
    report.append(f'- **最速**: {time_to_max.min():.0f}分')
    report.append(f'- **最遅**: {time_to_max.max():.0f}分')
    report.append('')

    good_speed = ((time_to_max >= 60) & (time_to_max <= 180)).sum()
    total = len(time_to_max)
    report.append(f'- **健康範囲内の日数（60-180分）**: {good_speed}/{total}日 ({good_speed/total*100:.1f}%)')
    report.append('')

    # グラフ
    report.append('## トレンドグラフ')
    report.append('')
    report.append('![HRV日別トレンド](hrv_daily_trends.png)')
    report.append('')
    report.append('---')
    report.append('')

    # 解釈
    report.append('## 指標の解釈')
    report.append('')
    report.append('### LF/HF比（自律神経バランス）')
    report.append('- **低いほど良い**（副交感神経優位、リラックス状態）')
    report.append('- **深睡眠の健康基準**: 1.22 ± 0.33')
    report.append('- **REM睡眠**: 3.0 ± 0.74（交感神経が再活性化するため高いのは正常）')
    report.append('')
    report.append('### RMSSD（副交感神経活動）')
    report.append('- **高いほど良い**（回復が良好）')
    report.append('- アスリート: 35-107ms、一般人: 19-48ms')
    report.append('')
    report.append('### 最高RMSSD到達時間')
    report.append('- 入眠後、副交感神経活動が最も活発になるまでの時間')
    report.append('- **健康範囲**: 60-180分程度')
    report.append('- 短すぎる（<60分）: 入眠前からすでにリラックス状態')
    report.append('- 長すぎる（>180分）: 副交感神経の活性化が遅い、深いリラクゼーションに時間がかかる')
    report.append('')

    # レポート保存
    with open(OUTPUT_REPORT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))

    print(f'  保存: {OUTPUT_REPORT}')


def main():
    """メイン処理"""
    print('='*70)
    print('HRV日別統計分析')
    print('='*70)
    print()

    # データ読み込み
    df_sleep, df_levels, df_hrv = load_data()

    # 分析実行
    df_results = analyze_daily_hrv(df_sleep, df_levels, df_hrv, days=30)

    # CSV保存
    df_results.to_csv(OUTPUT_CSV, index=False)
    print(f'\n結果を保存: {OUTPUT_CSV}')

    # グラフ作成
    plot_daily_trends(df_results)

    # レポート生成
    generate_report(df_results)

    print()
    print('='*70)
    print('✅ 完了')
    print('='*70)
    print(f'レポート: {OUTPUT_REPORT}')
    print(f'データ: {OUTPUT_CSV}')
    print(f'グラフ: {OUTPUT_IMG}')


if __name__ == '__main__':
    main()
