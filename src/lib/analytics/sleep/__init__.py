"""
睡眠データ分析パッケージ

モジュール:
    sleep_analysis: 睡眠統計・可視化
    sleep_cycle: 睡眠サイクル検出・分析
    sleep_need_estimator: 最適睡眠時間の推定
    sleep_debt_clean: 睡眠負債の計算
    sleep_intraday_analysis: 睡眠中のIntradayデータ分析
"""

from .sleep_analysis import (
    # 定数
    STAGE_COLORS,
    STAGE_Y_POSITION,
    # 統計分析
    calc_sleep_stats,
    calc_sleep_timing,
    calc_time_stats,
    calc_recovery_score,
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

from .sleep_intraday_analysis import (
    # 心拍数分析
    calc_resting_hr_baseline,
    calc_sleep_heart_rate_stats,
    calc_advanced_hr_metrics,
    # HRV分析
    calc_hrv_intraday_metrics,
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

from .sleep_need_estimator import (
    # データクラス
    SleepNeedEstimate,
    IntegratedSleepNeed,
    # 分析
    SleepNeedEstimator,
    # レポート
    print_sleep_need_report,
)

from .sleep_debt_clean import (
    # データクラス
    SleepDebtResult,
    # 分析
    SleepDebtCalculator,
    # 可視化
    plot_sleep_debt_trend,
    # レポート
    print_debt_report,
    format_debt_history_table,
)

__all__ = [
    # sleep_analysis
    'STAGE_COLORS',
    'STAGE_Y_POSITION',
    'calc_sleep_stats',
    'calc_sleep_timing',
    'calc_time_stats',
    'calc_recovery_score',
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
    # sleep_need_estimator
    'SleepNeedEstimate',
    'IntegratedSleepNeed',
    'SleepNeedEstimator',
    'print_sleep_need_report',
    # sleep_debt_clean
    'SleepDebtResult',
    'SleepDebtCalculator',
    'plot_sleep_debt_trend',
    'print_debt_report',
    'format_debt_history_table',
    # sleep_intraday_analysis
    'calc_resting_hr_baseline',
    'calc_sleep_heart_rate_stats',
    'calc_advanced_hr_metrics',
    'calc_hrv_intraday_metrics',
]
