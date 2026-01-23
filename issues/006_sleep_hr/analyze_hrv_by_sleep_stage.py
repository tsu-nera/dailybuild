#!/usr/bin/env python
# coding: utf-8
"""
睡眠ステージ別HRV分析スクリプト

睡眠ステージ（deep, light, rem, wake）ごとのHRV指標を分析し、
入眠時/起床時/平均/最低/最高の基本統計を計算する。
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
OUTPUT_CSV = OUTPUT_DIR / 'hrv_by_sleep_stage.csv'
OUTPUT_REPORT = OUTPUT_DIR / 'HRV_SLEEP_STAGE_REPORT.md'
OUTPUT_IMG = OUTPUT_DIR / 'hrv_sleep_stage_analysis.png'


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
    print(f'  睡眠ステージ: {len(df_levels)}セグメント')
    print(f'  HRV Intraday: {len(df_hrv)}ポイント')

    return df_sleep, df_levels, df_hrv


def analyze_sleep_stage_hrv(df_sleep, df_levels, df_hrv, days=30):
    """
    睡眠ステージ別のHRV分析

    Returns:
        DataFrame: 日別・ステージ別のHRV統計
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

        # 基本統計（全体）
        overall_stats = {
            'date': date,
            'stage': 'overall',
            'avg_rmssd': sleep_hrv['rmssd'].mean(),
            'avg_hf': sleep_hrv['hf'].mean(),
            'avg_lf': sleep_hrv['lf'].mean(),
            'avg_lf_hf_ratio': sleep_hrv['lf_hf_ratio'].mean(),
            'min_rmssd': sleep_hrv['rmssd'].min(),
            'max_rmssd': sleep_hrv['rmssd'].max(),
            'data_points': len(sleep_hrv),
        }
        results.append(overall_stats)

        # 入眠時（最初の30分）
        onset_period = sleep_hrv[
            sleep_hrv['datetime'] <= sleep_start + pd.Timedelta(minutes=30)
        ]
        if len(onset_period) > 0:
            onset_stats = {
                'date': date,
                'stage': 'onset',
                'avg_rmssd': onset_period['rmssd'].mean(),
                'avg_hf': onset_period['hf'].mean(),
                'avg_lf': onset_period['lf'].mean(),
                'avg_lf_hf_ratio': onset_period['lf_hf_ratio'].mean(),
                'min_rmssd': onset_period['rmssd'].min(),
                'max_rmssd': onset_period['rmssd'].max(),
                'data_points': len(onset_period),
            }
            results.append(onset_stats)

        # 起床時（最後の30分）
        wakeup_period = sleep_hrv[
            sleep_hrv['datetime'] >= sleep_end - pd.Timedelta(minutes=30)
        ]
        if len(wakeup_period) > 0:
            wakeup_stats = {
                'date': date,
                'stage': 'wakeup',
                'avg_rmssd': wakeup_period['rmssd'].mean(),
                'avg_hf': wakeup_period['hf'].mean(),
                'avg_lf': wakeup_period['lf'].mean(),
                'avg_lf_hf_ratio': wakeup_period['lf_hf_ratio'].mean(),
                'min_rmssd': wakeup_period['rmssd'].min(),
                'max_rmssd': wakeup_period['rmssd'].max(),
                'data_points': len(wakeup_period),
            }
            results.append(wakeup_stats)

        # 該当日の睡眠ステージデータ
        date_levels = df_levels[df_levels['dateOfSleep'] == date].copy()

        # 各睡眠ステージごとに分析
        for stage in ['deep', 'light', 'rem', 'wake']:
            stage_segments = date_levels[date_levels['level'] == stage]

            if len(stage_segments) == 0:
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
                continue

            # ステージ全体のHRVデータを結合
            stage_hrv = pd.concat(stage_hrv_list, ignore_index=True)

            stage_stats = {
                'date': date,
                'stage': stage,
                'avg_rmssd': stage_hrv['rmssd'].mean(),
                'avg_hf': stage_hrv['hf'].mean(),
                'avg_lf': stage_hrv['lf'].mean(),
                'avg_lf_hf_ratio': stage_hrv['lf_hf_ratio'].mean(),
                'min_rmssd': stage_hrv['rmssd'].min(),
                'max_rmssd': stage_hrv['rmssd'].max(),
                'data_points': len(stage_hrv),
            }
            results.append(stage_stats)

    df_results = pd.DataFrame(results)
    return df_results


def plot_hrv_by_stage(df_results):
    """睡眠ステージ別HRVのグラフを作成"""
    print('\nグラフ作成中...')

    # ステージごとの平均値を計算（日付ごとのデータから）
    stage_order = ['onset', 'deep', 'light', 'rem', 'wake', 'wakeup', 'overall']
    stage_labels = {
        'onset': '入眠時\n(最初30分)',
        'deep': '深睡眠',
        'light': '浅睡眠',
        'rem': 'REM睡眠',
        'wake': '覚醒',
        'wakeup': '起床時\n(最後30分)',
        'overall': '全体平均'
    }

    stage_means = df_results.groupby('stage').agg({
        'avg_rmssd': 'mean',
        'avg_hf': 'mean',
        'avg_lf': 'mean',
        'avg_lf_hf_ratio': 'mean',
    }).reindex(stage_order)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('睡眠ステージ別HRV分析', fontsize=16, fontweight='bold')

    # 1. RMSSD
    ax = axes[0, 0]
    bars = ax.bar(range(len(stage_order)), stage_means['avg_rmssd'],
                   color=['#4CAF50', '#2196F3', '#03A9F4', '#9C27B0', '#F44336', '#FF9800', '#607D8B'])
    ax.set_xticks(range(len(stage_order)))
    ax.set_xticklabels([stage_labels[s] for s in stage_order], fontsize=9)
    ax.set_ylabel('RMSSD (ms)', fontsize=11)
    ax.set_title('RMSSD（副交感神経活動）', fontsize=12, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    # 2. HF成分
    ax = axes[0, 1]
    bars = ax.bar(range(len(stage_order)), stage_means['avg_hf'],
                   color=['#4CAF50', '#2196F3', '#03A9F4', '#9C27B0', '#F44336', '#FF9800', '#607D8B'])
    ax.set_xticks(range(len(stage_order)))
    ax.set_xticklabels([stage_labels[s] for s in stage_order], fontsize=9)
    ax.set_ylabel('HF (ms²)', fontsize=11)
    ax.set_title('HF成分（副交感神経）', fontsize=12, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    # 3. LF成分
    ax = axes[1, 0]
    bars = ax.bar(range(len(stage_order)), stage_means['avg_lf'],
                   color=['#4CAF50', '#2196F3', '#03A9F4', '#9C27B0', '#F44336', '#FF9800', '#607D8B'])
    ax.set_xticks(range(len(stage_order)))
    ax.set_xticklabels([stage_labels[s] for s in stage_order], fontsize=9)
    ax.set_ylabel('LF (ms²)', fontsize=11)
    ax.set_title('LF成分（混合）', fontsize=12, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)

    # 4. LF/HF比
    ax = axes[1, 1]
    bars = ax.bar(range(len(stage_order)), stage_means['avg_lf_hf_ratio'],
                   color=['#4CAF50', '#2196F3', '#03A9F4', '#9C27B0', '#F44336', '#FF9800', '#607D8B'])
    ax.set_xticks(range(len(stage_order)))
    ax.set_xticklabels([stage_labels[s] for s in stage_order], fontsize=9)
    ax.set_ylabel('LF/HF比', fontsize=11)
    ax.set_title('LF/HF比（自律神経バランス）', fontsize=12, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    ax.axhline(y=1.22, color='red', linestyle='--', linewidth=1, alpha=0.7, label='健康基準(1.22)')
    ax.legend(fontsize=9)

    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=150, bbox_inches='tight')
    print(f'  保存: {OUTPUT_IMG}')

    return stage_means


def generate_report(df_results, stage_means):
    """Markdownレポートを生成"""
    print('\nレポート生成中...')

    report = []
    report.append('# 睡眠ステージ別HRV分析レポート')
    report.append('')
    report.append(f'**分析日**: {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}')
    report.append(f'**データ期間**: {df_results["date"].min()} ~ {df_results["date"].max()}')
    report.append(f'**分析日数**: {df_results["date"].nunique()}日')
    report.append('')
    report.append('---')
    report.append('')

    # サマリー
    report.append('## サマリー')
    report.append('')
    report.append('### 睡眠ステージ別HRV平均値')
    report.append('')

    summary_table = []
    stage_order = ['onset', 'deep', 'light', 'rem', 'wake', 'wakeup', 'overall']
    stage_labels = {
        'onset': '入眠時（最初30分）',
        'deep': '深睡眠',
        'light': '浅睡眠',
        'rem': 'REM睡眠',
        'wake': '覚醒',
        'wakeup': '起床時（最後30分）',
        'overall': '全体平均'
    }

    for stage in stage_order:
        if stage not in stage_means.index:
            continue

        summary_table.append({
            'ステージ': stage_labels[stage],
            'RMSSD (ms)': f"{stage_means.loc[stage, 'avg_rmssd']:.1f}",
            'HF (ms²)': f"{stage_means.loc[stage, 'avg_hf']:.1f}",
            'LF (ms²)': f"{stage_means.loc[stage, 'avg_lf']:.1f}",
            'LF/HF比': f"{stage_means.loc[stage, 'avg_lf_hf_ratio']:.2f}",
        })

    df_summary = pd.DataFrame(summary_table)
    report.append(df_summary.to_markdown(index=False))
    report.append('')

    # グラフ
    report.append('![睡眠ステージ別HRV分析](hrv_sleep_stage_analysis.png)')
    report.append('')
    report.append('---')
    report.append('')

    # 研究的知見
    report.append('## 研究的知見')
    report.append('')
    report.append('### 健康な人の睡眠ステージ別LF/HF比（参考値）')
    report.append('')
    report.append('| ステージ | LF/HF比 | 状態 |')
    report.append('|---------|---------|------|')
    report.append('| 覚醒時 | 4.0 ± 1.4 | 交感神経活性 |')
    report.append('| 深睡眠（NREM） | **1.22 ± 0.33** | 副交感神経優位 |')
    report.append('| REM睡眠 | 3.0 ± 0.74 | 交感神経再活性化 |')
    report.append('')
    report.append('出典: [Heart Rate Variability During Specific Sleep Stages, Circulation](https://www.ahajournals.org/doi/10.1161/01.cir.91.7.1918)')
    report.append('')

    # 解釈
    report.append('## 分析結果の解釈')
    report.append('')

    deep_lf_hf = stage_means.loc['deep', 'avg_lf_hf_ratio']
    report.append('### 深睡眠の回復度')
    report.append('')
    report.append(f'- **深睡眠中の平均LF/HF比**: {deep_lf_hf:.2f}')

    if deep_lf_hf < 1.5:
        report.append('- ✅ **良好**: 研究基準（1.22）に近く、副交感神経が優位で回復が良好')
    elif deep_lf_hf < 2.5:
        report.append('- ⚠️ **やや高い**: 理想値よりやや高いが、許容範囲内')
    else:
        report.append('- ❌ **要注意**: 深睡眠中も交感神経活動が高く、回復が不十分な可能性')

    report.append('')

    # REM睡眠
    rem_lf_hf = stage_means.loc['rem', 'avg_lf_hf_ratio']
    report.append('### REM睡眠の自律神経バランス')
    report.append('')
    report.append(f'- **REM睡眠中の平均LF/HF比**: {rem_lf_hf:.2f}')
    report.append('- REM睡眠中は交感神経が再活性化するため、LF/HF比が上昇するのは正常')
    report.append('')

    # 入眠・起床
    onset_lf_hf = stage_means.loc['onset', 'avg_lf_hf_ratio']
    wakeup_lf_hf = stage_means.loc['wakeup', 'avg_lf_hf_ratio']
    report.append('### 入眠時と起床時の変化')
    report.append('')
    report.append(f'- **入眠時LF/HF比**: {onset_lf_hf:.2f}')
    report.append(f'- **起床時LF/HF比**: {wakeup_lf_hf:.2f}')

    if onset_lf_hf > wakeup_lf_hf:
        report.append('- 入眠時から起床時にかけてLF/HF比が低下し、リラクゼーションが進んだ')
    else:
        report.append('- 起床時にLF/HF比が上昇し、覚醒への準備が進んだ')

    report.append('')
    report.append('---')
    report.append('')

    # HRV指標の説明
    report.append('## HRV指標の説明')
    report.append('')
    report.append('### RMSSD（Root Mean Square of Successive Differences）')
    report.append('- 連続する心拍間隔の差の二乗平均平方根')
    report.append('- **副交感神経活動**の指標')
    report.append('- 高いほどリラックス状態、回復が良好')
    report.append('')
    report.append('### HF（High Frequency: 0.15-0.4Hz）')
    report.append('- 高周波成分')
    report.append('- **副交感神経活動**の直接的な指標')
    report.append('- 呼吸による心拍変動を反映')
    report.append('')
    report.append('### LF（Low Frequency: 0.04-0.15Hz）')
    report.append('- 低周波成分')
    report.append('- 交感神経と副交感神経の**混合指標**')
    report.append('- 血圧調節などを反映')
    report.append('')
    report.append('### LF/HF比')
    report.append('- 自律神経バランスの指標')
    report.append('- 低いほど副交感神経優位（リラックス）')
    report.append('- 高いほど交感神経優位（ストレス・活動）')
    report.append('')

    # レポート保存
    with open(OUTPUT_REPORT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))

    print(f'  保存: {OUTPUT_REPORT}')


def main():
    """メイン処理"""
    print('='*70)
    print('睡眠ステージ別HRV分析')
    print('='*70)
    print()

    # データ読み込み
    df_sleep, df_levels, df_hrv = load_data()

    # 分析実行
    df_results = analyze_sleep_stage_hrv(df_sleep, df_levels, df_hrv, days=30)

    # CSV保存
    df_results.to_csv(OUTPUT_CSV, index=False)
    print(f'\n結果を保存: {OUTPUT_CSV}')

    # グラフ作成
    stage_means = plot_hrv_by_stage(df_results)

    # レポート生成
    generate_report(df_results, stage_means)

    print()
    print('='*70)
    print('✅ 完了')
    print('='*70)
    print(f'レポート: {OUTPUT_REPORT}')
    print(f'データ: {OUTPUT_CSV}')
    print(f'グラフ: {OUTPUT_IMG}')


if __name__ == '__main__':
    main()
