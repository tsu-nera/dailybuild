#!/usr/bin/env python
# coding: utf-8
"""
睡眠サイクル検出・分析ライブラリ

睡眠レベルデータから NREM-REM サイクルを検出し、
サイクル別の統計情報を計算する。

アルゴリズム:
    1. 最初の非覚醒ステージを睡眠開始（サイクル1開始）とする
    2. REM睡眠（min_rem_duration分以上）の終了をサイクルの終端とする
    3. 各サイクル内の睡眠ステージ時間を集計

References:
    - Heart rate-based algorithm for sleep stage classification
      https://www.frontiersin.org/articles/10.3389/fnins.2022.974192/full
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from dataclasses import dataclass
from typing import List, Optional, Dict


# =============================================================================
# 定数
# =============================================================================

STAGE_COLORS = {
    'wake': '#FF9500',   # オレンジ
    'rem': '#9B59B6',    # 紫
    'light': '#5DADE2',  # 水色
    'deep': '#2E4053',   # 濃紺
}


# =============================================================================
# データクラス
# =============================================================================

@dataclass
class SleepCycle:
    """
    睡眠サイクルを表すデータクラス

    睡眠は通常90分前後のサイクルで構成され、各サイクルは
    NREM期間（浅い睡眠 + 深い睡眠）とREM期間から成る。

    Attributes
    ----------
    cycle_num : int
        サイクル番号（1から始まる）
    start_min : float
        サイクル開始時刻（睡眠開始からの経過分数）
    end_min : float
        サイクル終了時刻（睡眠開始からの経過分数）
    nrem_duration : float
        NREM期間の長さ（分）
    rem_latency : float
        REM潜時（サイクル開始からREM開始までの時間、分）
    deep_minutes : float
        深い睡眠の合計時間（分）
    light_minutes : float
        浅い睡眠の合計時間（分）
    rem_minutes : float
        レム睡眠の合計時間（分）
    wake_minutes : float
        中途覚醒の合計時間（分）
    is_timeout : bool
        タイムアウトで強制終了されたか（REM未検出の可能性）
    """
    cycle_num: int
    start_min: float
    end_min: float
    nrem_duration: float
    rem_latency: float
    deep_minutes: float
    light_minutes: float
    rem_minutes: float
    wake_minutes: float
    is_timeout: bool = False

    @property
    def total_minutes(self) -> float:
        """サイクルの総時間（分）"""
        return self.end_min - self.start_min

    @property
    def nrem_minutes(self) -> float:
        """NREM睡眠の合計（deep + light）"""
        return self.deep_minutes + self.light_minutes

    @property
    def sleep_minutes(self) -> float:
        """実睡眠時間（wake除く）"""
        return self.deep_minutes + self.light_minutes + self.rem_minutes

    @property
    def deep_ratio(self) -> float:
        """サイクル内の深い睡眠の割合（%）"""
        if self.total_minutes == 0:
            return 0.0
        return self.deep_minutes / self.total_minutes * 100

    @property
    def rem_ratio(self) -> float:
        """サイクル内のREM睡眠の割合（%）"""
        if self.total_minutes == 0:
            return 0.0
        return self.rem_minutes / self.total_minutes * 100

    def to_dict(self) -> Dict:
        """辞書形式に変換"""
        return {
            'cycle_num': self.cycle_num,
            'start_min': self.start_min,
            'end_min': self.end_min,
            'total_min': self.total_minutes,
            'nrem_duration': self.nrem_duration,
            'rem_latency': self.rem_latency,
            'deep_min': self.deep_minutes,
            'light_min': self.light_minutes,
            'rem_min': self.rem_minutes,
            'wake_min': self.wake_minutes,
            'deep_ratio': self.deep_ratio,
            'rem_ratio': self.rem_ratio,
            'is_timeout': self.is_timeout,
        }


# =============================================================================
# サイクル検出
# =============================================================================

def detect_sleep_cycles(
    df_levels: pd.DataFrame,
    date: Optional[str] = None,
    min_rem_duration: float = 5.0,
    rem_gap_threshold: float = 30.0,
    max_cycle_length: float = 180.0,
) -> List[SleepCycle]:
    """
    睡眠レベルデータから睡眠サイクルを検出する

    アルゴリズム:
    1. 最初の非覚醒ステージを睡眠開始（サイクル1開始）とする
    2. REM睡眠の累積時間がmin_rem_duration以上になったらサイクル終了
    3. REM間の非REM時間がrem_gap_thresholdを超えたら累積REMをリセット
    4. サイクル時間がmax_cycle_lengthを超えたらタイムアウトで強制終了

    Parameters
    ----------
    df_levels : DataFrame
        sleep_levels.csvを読み込んだDataFrame
        必要カラム: dateOfSleep, dateTime, level, seconds, isShort
    date : str, optional
        分析対象の日付（'YYYY-MM-DD'形式）。Noneの場合は最新日
    min_rem_duration : float
        サイクル終端と判定するREM睡眠の累積最小時間（分）
    rem_gap_threshold : float
        REM間の非REM時間がこれを超えたら別のREMブロックとみなす（分）
    max_cycle_length : float
        サイクルの最大許容時間（分）。超過でタイムアウト終了

    Returns
    -------
    List[SleepCycle]
        検出されたサイクルのリスト
    """
    df = df_levels.copy()
    if not pd.api.types.is_datetime64_any_dtype(df['dateTime']):
        df['dateTime'] = pd.to_datetime(df['dateTime'])

    # 日付でフィルタ
    if date is None:
        date = df['dateOfSleep'].max()
    df_day = df[df['dateOfSleep'] == date].copy()

    if len(df_day) == 0:
        return []

    df_day = df_day.sort_values('dateTime')

    # 経過時間を計算
    start_time = df_day['dateTime'].min()
    df_day['elapsed_min'] = (df_day['dateTime'] - start_time).dt.total_seconds() / 60
    df_day['duration_min'] = df_day['seconds'] / 60

    # 短い覚醒を除外してメインの睡眠ステージのみ
    df_main = df_day[df_day['isShort'] == False].copy()

    cycles = []
    current_cycle_start = None
    cycle_stages = {'deep': 0.0, 'light': 0.0, 'rem': 0.0, 'wake': 0.0}
    rem_start = None
    nrem_end = None

    # 連続REM合算用
    cumulative_rem = 0.0
    last_rem_end = None
    nrem_since_last_rem = 0.0

    for _, row in df_main.iterrows():
        level = row['level']
        elapsed = row['elapsed_min']
        duration = row['duration_min']

        # 最初の非覚醒ステージでサイクル開始
        if current_cycle_start is None and level != 'wake':
            current_cycle_start = elapsed

        if current_cycle_start is None:
            continue

        # ステージ時間を加算
        cycle_stages[level] += duration

        # NREM→REMの遷移を検出
        if level in ['deep', 'light']:
            nrem_end = elapsed + duration
            # 最後のREM以降の非REM時間を累積
            if last_rem_end is not None:
                nrem_since_last_rem += duration

        if level == 'rem':
            if rem_start is None:
                rem_start = elapsed

            # 非REM時間がgap_thresholdを超えていたら累積REMをリセット
            if nrem_since_last_rem > rem_gap_threshold:
                cumulative_rem = 0.0

            cumulative_rem += duration
            last_rem_end = elapsed + duration
            nrem_since_last_rem = 0.0

        # 現在のサイクル時間を計算
        current_cycle_duration = elapsed + duration - current_cycle_start

        # タイムアウト検出: max_cycle_lengthを超えたら強制終了
        is_timeout = current_cycle_duration > max_cycle_length and level != 'rem'

        # サイクル終了条件: REM累積 >= 閾値 または タイムアウト
        should_end_cycle = (level == 'rem' and cumulative_rem >= min_rem_duration) or is_timeout

        if should_end_cycle:
            cycle_end = elapsed + duration

            # REM潜時を計算
            rem_latency = rem_start - current_cycle_start if rem_start else 0

            # NREM期間の長さ
            nrem_duration = nrem_end - current_cycle_start if nrem_end else 0

            cycle = SleepCycle(
                cycle_num=len(cycles) + 1,
                start_min=current_cycle_start,
                end_min=cycle_end,
                nrem_duration=nrem_duration,
                rem_latency=rem_latency,
                deep_minutes=cycle_stages['deep'],
                light_minutes=cycle_stages['light'],
                rem_minutes=cycle_stages['rem'],
                wake_minutes=cycle_stages['wake'],
                is_timeout=is_timeout,
            )
            cycles.append(cycle)

            # リセット
            current_cycle_start = cycle_end
            nrem_end = None
            rem_start = None
            cycle_stages = {'deep': 0.0, 'light': 0.0, 'rem': 0.0, 'wake': 0.0}
            # 累積REMもリセット
            cumulative_rem = 0.0
            last_rem_end = None
            nrem_since_last_rem = 0.0

    return cycles


def detect_cycles_multi_day(
    df_levels: pd.DataFrame,
    dates: Optional[List[str]] = None,
    **kwargs
) -> Dict[str, List[SleepCycle]]:
    """
    複数日の睡眠サイクルを検出

    Parameters
    ----------
    df_levels : DataFrame
        sleep_levels.csvを読み込んだDataFrame
    dates : List[str], optional
        分析対象の日付リスト。Noneの場合は全日付
    **kwargs
        detect_sleep_cyclesに渡すパラメータ

    Returns
    -------
    Dict[str, List[SleepCycle]]
        日付をキー、サイクルリストを値とする辞書
    """
    if dates is None:
        dates = sorted(df_levels['dateOfSleep'].unique())

    results = {}
    for date in dates:
        cycles = detect_sleep_cycles(df_levels, date=date, **kwargs)
        results[date] = cycles

    return results


def cycles_to_dataframe(
    df_levels: pd.DataFrame,
    df_master: Optional[pd.DataFrame] = None,
    max_cycles: int = 5,
    **kwargs
) -> pd.DataFrame:
    """
    サイクル検出結果をDataFrameのカラムとして返す

    各日の睡眠サイクル情報をDataFrameに変換する。
    レポート生成やsleep_master.csvとの結合に使用。

    Parameters
    ----------
    df_levels : DataFrame
        sleep_levels.csvを読み込んだDataFrame
    df_master : DataFrame, optional
        sleep_master.csvを読み込んだDataFrame（startTime含む）
        指定時はREM実時刻（rem{N}_time）を計算
    max_cycles : int
        出力するサイクルカラムの最大数（デフォルト5）
    **kwargs
        detect_sleep_cyclesに渡すパラメータ

    Returns
    -------
    DataFrame
        カラム:
        - dateOfSleep: 日付
        - cycle_count: 検出されたサイクル数
        - avg_cycle_length: 平均サイクル長（分）
        - cycle_length_std: サイクル長の標準偏差（規則性指標）
        - deep_latency: 最初の深い睡眠までの時間（分）
        - first_rem_latency: 最初のREMまでの時間（分）
        - deep_in_first_half: 前半サイクルの深い睡眠割合（%）
        - cycle{N}_length: サイクルNの長さ（分）
        - cycle{N}_deep: サイクルNの深い睡眠（分）
        - cycle{N}_rem: サイクルNのREM睡眠（分）
        - cycle{N}_timeout: サイクルNがタイムアウト終了か
        - rem{N}_onset: 第NサイクルのREM開始時刻（入眠からの分数、夢想起用）
        - bedtime: 就寝時刻（df_master指定時）
        - rem{N}_time: 第NサイクルのREM開始実時刻（df_master指定時）
    """
    all_cycles = detect_cycles_multi_day(df_levels, **kwargs)

    # deep_latency計算用にdf_levelsを準備
    df_prep = df_levels.copy()
    if not pd.api.types.is_datetime64_any_dtype(df_prep['dateTime']):
        df_prep['dateTime'] = pd.to_datetime(df_prep['dateTime'])

    rows = []
    for date, cycles in all_cycles.items():
        row = {'dateOfSleep': date}

        # サイクル数
        row['cycle_count'] = len(cycles)

        # deep_latency: 睡眠開始から最初の深い睡眠までの時間
        df_day = df_prep[df_prep['dateOfSleep'] == date].sort_values('dateTime')
        df_main = df_day[df_day['isShort'] == False]

        sleep_start = None
        for _, r in df_main.iterrows():
            if r['level'] != 'wake':
                sleep_start = r['dateTime']
                break

        first_deep = df_main[df_main['level'] == 'deep']['dateTime'].min()
        if sleep_start is not None and pd.notna(first_deep):
            row['deep_latency'] = (first_deep - sleep_start).total_seconds() / 60
        else:
            row['deep_latency'] = None

        # サイクル長の統計（サイクル分析特有の指標）
        if cycles:
            lengths = [c.total_minutes for c in cycles]
            row['avg_cycle_length'] = np.mean(lengths)
            row['cycle_length_std'] = np.std(lengths) if len(lengths) > 1 else 0.0

            # first_rem_latency: 第1サイクルのREM潜時
            row['first_rem_latency'] = cycles[0].rem_latency

            # avg_rem_interval: REM間隔（連続するREM開始時刻の差の平均）
            rem_onsets = []
            for c in cycles:
                if c.rem_minutes > 0:
                    rem_onsets.append(c.start_min + c.rem_latency)
            if len(rem_onsets) >= 2:
                intervals = [rem_onsets[i+1] - rem_onsets[i] for i in range(len(rem_onsets)-1)]
                row['avg_rem_interval'] = np.mean(intervals)
            else:
                row['avg_rem_interval'] = None

            # deep_in_first_half: 前半サイクル（1-2）の深い睡眠 / 全深い睡眠
            total_deep = sum(c.deep_minutes for c in cycles)
            if total_deep > 0:
                first_half_cycles = cycles[:2]  # 第1-2サイクル
                first_half_deep = sum(c.deep_minutes for c in first_half_cycles)
                row['deep_in_first_half'] = (first_half_deep / total_deep) * 100
            else:
                row['deep_in_first_half'] = None
        else:
            row['avg_cycle_length'] = None
            row['cycle_length_std'] = None
            row['first_rem_latency'] = None
            row['avg_rem_interval'] = None
            row['deep_in_first_half'] = None

        # 各サイクルの詳細
        for i in range(1, max_cycles + 1):
            if i <= len(cycles):
                c = cycles[i - 1]
                row[f'cycle{i}_length'] = c.total_minutes
                row[f'cycle{i}_deep'] = c.deep_minutes
                row[f'cycle{i}_rem'] = c.rem_minutes
                row[f'cycle{i}_timeout'] = c.is_timeout
            else:
                row[f'cycle{i}_length'] = None
                row[f'cycle{i}_deep'] = None
                row[f'cycle{i}_rem'] = None
                row[f'cycle{i}_timeout'] = None

        # 各サイクルのREM開始時刻（入眠からの経過分数）
        # 夢想起のための起床時刻計算に使用
        for i in range(1, max_cycles + 1):
            if i <= len(cycles):
                c = cycles[i - 1]
                # REM開始時刻 = サイクル開始 + REM潜時
                # rem_minutes > 0 で判定（rem_latency=0でもREMがあれば表示）
                rem_onset = c.start_min + c.rem_latency if c.rem_minutes > 0 else None
                row[f'rem{i}_onset'] = rem_onset
            else:
                row[f'rem{i}_onset'] = None

        rows.append(row)

    df_result = pd.DataFrame(rows)

    # df_master指定時は就寝時刻とREM実時刻を追加
    if df_master is not None and 'startTime' in df_master.columns:
        df_result = df_result.merge(
            df_master[['dateOfSleep', 'startTime']],
            on='dateOfSleep',
            how='left'
        )
        df_result['startTime'] = pd.to_datetime(df_result['startTime'])
        df_result['bedtime'] = df_result['startTime'].dt.strftime('%H:%M')

        # REM実時刻を計算
        for i in range(1, max_cycles + 1):
            onset_col = f'rem{i}_onset'
            if onset_col in df_result.columns:
                def calc_rem_time(row, col=onset_col):
                    if pd.notna(row[col]) and pd.notna(row['startTime']):
                        rem_time = row['startTime'] + pd.Timedelta(minutes=row[col])
                        return rem_time.strftime('%H:%M')
                    return None
                df_result[f'rem{i}_time'] = df_result.apply(calc_rem_time, axis=1)

        # startTimeカラムは削除（内部計算用）
        df_result = df_result.drop(columns=['startTime'])

    return df_result


# =============================================================================
# 統計計算
# =============================================================================

def calc_cycle_stats(
    cycles_by_date: Dict[str, List[SleepCycle]],
    max_cycles: int = 5,
    max_cycle_length: float = 180.0
) -> Dict:
    """
    サイクル別の統計情報を計算

    Parameters
    ----------
    cycles_by_date : Dict[str, List[SleepCycle]]
        detect_cycles_multi_dayの出力
    max_cycles : int
        分析するサイクル数の上限
    max_cycle_length : float
        異常値として除外するサイクル長（分）

    Returns
    -------
    Dict
        サイクル別統計情報
    """
    from collections import defaultdict

    # サイクル番号ごとにグループ化
    by_cycle_num = defaultdict(list)
    for date, cycles in cycles_by_date.items():
        for c in cycles:
            # 異常に長いサイクル（REM未検出）は除外
            if c.total_minutes <= max_cycle_length:
                by_cycle_num[c.cycle_num].append(c)

    stats = {
        'by_cycle': {},
        'summary': {},
    }

    # サイクル別の統計
    for cycle_num in range(1, max_cycles + 1):
        cycles = by_cycle_num.get(cycle_num, [])
        if not cycles:
            continue

        n = len(cycles)
        stats['by_cycle'][cycle_num] = {
            'n_samples': n,
            'avg_length': sum(c.total_minutes for c in cycles) / n,
            'avg_deep': sum(c.deep_minutes for c in cycles) / n,
            'avg_light': sum(c.light_minutes for c in cycles) / n,
            'avg_rem': sum(c.rem_minutes for c in cycles) / n,
            'avg_rem_latency': sum(c.rem_latency for c in cycles) / n,
            'deep_ratio': sum(c.deep_ratio for c in cycles) / n,
            'rem_ratio': sum(c.rem_ratio for c in cycles) / n,
        }

    # 前半 vs 後半の比較
    early = [c for num in [1, 2] for c in by_cycle_num.get(num, [])]
    late = [c for num in [3, 4, 5] for c in by_cycle_num.get(num, [])]

    if early:
        stats['summary']['early_cycles'] = {
            'n_samples': len(early),
            'avg_deep': sum(c.deep_minutes for c in early) / len(early),
            'avg_rem': sum(c.rem_minutes for c in early) / len(early),
        }
    if late:
        stats['summary']['late_cycles'] = {
            'n_samples': len(late),
            'avg_deep': sum(c.deep_minutes for c in late) / len(late),
            'avg_rem': sum(c.rem_minutes for c in late) / len(late),
        }

    # 全体平均
    all_cycles = [c for cycles in by_cycle_num.values() for c in cycles]
    if all_cycles:
        stats['summary']['overall'] = {
            'total_samples': len(all_cycles),
            'avg_cycle_length': sum(c.total_minutes for c in all_cycles) / len(all_cycles),
            'total_dates': len(cycles_by_date),
        }

    return stats


# =============================================================================
# 可視化
# =============================================================================

def plot_cycle_structure(
    cycles: List[SleepCycle],
    date: str = "",
    save_path=None
):
    """
    1日分の睡眠サイクル構造を可視化

    各サイクルをNREM期間とREM期間に分けて表示し、
    深い睡眠の分布を視覚化する。

    Parameters
    ----------
    cycles : List[SleepCycle]
        detect_sleep_cyclesの出力
    date : str
        日付（タイトル用）
    save_path : Path, optional
        保存先パス
    """
    if not cycles:
        return None, None

    fig, ax = plt.subplots(figsize=(12, 4))

    for c in cycles:
        # NREM期間（deep + light）
        nrem_start = c.start_min / 60
        nrem_width = c.nrem_duration / 60

        # 深い睡眠を下部に
        deep_height = c.deep_minutes / c.nrem_minutes if c.nrem_minutes > 0 else 0
        light_height = 1 - deep_height

        # 深い睡眠
        if c.deep_minutes > 0:
            ax.bar(nrem_start + nrem_width/2, deep_height, width=nrem_width,
                   bottom=0, color=STAGE_COLORS['deep'], alpha=0.9,
                   edgecolor='white', linewidth=0.5)
        # 浅い睡眠
        if c.light_minutes > 0:
            ax.bar(nrem_start + nrem_width/2, light_height, width=nrem_width,
                   bottom=deep_height, color=STAGE_COLORS['light'], alpha=0.9,
                   edgecolor='white', linewidth=0.5)

        # REM期間
        rem_start = (c.start_min + c.nrem_duration) / 60
        rem_width = c.rem_minutes / 60
        if c.rem_minutes > 0:
            ax.bar(rem_start + rem_width/2, 1, width=rem_width,
                   bottom=0, color=STAGE_COLORS['rem'], alpha=0.9,
                   edgecolor='white', linewidth=0.5)

        # サイクル番号ラベル
        cycle_center = (c.start_min + c.end_min) / 2 / 60
        ax.text(cycle_center, 1.1, f"C{c.cycle_num}\n{c.total_minutes:.0f}m",
                ha='center', va='bottom', fontsize=9, fontweight='bold')

        # サイクル区切り線
        ax.axvline(x=c.end_min/60, color='gray', linestyle='--', alpha=0.5)

    ax.set_xlim(0, cycles[-1].end_min / 60 + 0.5)
    ax.set_ylim(0, 1.3)
    ax.set_xlabel('Time from sleep onset (hours)')
    ax.set_ylabel('Stage proportion')
    ax.set_title(f'Sleep Cycle Structure - {date}' if date else 'Sleep Cycle Structure')

    # 凡例
    legend_patches = [
        mpatches.Patch(color=STAGE_COLORS['deep'], label='Deep (NREM N3)'),
        mpatches.Patch(color=STAGE_COLORS['light'], label='Light (NREM N1-N2)'),
        mpatches.Patch(color=STAGE_COLORS['rem'], label='REM'),
    ]
    ax.legend(handles=legend_patches, loc='upper right')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, ax


def plot_cycle_comparison(
    cycle_stats: Dict,
    save_path=None
):
    """
    サイクル別の統計比較グラフ

    Parameters
    ----------
    cycle_stats : Dict
        calc_cycle_statsの出力
    save_path : Path, optional
        保存先パス
    """
    by_cycle = cycle_stats.get('by_cycle', {})
    if not by_cycle:
        return None, None

    cycle_nums = sorted(by_cycle.keys())
    n_cycles = len(cycle_nums)

    fig, axes = plt.subplots(1, 3, figsize=(14, 4))

    # 1. サイクル長
    ax1 = axes[0]
    lengths = [by_cycle[n]['avg_length'] for n in cycle_nums]
    ax1.bar(range(n_cycles), lengths, color='steelblue', alpha=0.7)
    ax1.axhline(y=90, color='green', linestyle='--', label='Ideal (90min)')
    ax1.set_xticks(range(n_cycles))
    ax1.set_xticklabels([f'Cycle {n}' for n in cycle_nums])
    ax1.set_ylabel('Minutes')
    ax1.set_title('Average Cycle Length')
    ax1.legend()

    # 2. 深い睡眠
    ax2 = axes[1]
    deep = [by_cycle[n]['avg_deep'] for n in cycle_nums]
    ax2.bar(range(n_cycles), deep, color=STAGE_COLORS['deep'], alpha=0.9)
    ax2.set_xticks(range(n_cycles))
    ax2.set_xticklabels([f'Cycle {n}' for n in cycle_nums])
    ax2.set_ylabel('Minutes')
    ax2.set_title('Deep Sleep per Cycle')
    ax2.annotate('Expected: decreases →', xy=(0.5, 0.95), xycoords='axes fraction',
                 fontsize=8, color='gray', ha='center')

    # 3. REM睡眠
    ax3 = axes[2]
    rem = [by_cycle[n]['avg_rem'] for n in cycle_nums]
    ax3.bar(range(n_cycles), rem, color=STAGE_COLORS['rem'], alpha=0.9)
    ax3.set_xticks(range(n_cycles))
    ax3.set_xticklabels([f'Cycle {n}' for n in cycle_nums])
    ax3.set_ylabel('Minutes')
    ax3.set_title('REM Sleep per Cycle')
    ax3.annotate('Expected: increases →', xy=(0.5, 0.95), xycoords='axes fraction',
                 fontsize=8, color='gray', ha='center')

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"保存しました: {save_path}")

    return fig, axes


# =============================================================================
# テキスト出力
# =============================================================================

def print_cycle_report(cycles: List[SleepCycle], date: str = ""):
    """
    サイクル分析結果をテキストで出力

    Parameters
    ----------
    cycles : List[SleepCycle]
        detect_sleep_cyclesの出力
    date : str
        日付
    """
    if not cycles:
        print("サイクルが検出されませんでした")
        return

    print(f"\n{'='*60}")
    print(f"睡眠サイクル分析 {date}")
    print(f"{'='*60}")
    print(f"検出サイクル数: {len(cycles)}")
    print()

    print(f"{'サイクル':^8} | {'時間帯':^14} | {'長さ':^6} | {'深い':^6} | {'REM':^6} | {'REM潜時':^6}")
    print("-" * 65)

    for c in cycles:
        start_h = int(c.start_min // 60)
        start_m = int(c.start_min % 60)
        end_h = int(c.end_min // 60)
        end_m = int(c.end_min % 60)
        time_range = f"{start_h}:{start_m:02d}-{end_h}:{end_m:02d}"
        timeout_mark = " [!]" if c.is_timeout else ""

        print(f"  第{c.cycle_num}     | {time_range:^14} | {c.total_minutes:5.0f}分 | "
              f"{c.deep_minutes:5.0f}分 | {c.rem_minutes:5.0f}分 | {c.rem_latency:5.0f}分{timeout_mark}")

    print("-" * 65)
    total_deep = sum(c.deep_minutes for c in cycles)
    total_rem = sum(c.rem_minutes for c in cycles)
    avg_len = sum(c.total_minutes for c in cycles) / len(cycles)
    timeout_count = sum(1 for c in cycles if c.is_timeout)
    print(f"合計: 深い睡眠 {total_deep:.0f}分 | REM {total_rem:.0f}分 | 平均サイクル長 {avg_len:.0f}分")
    if timeout_count > 0:
        print(f"[!] タイムアウト終了: {timeout_count}件（REM未検出の可能性）")
