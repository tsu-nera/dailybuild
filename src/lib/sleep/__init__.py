"""
睡眠データ分析パッケージ

モジュール:
    sleep_analysis: 睡眠統計・可視化
    sleep_cycle: 睡眠サイクル検出・分析
"""

from .sleep_analysis import (
    # 定数
    STAGE_COLORS,
    STAGE_Y_POSITION,
    # 統計分析
    calc_sleep_stats,
    calc_sleep_timing,
    calc_time_stats,
    print_sleep_stats,
    # 可視化
    plot_sleep_duration,
    plot_time_in_bed_stacked,
    plot_sleep_stages_stacked,
    plot_sleep_stages_pie,
    plot_sleep_dashboard,
    plot_sleep_timeline,
    plot_single_day_timeline,
)

from .sleep_cycle import (
    # データクラス
    SleepCycle,
    # サイクル検出
    detect_sleep_cycles,
    detect_cycles_multi_day,
    cycles_to_dataframe,
    # 統計
    calc_cycle_stats,
    # 可視化
    plot_cycle_structure,
    plot_cycle_comparison,
    print_cycle_report,
)

__all__ = [
    # sleep_analysis
    'STAGE_COLORS',
    'STAGE_Y_POSITION',
    'calc_sleep_stats',
    'calc_sleep_timing',
    'calc_time_stats',
    'print_sleep_stats',
    'plot_sleep_duration',
    'plot_time_in_bed_stacked',
    'plot_sleep_stages_stacked',
    'plot_sleep_stages_pie',
    'plot_sleep_dashboard',
    'plot_sleep_timeline',
    'plot_single_day_timeline',
    # sleep_cycle
    'SleepCycle',
    'detect_sleep_cycles',
    'detect_cycles_multi_day',
    'cycles_to_dataframe',
    'calc_cycle_stats',
    'plot_cycle_structure',
    'plot_cycle_comparison',
    'print_cycle_report',
]
