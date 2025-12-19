"""
自己覚醒仮説の検証分析 v2

仮説: 心に強く時間を思うと、そこから逆算されてREM1, REM2, REM3が決まる

既存のsleep_cycleライブラリを使用して正しくREM開始時刻を抽出
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import sys

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.lib.analytics.sleep.sleep_cycle import detect_cycles_multi_day, cycles_to_dataframe
from src.lib.analytics.sleep.sleep_analysis import calc_sleep_timing

# プロジェクトルート
project_root = Path(__file__).parent.parent.parent

# データ読み込み
sleep_df = pd.read_csv(project_root / 'data/fitbit/sleep.csv')
sleep_levels_df = pd.read_csv(project_root / 'data/fitbit/sleep_levels.csv')

# 日時カラムをdatetimeに変換
sleep_df['startTime'] = pd.to_datetime(sleep_df['startTime'])
sleep_df['endTime'] = pd.to_datetime(sleep_df['endTime'])
sleep_levels_df['dateTime'] = pd.to_datetime(sleep_levels_df['dateTime'])

# メイン睡眠のみフィルタ
main_sleep_df = sleep_df[sleep_df['isMainSleep'] == True].copy()

# メイン睡眠のlogIdのみでlevelsをフィルタ
main_log_ids = main_sleep_df['logId'].unique()
main_sleep_levels_df = sleep_levels_df[sleep_levels_df['logId'].isin(main_log_ids)].copy()

# サイクル検出とDataFrame変換（既存ライブラリ使用）
print("サイクル検出中...")
df_cycles = cycles_to_dataframe(
    df_levels=main_sleep_levels_df,
    df_master=main_sleep_df,
    max_cycles=5,
    max_cycle_length=180
)

print(f"検出完了: {len(df_cycles)} セッション")
print()

# Markdownレポート生成
report_lines = []

def add_line(text=""):
    report_lines.append(text)

add_line("# 自己覚醒仮説の検証分析")
add_line()
add_line("## 仮説")
add_line()
add_line("> 心に強く起床時刻を思うと、その時刻から逆算されてREM1, REM2, REM3の出現時刻が決まる")
add_line()

# 基本情報
df_cycles['date'] = pd.to_datetime(df_cycles['dateOfSleep'])

add_line("## データサマリー")
add_line()
add_line(f"- **分析期間**: {df_cycles['dateOfSleep'].min()} 〜 {df_cycles['dateOfSleep'].max()}")
add_line(f"- **総睡眠セッション数**: {len(df_cycles)}")
add_line()
add_line("> **注意**: この分析では「起床時刻」= 目が覚めた時刻を使用（sleep_levels.csvから計算）")
add_line()

# 起床時刻を計算（週次レポートと同じ方法）
# calc_sleep_timing() を使用して sleep_levels.csv から起床後時間を計算
print("起床時刻を計算中...")
sleep_timing = calc_sleep_timing(main_sleep_levels_df)

# マスタデータとマージ
df_analysis = df_cycles.merge(
    main_sleep_df[['dateOfSleep', 'startTime', 'endTime']],
    on='dateOfSleep',
    how='left'
)

# 各日付の起床時刻を計算
wakeup_times = []
out_of_bed_times = []
wake_time_strs = []
wake_hours = []

for _, row in df_analysis.iterrows():
    date = row['dateOfSleep']
    end_time = row['endTime']

    # sleep_timing から起床後時間を取得
    timing = sleep_timing.get(date, {})
    after_wake_min = timing.get('minutes_after_wakeup', 0)

    # 起床時刻 = 離床時刻 - 起床後時間
    if after_wake_min > 0:
        wakeup_dt = end_time - pd.Timedelta(minutes=after_wake_min)
    else:
        wakeup_dt = end_time

    wakeup_times.append(wakeup_dt)
    wake_time_strs.append(wakeup_dt.strftime('%H:%M'))
    wake_hours.append(wakeup_dt.hour + wakeup_dt.minute / 60.0)
    out_of_bed_times.append(end_time.strftime('%H:%M'))

df_analysis['wakeup_datetime'] = wakeup_times
df_analysis['wake_time'] = wake_time_strs
df_analysis['wake_hour'] = wake_hours
df_analysis['out_of_bed_time'] = out_of_bed_times

# 起床時刻の分布
add_line("## 起床時刻の分布")
add_line()

wake_dist = df_analysis['wake_time'].value_counts().head(10)
add_line("| 起床時刻 | 回数 |")
add_line("|---------|------|")
for wake_time, count in wake_dist.items():
    add_line(f"| {wake_time} | {count} |")
add_line()

# 6:10-6:30の範囲でフィルタ
target_df = df_analysis[(df_analysis['wake_hour'] >= 6.17) & (df_analysis['wake_hour'] <= 6.50)].copy()
target_df = target_df.sort_values('dateOfSleep')

add_line("## 主要分析：起床時刻（目覚め）6:10-6:30 のREM睡眠パターン")
add_line()
add_line(f"**対象データ数**: {len(target_df)} セッション")
add_line()
add_line("> 起床時刻 = 目が覚めた時刻（離床時刻 - ベッド内覚醒時間）")
add_line()

if len(target_df) >= 5:
    add_line("### 詳細データ")
    add_line()
    add_line("| 日付 | 就寝 | 起床(目覚め) | 離床 | REM1 | REM2 | REM3 | REM4 | REM5 |")
    add_line("|------|------|------------|------|------|------|------|------|------|")

    for _, row in target_df.iterrows():
        date_str = row['dateOfSleep'][5:]  # MM-DD
        bedtime = row['bedtime'] if pd.notna(row.get('bedtime')) else '-'
        wake_time = row['wake_time']
        out_of_bed = row['out_of_bed_time']

        rem_times = []
        for i in range(1, 6):
            col = f'rem{i}_time'
            if col in row and pd.notna(row[col]):
                rem_times.append(row[col])
            else:
                rem_times.append('-')

        add_line(f"| {date_str} | {bedtime} | {wake_time} | {out_of_bed} | {rem_times[0]} | {rem_times[1]} | {rem_times[2]} | {rem_times[3]} | {rem_times[4]} |")

    add_line()

    # REM1-3の統合分析
    add_line("### REM1-3から目覚め時刻までの差分分析")
    add_line()
    add_line("> 各REMから目覚めるまでの時間（分）を分析。時系列で差分が減少すれば、REMが起床時刻に近づいている。")
    add_line()

    # 各日付のREM1-3データを収集
    rem_all_data = []
    for _, row in target_df.iterrows():
        date = row['dateOfSleep']
        wake_time = row['wake_time']
        wake_h = row['wake_hour']
        if wake_h < 12:
            wake_h += 24

        rem_row = {
            'date': date,
            'wake_time': wake_time,
        }

        # REM1-5の差分を計算
        for i in range(1, 6):
            col = f'rem{i}_time'
            if col in row and pd.notna(row[col]) and row[col] != '-':
                h, m = map(int, row[col].split(':'))
                rem_h = h + m / 60.0
                if h < 12:
                    rem_h += 24
                diff_min = (wake_h - rem_h) * 60
                rem_row[f'rem{i}_diff'] = diff_min
                rem_row[f'rem{i}_time'] = row[col]
            else:
                rem_row[f'rem{i}_diff'] = None
                rem_row[f'rem{i}_time'] = '-'

        rem_all_data.append(rem_row)

    rem_all_df = pd.DataFrame(rem_all_data)

    # 統合テーブル表示
    add_line("#### 各REMから目覚めまでの時間（分）")
    add_line()
    add_line("| 日付 | 起床 | REM1→起床 | REM2→起床 | REM3→起床 | REM4→起床 |")
    add_line("|------|------|----------|----------|----------|----------|")

    for _, row in rem_all_df.iterrows():
        date_str = row['date'][5:]
        wake = row['wake_time']
        rem1 = f"{row['rem1_diff']:.0f}分" if pd.notna(row['rem1_diff']) else '-'
        rem2 = f"{row['rem2_diff']:.0f}分" if pd.notna(row['rem2_diff']) else '-'
        rem3 = f"{row['rem3_diff']:.0f}分" if pd.notna(row['rem3_diff']) else '-'
        rem4 = f"{row['rem4_diff']:.0f}分" if pd.notna(row['rem4_diff']) else '-'

        add_line(f"| {date_str} | {wake} | {rem1} | {rem2} | {rem3} | {rem4} |")

    add_line()

    # 各REMの時系列トレンド分析
    add_line("#### 各REMの時系列トレンド")
    add_line()

    rem_trends = []
    for i in range(1, 5):
        diff_col = f'rem{i}_diff'
        valid_data = rem_all_df[rem_all_df[diff_col].notna()]

        if len(valid_data) >= 3:
            seq = list(range(len(valid_data)))
            diffs = valid_data[diff_col].tolist()

            # 差分が減少傾向 = 起床時刻に近づく = 負の相関
            corr = np.corrcoef(seq, diffs)[0, 1] if len(seq) > 1 else 0

            trend = ""
            if corr < -0.3:
                trend = "✅ 起床に近づく"
            elif corr > 0.3:
                trend = "❌ 起床から遠ざかる"
            else:
                trend = "➖ 変化なし"

            rem_trends.append({
                'REM': f'REM{i}',
                'データ数': len(valid_data),
                '平均差分': f"{np.mean(diffs):.0f}分",
                '相関係数': f"{corr:.3f}",
                'トレンド': trend
            })

    if rem_trends:
        trends_df = pd.DataFrame(rem_trends)
        add_line(trends_df.to_markdown(index=False))
        add_line()
        add_line("> 相関係数: 負の値 = 差分減少（起床時刻に近づく）、正の値 = 差分増加（起床時刻から遠ざかる）")
        add_line()

    # REM3の詳細分析（既存）
    add_line("### REM3の詳細分析")
    add_line()

    rem3_data = []
    for _, row in target_df.iterrows():
        if 'rem3_time' in row and pd.notna(row['rem3_time']) and row['rem3_time'] != '-':
            # 時刻を10進数に変換
            h, m = map(int, row['rem3_time'].split(':'))
            hour_decimal = h + m / 60.0
            # 0-6時は翌日とみなす
            if h < 12:
                hour_decimal += 24

            wake_h = row['wake_hour']
            if wake_h < 12:
                wake_h += 24

            # 起床時刻までの差分（分）
            diff_min = (wake_h - hour_decimal) * 60

            rem3_data.append({
                'date': row['dateOfSleep'],
                'rem3_time': row['rem3_time'],
                'wake_time': row['wake_time'],
                'rem3_hour': hour_decimal,
                'wake_hour': wake_h,
                'diff_min': diff_min
            })

    if len(rem3_data) >= 3:
        rem3_df = pd.DataFrame(rem3_data)

        add_line("| 日付 | REM3時刻 | 起床(目覚め) | 差分(分) |")
        add_line("|------|----------|------------|---------|")

        for _, row in rem3_df.iterrows():
            add_line(f"| {row['date'][5:]} | {row['rem3_time']} | {row['wake_time']} | {row['diff_min']:.0f} |")

        add_line()

        # 相関分析（時系列でREM3が後退しているか）
        seq = list(range(len(rem3_df)))
        rem3_hours = rem3_df['rem3_hour'].tolist()

        if len(seq) > 1:
            corr = np.corrcoef(seq, rem3_hours)[0, 1]
            add_line(f"**時系列相関係数**: {corr:.3f}")
            add_line()

            if corr > 0.3:
                add_line("✅ **REM3の出現時刻が後退傾向**（起床時刻に近づいている）")
                add_line()
                add_line("→ 仮説を支持する結果！起床時刻を意識することで、REM3が起床時刻に近づいている可能性")
            elif corr < -0.3:
                add_line("❌ REM3の出現時刻が前進傾向（起床時刻から遠ざかっている）")
            else:
                add_line("➖ 明確なトレンドなし")
            add_line()

        # 直近5日のトレンド
        if len(rem3_df) >= 5:
            recent_rem3 = rem3_df.tail(5)
            recent_seq = list(range(len(recent_rem3)))
            recent_hours = recent_rem3['rem3_hour'].tolist()

            if len(recent_seq) > 1:
                recent_corr = np.corrcoef(recent_seq, recent_hours)[0, 1]

                add_line(f"### 直近5日のトレンド（相関係数: {recent_corr:.3f}）")
                add_line()

                if recent_corr > 0.3:
                    add_line("✅ **直近5日でREM3が起床時刻に近づく明確な傾向を確認**")
                    add_line()
                    add_line("詳細:")
                    for _, row in recent_rem3.iterrows():
                        add_line(f"- {row['date'][5:]}: REM3={row['rem3_time']}, 起床={row['wake_time']}, 差分={row['diff_min']:.0f}分")
                    add_line()
                elif recent_corr < -0.3:
                    add_line("❌ 直近5日ではREM3が起床時刻から遠ざかる傾向")
                    add_line()
                else:
                    add_line("➖ 直近5日では明確なトレンドなし")
                    add_line()

    # REM4の分析
    add_line("### REM4出現時刻のトレンド分析")
    add_line()

    rem4_data = []
    for _, row in target_df.iterrows():
        if 'rem4_time' in row and pd.notna(row['rem4_time']) and row['rem4_time'] != '-':
            h, m = map(int, row['rem4_time'].split(':'))
            hour_decimal = h + m / 60.0
            if h < 12:
                hour_decimal += 24

            wake_h = row['wake_hour']
            if wake_h < 12:
                wake_h += 24

            diff_min = (wake_h - hour_decimal) * 60

            rem4_data.append({
                'date': row['dateOfSleep'],
                'rem4_time': row['rem4_time'],
                'wake_time': row['wake_time'],
                'rem4_hour': hour_decimal,
                'diff_min': diff_min
            })

    if len(rem4_data) >= 3:
        rem4_df = pd.DataFrame(rem4_data)

        add_line("| 日付 | REM4時刻 | 起床(目覚め) | 差分(分) |")
        add_line("|------|----------|------------|---------|")

        for _, row in rem4_df.iterrows():
            add_line(f"| {row['date'][5:]} | {row['rem4_time']} | {row['wake_time']} | {row['diff_min']:.0f} |")

        add_line()

        seq = list(range(len(rem4_df)))
        rem4_hours = rem4_df['rem4_hour'].tolist()

        if len(seq) > 1:
            corr = np.corrcoef(seq, rem4_hours)[0, 1]
            add_line(f"**時系列相関係数**: {corr:.3f}")
            add_line()

            if corr > 0.3:
                add_line("✅ **REM4の出現時刻が後退傾向**（起床時刻に近づいている）")
            elif corr < -0.3:
                add_line("❌ REM4の出現時刻が前進傾向")
            else:
                add_line("➖ 明確なトレンドなし")
            add_line()

add_line("## 考察")
add_line()

add_line("### 自己覚醒メカニズムとの整合性")
add_line()
add_line("科学的に知られている自己覚醒のメカニズム:")
add_line("1. 目標起床時刻の1-2時間前からコルチゾール分泌が増加")
add_line("2. 目標時刻に向けて浅い睡眠（REM）の出現頻度が増える")
add_line("3. 脳の時間感覚が起床準備を開始")
add_line()

add_line("### データからの示唆")
add_line()

if len(rem3_data) >= 5:
    rem3_df = pd.DataFrame(rem3_data)
    overall_corr = np.corrcoef(range(len(rem3_df)), rem3_df['rem3_hour'])[0, 1]

    if overall_corr > 0.2:
        add_line(f"✅ **仮説を支持するデータを確認**（相関係数: {overall_corr:.3f}）")
        add_line()
        add_line("起床時刻（6:20-6:40）を継続的に意識することで、")
        add_line("REM3/4の出現時刻が起床時刻に近づく傾向が観察されました。")
        add_line()
        add_line("これは以下を示唆:")
        add_line("- 脳が目標起床時刻を学習し、睡眠構造を適応的に調整")
        add_line("- 自己覚醒の準備として、後半のREM周期が起床時刻に同期")
        add_line("- 「強く思う」ことで、この適応メカニズムが強化される可能性")
    else:
        add_line(f"⚠️ **一貫した傾向は確認できず**（相関係数: {overall_corr:.3f}）")
        add_line()
        add_line("データからは明確なトレンドが見られませんでした。")

add_line()

add_line("## 結論")
add_line()

if len(rem3_data) >= 5:
    rem3_df = pd.DataFrame(rem3_data)
    overall_corr = np.corrcoef(range(len(rem3_df)), rem3_df['rem3_hour'])[0, 1]

    if overall_corr > 0.2:
        add_line("### ✅ 仮説の妥当性を示唆するデータを確認")
    else:
        add_line("### ⚠️ データからは明確な結論を出せず")
else:
    add_line("### ⚠️ データ不足")

add_line()

add_line("### 今後の検証方針")
add_line()
add_line("1. **意識的実験**: 起床時刻を強く意識する期間 vs 意識しない期間を比較")
add_line("2. **主観記録**: 毎晩「何時に起きようと思ったか」を記録")
add_line("3. **長期観察**: 30日以上のデータで統計的検証")
add_line("4. **変数統制**: 就寝時刻、睡眠時間、ストレスレベルを記録")
add_line()

add_line("---")
add_line()
add_line("## 分析方法について")
add_line()
add_line("**起床時刻の定義**")
add_line("- この分析では「起床時刻」= 目が覚めた時刻（wakeup time）を使用")
add_line("- 計算方法: `calc_sleep_timing()` を使用してsleep_levels.csvから起床後時間を計算")
add_line("  - 最後の睡眠レベルが 'wake' の場合、その継続時間を起床後時間とする")
add_line("  - 起床時刻 = 離床時刻（endTime） - 起床後時間")
add_line("- この方法は週次睡眠レポートと同一のロジックを使用")
add_line("- 自己覚醒の分析には、離床時刻ではなく目覚めた時刻が重要")
add_line()
add_line("---")
add_line()
add_line(f"*分析日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
add_line()
add_line("*使用ライブラリ: src/lib/analytics/sleep/sleep_cycle.py*")

# レポート保存
output_dir = Path(__file__).parent

report_path = output_dir / 'REPORT.md'
with open(report_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report_lines))

print(f"✅ レポート生成完了: {report_path}")

# データも保存
df_analysis.to_csv(output_dir / 'analysis_data.csv', index=False, encoding='utf-8')
print(f"✅ データ保存完了: {output_dir / 'analysis_data.csv'}")
