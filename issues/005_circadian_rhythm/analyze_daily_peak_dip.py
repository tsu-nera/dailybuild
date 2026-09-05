#!/usr/bin/env python3
"""
日毎のサーカディアンリズム - Peak/Dip分析

目的:
1. 各日のpeak/dip時刻を検出
2. 起床時刻からの経過時間を計算
3. 絶対時刻 vs 相対時刻の安定性を比較
4. Riseアプリの予測方法との整合性を検証
"""

import sys
import os
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.lib.analytics.circadian import (
    format_time,
    load_activity_periods,
    exclude_activity_periods,
    prepare_hourly_data_with_interval,
)

# 既存スクリプトから関数をインポート
sys.path.insert(0, str(Path(__file__).parent))
from analyze_circadian_peak_dip import (
    detect_peaks_dips_detailed,
    categorize_peaks_dips_detailed,
)


def calculate_time_since_wake(peak_time: float, wake_time: datetime) -> float:
    """
    起床時刻からの経過時間を計算

    Parameters
    ----------
    peak_time : float
        peak/dipの時刻（0-24の実数、例: 15.05）
    wake_time : datetime
        起床時刻

    Returns
    -------
    float
        起床からの経過時間（時間単位）
    """
    wake_hour = wake_time.hour + wake_time.minute / 60.0
    elapsed = peak_time - wake_hour

    # 負の場合は24を足す（前日起床のケース）
    if elapsed < 0:
        elapsed += 24

    return elapsed


def analyze_daily_peaks_dips(
    hr_df: pd.DataFrame,
    sleep_df: pd.DataFrame,
    activity_periods: list,
    date_range: pd.DatetimeIndex
) -> pd.DataFrame:
    """
    日毎のpeak/dip分析を実行

    Parameters
    ----------
    hr_df : pd.DataFrame
        心拍数Intradayデータ（datetimeインデックス）
    sleep_df : pd.DataFrame
        睡眠データ（'dateOfSleep', 'startTime', 'endTime', 'durationHours'列）
    activity_periods : list
        運動時間帯のリスト
    date_range : pd.DatetimeIndex
        分析対象の日付範囲

    Returns
    -------
    pd.DataFrame
        日毎の分析結果
    """
    daily_results = []

    for date in date_range:
        print(f"\n📅 {date.strftime('%Y-%m-%d')} を分析中...")

        # その日の心拍数データを抽出
        hr_day = hr_df[hr_df.index.date == date.date()]

        if len(hr_day) == 0:
            print(f"   ⚠️ データなし - スキップ")
            continue

        # その日の睡眠データから起床時刻を取得
        sleep_day = sleep_df[sleep_df['dateOfSleep'] == date.strftime('%Y-%m-%d')]

        if len(sleep_day) == 0:
            print(f"   ⚠️ 睡眠データなし - スキップ")
            continue

        # 最後の睡眠の終了時刻を起床時刻とする
        wake_time = pd.to_datetime(sleep_day.iloc[-1]['endTime'])
        sleep_duration = sleep_day.iloc[-1]['duration'] / 60.0  # 分を時間に変換

        # その日の運動時間を除外
        activity_periods_day = [
            (start, end) for start, end in activity_periods
            if start.date() == date.date()
        ]

        if activity_periods_day:
            hr_day = exclude_activity_periods(hr_day, activity_periods_day)

        # データが少なすぎる場合はスキップ
        if len(hr_day) < 100:
            print(f"   ⚠️ データ不足 ({len(hr_day)}件) - スキップ")
            continue

        # 10分ごとの平均を計算（その日だけ）
        hr_day_copy = hr_day.copy()
        hr_day_copy['time_decimal'] = (
            hr_day_copy.index.hour + hr_day_copy.index.minute / 60.0
        )

        # 10分ごとに集約
        hr_day_copy['time_bin'] = (
            hr_day_copy['time_decimal'] * 6
        ).round() / 6

        hr_10min_day = hr_day_copy.groupby('time_bin')['heart_rate'].mean().reset_index()
        hr_10min_day.columns = ['time_decimal', 'heart_rate']
        hr_10min_day = hr_10min_day.sort_values('time_decimal').reset_index(drop=True)

        # peak/dip検出
        results_day = detect_peaks_dips_detailed(
            hr_10min_day['time_decimal'].values,
            hr_10min_day['heart_rate'].values,
            prominence=1.5  # 日毎なので閾値を少し下げる
        )

        # カテゴリ分類
        categories_day = categorize_peaks_dips_detailed(
            results_day['peaks'],
            results_day['dips']
        )

        # 結果を記録
        result = {
            'date': date,
            'wake_time': wake_time,
            'sleep_duration': sleep_duration,
        }

        # 各カテゴリのpeak/dipを記録
        for cat_name, cat_value in categories_day.items():
            if cat_value:
                peak_time, peak_hr = cat_value
                result[f'{cat_name}_time'] = peak_time
                result[f'{cat_name}_hr'] = peak_hr
                result[f'{cat_name}_since_wake'] = calculate_time_since_wake(
                    peak_time, wake_time
                )
                print(f"   {cat_name}: {format_time(peak_time)} "
                      f"(起床から {result[f'{cat_name}_since_wake']:.1f}h後)")
            else:
                result[f'{cat_name}_time'] = None
                result[f'{cat_name}_hr'] = None
                result[f'{cat_name}_since_wake'] = None

        daily_results.append(result)

    return pd.DataFrame(daily_results)


def calculate_statistics(df_daily: pd.DataFrame) -> dict:
    """
    統計分析を実行

    Parameters
    ----------
    df_daily : pd.DataFrame
        日毎の分析結果

    Returns
    -------
    dict
        統計結果
    """
    stats = {}

    categories = ['night_dip', 'morning_peak', 'afternoon_dip',
                  'afternoon_peak', 'evening_dip', 'evening_peak']

    for cat in categories:
        time_col = f'{cat}_time'
        since_wake_col = f'{cat}_since_wake'
        hr_col = f'{cat}_hr'

        if time_col in df_daily.columns:
            # 絶対時刻の統計
            time_data = df_daily[time_col].dropna()
            if len(time_data) > 0:
                stats[f'{cat}_abs_mean'] = time_data.mean()
                stats[f'{cat}_abs_std'] = time_data.std()
                stats[f'{cat}_abs_count'] = len(time_data)

            # 起床からの経過時間の統計
            since_wake_data = df_daily[since_wake_col].dropna()
            if len(since_wake_data) > 0:
                stats[f'{cat}_rel_mean'] = since_wake_data.mean()
                stats[f'{cat}_rel_std'] = since_wake_data.std()

            # 心拍数の統計
            hr_data = df_daily[hr_col].dropna()
            if len(hr_data) > 0:
                stats[f'{cat}_hr_mean'] = hr_data.mean()
                stats[f'{cat}_hr_std'] = hr_data.std()

    # 起床時刻の統計
    wake_times = df_daily['wake_time'].dropna()
    if len(wake_times) > 0:
        wake_time_decimal = wake_times.dt.hour + wake_times.dt.minute / 60.0
        stats['wake_time_mean'] = wake_time_decimal.mean()
        stats['wake_time_std'] = wake_time_decimal.std()

    # 相関分析
    # 起床時刻 vs 各peak/dipの時刻
    if 'wake_time' in df_daily.columns:
        df_corr = df_daily.copy()
        df_corr['wake_time_decimal'] = (
            df_corr['wake_time'].dt.hour + df_corr['wake_time'].dt.minute / 60.0
        )

        for cat in categories:
            time_col = f'{cat}_time'
            if time_col in df_corr.columns:
                corr_data = df_corr[['wake_time_decimal', time_col]].dropna()
                if len(corr_data) > 1:
                    correlation = corr_data.corr().iloc[0, 1]
                    stats[f'{cat}_wake_corr'] = correlation

    # 睡眠時間 vs peak/dip強度
    for cat in categories:
        hr_col = f'{cat}_hr'
        if hr_col in df_daily.columns:
            corr_data = df_daily[['sleep_duration', hr_col]].dropna()
            if len(corr_data) > 1:
                correlation = corr_data.corr().iloc[0, 1]
                stats[f'{cat}_sleep_corr'] = correlation

    return stats


def visualize_daily_analysis(df_daily: pd.DataFrame, output_file: str):
    """
    日毎分析の可視化（4つのプロット）

    Parameters
    ----------
    df_daily : pd.DataFrame
        日毎の分析結果
    output_file : str
        出力ファイルパス
    """
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))

    categories = {
        'morning_peak': ('Morning peak', 'gold', '^'),
        'afternoon_dip': ('Afternoon dip', 'purple', 'v'),
        'afternoon_peak': ('Afternoon peak', 'orange', '^'),
        'evening_dip': ('Evening dip', 'brown', 'v'),
        'evening_peak': ('Evening peak', 'red', '^'),
    }

    # 1. 日毎のpeak/dip時刻（絶対時刻）
    ax1 = axes[0, 0]
    for cat, (label, color, marker) in categories.items():
        time_col = f'{cat}_time'
        if time_col in df_daily.columns:
            data = df_daily[['date', time_col]].dropna()
            if len(data) > 0:
                ax1.scatter(data['date'], data[time_col],
                           label=label, color=color, marker=marker,
                           s=100, alpha=0.7, edgecolors='black', linewidths=1)

    ax1.set_ylabel('Time of day (hour)', fontsize=13, fontweight='bold')
    ax1.set_title('Daily Peak/Dip Times (Absolute Time)', fontsize=14, fontweight='bold')
    ax1.legend(loc='best', fontsize=10)
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.set_ylim(0, 24)
    ax1.set_yticks(np.arange(0, 25, 2))

    # 2. 起床からの経過時間
    ax2 = axes[0, 1]
    for cat, (label, color, marker) in categories.items():
        since_wake_col = f'{cat}_since_wake'
        if since_wake_col in df_daily.columns:
            data = df_daily[['date', since_wake_col]].dropna()
            if len(data) > 0:
                ax2.scatter(data['date'], data[since_wake_col],
                           label=label, color=color, marker=marker,
                           s=100, alpha=0.7, edgecolors='black', linewidths=1)

    ax2.set_ylabel('Hours since wake', fontsize=13, fontweight='bold')
    ax2.set_title('Daily Peak/Dip Times (Relative to Wake Time)', fontsize=14, fontweight='bold')
    ax2.legend(loc='best', fontsize=10)
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.set_ylim(0, 18)

    # 3. 起床時刻 vs morning peak時刻の相関
    ax3 = axes[1, 0]
    if 'morning_peak_time' in df_daily.columns:
        df_plot = df_daily.copy()
        df_plot['wake_time_decimal'] = (
            df_plot['wake_time'].dt.hour + df_plot['wake_time'].dt.minute / 60.0
        )
        corr_data = df_plot[['wake_time_decimal', 'morning_peak_time']].dropna()

        if len(corr_data) > 1:
            ax3.scatter(corr_data['wake_time_decimal'],
                       corr_data['morning_peak_time'],
                       color='gold', s=120, alpha=0.7,
                       edgecolors='black', linewidths=1.5)

            # 相関係数を計算
            correlation = corr_data.corr().iloc[0, 1]

            # 回帰線
            z = np.polyfit(corr_data['wake_time_decimal'],
                          corr_data['morning_peak_time'], 1)
            p = np.poly1d(z)
            x_line = np.linspace(corr_data['wake_time_decimal'].min(),
                                corr_data['wake_time_decimal'].max(), 100)
            ax3.plot(x_line, p(x_line), "r--", alpha=0.8, linewidth=2,
                    label=f'r = {correlation:.3f}')

            ax3.set_xlabel('Wake time (hour)', fontsize=13, fontweight='bold')
            ax3.set_ylabel('Morning peak time (hour)', fontsize=13, fontweight='bold')
            ax3.set_title('Wake Time vs Morning Peak Time', fontsize=14, fontweight='bold')
            ax3.legend(fontsize=11)
            ax3.grid(True, alpha=0.3, linestyle='--')

    # 4. 睡眠時間 vs morning peak強度
    ax4 = axes[1, 1]
    if 'morning_peak_hr' in df_daily.columns:
        corr_data = df_daily[['sleep_duration', 'morning_peak_hr']].dropna()

        if len(corr_data) > 1:
            ax4.scatter(corr_data['sleep_duration'],
                       corr_data['morning_peak_hr'],
                       color='gold', s=120, alpha=0.7,
                       edgecolors='black', linewidths=1.5)

            # 相関係数を計算
            correlation = corr_data.corr().iloc[0, 1]

            # 回帰線
            z = np.polyfit(corr_data['sleep_duration'],
                          corr_data['morning_peak_hr'], 1)
            p = np.poly1d(z)
            x_line = np.linspace(corr_data['sleep_duration'].min(),
                                corr_data['sleep_duration'].max(), 100)
            ax4.plot(x_line, p(x_line), "r--", alpha=0.8, linewidth=2,
                    label=f'r = {correlation:.3f}')

            ax4.set_xlabel('Sleep duration (hours)', fontsize=13, fontweight='bold')
            ax4.set_ylabel('Morning peak HR (bpm)', fontsize=13, fontweight='bold')
            ax4.set_title('Sleep Duration vs Morning Peak HR', fontsize=14, fontweight='bold')
            ax4.legend(fontsize=11)
            ax4.grid(True, alpha=0.3, linestyle='--')

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    print(f"✅ 可視化を保存: {output_file}")


def generate_report(df_daily: pd.DataFrame, stats: dict) -> str:
    """
    分析レポートを生成

    Parameters
    ----------
    df_daily : pd.DataFrame
        日毎の分析結果
    stats : dict
        統計結果

    Returns
    -------
    str
        Markdownレポート
    """
    report = """# サーカディアンリズム - 日毎Peak/Dip分析

**分析日**: 2026-01-07
**目的**: 起床時刻からの経過時間 vs 絶対時刻の安定性を比較

---

## 📊 分析結果の可視化

![日毎分析](daily_peak_dip_analysis.png)

**グラフの見方**:
- **左上**: 各peak/dipの絶対時刻（何時に現れるか）
- **右上**: 起床からの経過時間（起床から何時間後に現れるか）
- **左下**: 起床時刻と朝peakの相関
- **右下**: 睡眠時間と朝peak強度の相関

---

## 📈 統計分析結果

### 朝のピーク (Morning Peak)

"""

    # Morning peak統計
    if 'morning_peak_abs_mean' in stats:
        abs_mean = stats['morning_peak_abs_mean']
        abs_std = stats['morning_peak_abs_std']
        rel_mean = stats.get('morning_peak_rel_mean', np.nan)
        rel_std = stats.get('morning_peak_rel_std', np.nan)
        count = stats['morning_peak_abs_count']

        report += f"""
- **絶対時刻**: {format_time(abs_mean)} ± {abs_std*60:.0f}分 ({count}日中{count}日検出)
- **起床からの経過時間**: {rel_mean:.1f}h ± {rel_std:.1f}h
- **安定性**: 絶対時刻の標準偏差 {abs_std*60:.0f}分 vs 経過時間の標準偏差 {rel_std*60:.0f}分
"""

        # 相関分析
        if 'morning_peak_wake_corr' in stats:
            corr = stats['morning_peak_wake_corr']
            report += f"- **起床時刻との相関**: r = {corr:.3f}\n"

            if corr > 0.7:
                report += "  - ✅ **強い正の相関** → 起床時刻に依存（Riseアプリ型）\n"
            elif corr < 0.3:
                report += "  - ✅ **相関なし** → 絶対時刻で固定（体内時計型）\n"
            else:
                report += "  - ✅ **中程度の相関** → 混合パターン\n"

    # 他のpeak/dip統計
    for cat_name, cat_label in [
        ('afternoon_dip', '昼のディップ (Afternoon Dip)'),
        ('afternoon_peak', '午後のピーク (Afternoon Peak)'),
        ('evening_dip', '夕方のディップ (Evening Dip)'),
        ('evening_peak', '夜のピーク (Evening Peak)'),
    ]:
        abs_key = f'{cat_name}_abs_mean'
        if abs_key in stats:
            abs_mean = stats[abs_key]
            abs_std = stats[f'{cat_name}_abs_std']
            rel_mean = stats.get(f'{cat_name}_rel_mean', np.nan)
            rel_std = stats.get(f'{cat_name}_rel_std', np.nan)
            count = stats[f'{cat_name}_abs_count']

            report += f"\n### {cat_label}\n\n"
            report += f"- **絶対時刻**: {format_time(abs_mean)} ± {abs_std*60:.0f}分 ({count}日検出)\n"
            report += f"- **起床からの経過時間**: {rel_mean:.1f}h ± {rel_std:.1f}h\n"

            if f'{cat_name}_wake_corr' in stats:
                corr = stats[f'{cat_name}_wake_corr']
                report += f"- **起床時刻との相関**: r = {corr:.3f}\n"

    # 起床時刻の統計
    if 'wake_time_mean' in stats:
        wake_mean = stats['wake_time_mean']
        wake_std = stats['wake_time_std']
        report += f"\n### 起床時刻\n\n"
        report += f"- **平均起床時刻**: {format_time(wake_mean)} ± {wake_std*60:.0f}分\n"

    report += """

---

## 🔍 主要な発見

"""

    # パターン判定
    patterns = []

    if 'morning_peak_wake_corr' in stats:
        corr = stats['morning_peak_wake_corr']
        if corr > 0.7:
            patterns.append("### パターン: 起床時刻依存型（朝のピーク）\n\n"
                          "朝のピークは**起床時刻に強く依存**しています。"
                          "これはRiseアプリの予測方法（起床からX時間後）と一致します。")
        elif corr < 0.3:
            patterns.append("### パターン: 絶対時刻固定型（朝のピーク）\n\n"
                          "朝のピークは**絶対時刻で固定**されています。"
                          "体内時計が強く、起床時刻の影響を受けません。")

    # 安定性の比較
    if 'morning_peak_abs_std' in stats and 'morning_peak_rel_std' in stats:
        abs_std = stats['morning_peak_abs_std']
        rel_std = stats['morning_peak_rel_std']

        if rel_std < abs_std:
            patterns.append("### 安定性: 起床からの経過時間がより安定\n\n"
                          f"起床からの経過時間の標準偏差（{rel_std*60:.0f}分）が、"
                          f"絶対時刻の標準偏差（{abs_std*60:.0f}分）よりも小さいです。"
                          "これは**起床時刻を基準にした予測が有効**であることを示します。")
        else:
            patterns.append("### 安定性: 絶対時刻がより安定\n\n"
                          f"絶対時刻の標準偏差（{abs_std*60:.0f}分）が、"
                          f"起床からの経過時間の標準偏差（{rel_std*60:.0f}分）よりも小さいです。"
                          "これは**体内時計による固定時刻予測が有効**であることを示します。")

    report += "\n\n".join(patterns)

    report += """

---

## 📋 日毎の詳細データ

| 日付 | 起床時刻 | 朝peak | 昼dip | 午後peak | 夕方dip | 夜peak |
|------|---------|--------|-------|---------|--------|--------|
"""

    for _, row in df_daily.iterrows():
        date_str = row['date'].strftime('%m-%d')
        wake_str = row['wake_time'].strftime('%H:%M')

        def format_peak(cat_name):
            time_col = f'{cat_name}_time'
            since_wake_col = f'{cat_name}_since_wake'
            if pd.notna(row.get(time_col)):
                time_val = row[time_col]
                since_val = row.get(since_wake_col, np.nan)
                if pd.notna(since_val):
                    return f"{format_time(time_val)}<br/>(+{since_val:.1f}h)"
                else:
                    return format_time(time_val)
            return "-"

        report += f"| {date_str} | {wake_str} | "
        report += f"{format_peak('morning_peak')} | "
        report += f"{format_peak('afternoon_dip')} | "
        report += f"{format_peak('afternoon_peak')} | "
        report += f"{format_peak('evening_dip')} | "
        report += f"{format_peak('evening_peak')} |\n"

    report += """

---

## 💡 結論

この分析により、あなたのサーカディアンリズムが以下のどのパターンに該当するかが明らかになりました：

1. **起床時刻依存型**: Peak/Dipが起床からの経過時間で安定 → Riseアプリの予測が有効
2. **絶対時刻固定型**: Peak/Dipが特定の時刻で安定 → 体内時計が強い
3. **混合型**: 朝は起床依存、午後以降は絶対時刻固定

この結果を基に、最適な活動スケジュールを計画できます。

---

**生成日時**: 2026-01-07
**分析ツール**: dailybuild サーカディアンリズム分析モジュール
"""

    return report


def main():
    print("=" * 70)
    print("日毎サーカディアンリズム - Peak/Dip分析")
    print("=" * 70)

    # データ読み込み
    print("\n📂 データ読み込み中...")
    hr_df = pd.read_csv('data/fitbit/heart_rate_intraday.csv',
                       index_col='datetime', parse_dates=True)
    sleep_df = pd.read_csv('data/fitbit/sleep.csv')

    print(f"   心拍数データ: {len(hr_df):,}件")
    print(f"   睡眠データ: {len(sleep_df)}日分")

    # activity_logsから運動時間を抽出
    activity_periods = load_activity_periods()
    print(f"   運動記録: {len(activity_periods)}件")

    # 分析期間を決定（最新30日間）
    latest_date = hr_df.index.max().date()
    start_date = latest_date - timedelta(days=29)
    date_range = pd.date_range(start=start_date, end=latest_date, freq='D')

    print(f"\n📅 分析期間: {start_date} ~ {latest_date} ({len(date_range)}日間)")

    # 日毎の分析を実行
    print("\n🔍 日毎のpeak/dip分析を実行中...")
    df_daily = analyze_daily_peaks_dips(hr_df, sleep_df, activity_periods, date_range)

    print(f"\n✅ {len(df_daily)}日分の分析が完了")

    # 統計分析
    print("\n📊 統計分析を実行中...")
    stats = calculate_statistics(df_daily)

    # 可視化
    print("\n📊 可視化を生成中...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_file = os.path.join(script_dir, 'daily_peak_dip_analysis.png')
    visualize_daily_analysis(df_daily, output_file)

    # レポート生成
    print("\n📄 レポートを生成中...")
    report = generate_report(df_daily, stats)

    report_file = os.path.join(script_dir, 'DAILY_PEAK_DIP_ANALYSIS.md')
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"✅ レポートを生成: {report_file}")

    print("\n" + "=" * 70)
    print("✅ 分析完了！")
    print(f"   レポート: {report_file}")
    print(f"   画像: {output_file}")
    print("=" * 70)


if __name__ == '__main__':
    main()
