#!/usr/bin/env python
# coding: utf-8
"""
睡眠負債計算ライブラリ

睡眠必要量（sleep_need）を受け取り、睡眠負債を計算する。
最適睡眠時間の推定は sleep_need_estimator.py を使用すること。

主要クラス:
    SleepDebtResult: 睡眠負債計算結果のデータクラス
    SleepDebtCalculator: 睡眠負債計算器
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Tuple, List


@dataclass
class SleepDebtResult:
    """
    睡眠負債計算結果

    Attributes:
        date: 分析日
        sleep_need_hours: 睡眠必要量（時間）
        sleep_debt_hours: 睡眠負債（時間）
        category: カテゴリ (None/Low/Moderate/High)
        avg_sleep_hours: 計算期間の平均睡眠時間（時間）
        data_points: データ点数
        daily_deficits: 日ごとの不足分（分）
        recovery_days_estimate: 推定回復日数
    """
    date: datetime
    sleep_need_hours: float
    sleep_debt_hours: float
    category: str
    avg_sleep_hours: float
    data_points: int
    daily_deficits: List[float]
    recovery_days_estimate: int

    def __str__(self):
        """文字列表現"""
        return (
            f"Sleep Debt ({self.date.strftime('%Y-%m-%d')})\n"
            f"  Need: {self.sleep_need_hours:.1f}h\n"
            f"  Average: {self.avg_sleep_hours:.1f}h\n"
            f"  Debt: {self.sleep_debt_hours:.1f}h ({self.category})\n"
            f"  Recovery: {self.recovery_days_estimate} days"
        )


class SleepDebtCalculator:
    """
    睡眠負債計算器

    睡眠必要量を元に、過去の睡眠データから睡眠負債を計算する。

    Parameters:
        sleep_data: 睡眠データ（dateOfSleep, minutesAsleepを含む）
        sleep_need_hours: 睡眠必要量（時間）
        window_days: 負債計算期間（デフォルト: 14日）
        min_data_points: 最低必要データ数（デフォルト: 5）
    """

    # カテゴリの閾値（Oura Ring準拠）
    CATEGORY_THRESHOLDS = {
        'None': 0.0,
        'Low': 2.0,
        'Moderate': 5.0,
        'High': float('inf'),
    }

    # 回復速度（研究ベース: 1時間の負債 = 3-4日で回復）
    RECOVERY_RATE_PER_DAY = 0.3  # 1日あたり0.3時間回復

    def __init__(
        self,
        sleep_data: pd.DataFrame,
        sleep_need_hours: float,
        window_days: int = 14,
        min_data_points: int = 5
    ):
        """
        初期化

        Args:
            sleep_data: 睡眠データ
            sleep_need_hours: 睡眠必要量（時間）
            window_days: 負債計算期間
            min_data_points: 最低必要データ数
        """
        self.sleep_data = sleep_data.copy()
        self.sleep_need_minutes = sleep_need_hours * 60
        self.window_days = window_days
        self.min_data_points = min_data_points

        # 日付カラムの処理
        if 'dateOfSleep' in self.sleep_data.columns:
            self.sleep_data['dateOfSleep'] = pd.to_datetime(self.sleep_data['dateOfSleep'])
            self.sleep_data = self.sleep_data.sort_values('dateOfSleep')
            self.date_column = 'dateOfSleep'
        else:
            self.sleep_data.index = pd.to_datetime(self.sleep_data.index)
            self.sleep_data = self.sleep_data.sort_index()
            self.date_column = None

    def calculate(
        self,
        end_date: Optional[datetime] = None,
        weight_method: str = 'linear'
    ) -> SleepDebtResult:
        """
        睡眠負債を計算（累積方式）

        Args:
            end_date: 基準日（デフォルト: 最新日）
            weight_method: 重み付け方法
                - 'linear': 線形減衰（0.5-1.0）
                - 'exponential': 指数減衰
                - 'uniform': 均等

        Returns:
            SleepDebtResult: 睡眠負債計算結果
        """
        if end_date is None:
            end_date = self._get_latest_date()

        # 過去window_days日間のデータを取得
        start_date = end_date - timedelta(days=self.window_days - 1)
        window_data = self._filter_by_period(start_date, end_date)

        if len(window_data) < self.min_data_points:
            raise ValueError(
                f"睡眠負債の計算には最低{self.min_data_points}夜分のデータが必要です "
                f"（現在: {len(window_data)}夜）"
            )

        # 日ごとの不足分を計算（プラス=不足、マイナス=余剰）
        sleep_minutes = window_data['minutesAsleep'].values
        daily_deficits = self.sleep_need_minutes - sleep_minutes

        # 重み付け
        weights = self._calculate_weights(len(daily_deficits), weight_method)

        # 重み付き累積負債（Oura Ring方式）
        # 各日の不足分に重みを掛けて累積
        weighted_cumulative_debt = np.sum(daily_deficits * weights)

        # 負の値（睡眠過剰による返済）も考慮し、最終的に0以下にはしない
        total_debt_minutes = max(0, weighted_cumulative_debt)
        sleep_debt_hours = total_debt_minutes / 60

        # カテゴリ分類
        category = self._categorize_debt(sleep_debt_hours)

        # 平均睡眠時間
        avg_sleep_minutes = np.mean(sleep_minutes)

        # 回復日数の推定
        recovery_days = self._estimate_recovery_days(sleep_debt_hours)

        return SleepDebtResult(
            date=end_date,
            sleep_need_hours=round(self.sleep_need_minutes / 60, 1),
            sleep_debt_hours=round(sleep_debt_hours, 2),
            category=category,
            avg_sleep_hours=round(avg_sleep_minutes / 60, 1),
            data_points=len(window_data),
            daily_deficits=daily_deficits.tolist(),
            recovery_days_estimate=recovery_days,
        )

    def get_history(
        self,
        start_date: datetime,
        end_date: datetime,
        weight_method: str = 'linear'
    ) -> pd.DataFrame:
        """
        期間内の睡眠負債履歴を取得

        Args:
            start_date: 開始日
            end_date: 終了日
            weight_method: 重み付け方法

        Returns:
            pd.DataFrame: 日ごとの睡眠負債データ
        """
        date_range = pd.date_range(start_date, end_date)
        history = []

        for date in date_range:
            try:
                result = self.calculate(end_date=date, weight_method=weight_method)
                history.append({
                    'date': date,
                    'sleep_need_hours': result.sleep_need_hours,
                    'avg_sleep_hours': result.avg_sleep_hours,
                    'sleep_debt_hours': result.sleep_debt_hours,
                    'category': result.category,
                    'recovery_days': result.recovery_days_estimate,
                })
            except ValueError:
                # データ不足の場合はスキップ
                continue

        return pd.DataFrame(history)

    # -------------------------------------------------------------------------
    # 内部メソッド
    # -------------------------------------------------------------------------

    def _get_latest_date(self) -> datetime:
        """最新の日付を取得"""
        if self.date_column:
            return self.sleep_data[self.date_column].max()
        else:
            return self.sleep_data.index.max()

    def _filter_by_period(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """期間でフィルタリング"""
        if self.date_column:
            mask = (
                (self.sleep_data[self.date_column] >= start_date) &
                (self.sleep_data[self.date_column] <= end_date)
            )
            return self.sleep_data[mask].copy()
        else:
            return self.sleep_data.loc[start_date:end_date].copy()

    def _calculate_weights(self, n: int, method: str) -> np.ndarray:
        """重み付けを計算"""
        if method == 'linear':
            # 線形減衰: 最古の日 0.5 → 最新の日 1.0
            return np.linspace(0.5, 1.0, n)
        elif method == 'exponential':
            # 指数減衰
            decay_rate = 0.1
            weights = np.exp(decay_rate * np.arange(n))
            return weights / np.max(weights)
        else:  # uniform
            return np.ones(n)

    def _categorize_debt(self, sleep_debt_hours: float) -> str:
        """睡眠負債をカテゴリ分類"""
        if sleep_debt_hours == 0:
            return 'None'
        elif sleep_debt_hours < self.CATEGORY_THRESHOLDS['Low']:
            return 'Low'
        elif sleep_debt_hours < self.CATEGORY_THRESHOLDS['Moderate']:
            return 'Moderate'
        else:
            return 'High'

    def _estimate_recovery_days(self, sleep_debt_hours: float) -> int:
        """回復日数を推定"""
        if sleep_debt_hours == 0:
            return 0
        return int(np.ceil(sleep_debt_hours / self.RECOVERY_RATE_PER_DAY))


# =============================================================================
# 可視化
# =============================================================================

def plot_sleep_debt_trend(
    history_df: pd.DataFrame,
    figsize: Tuple[int, int] = (12, 6),
    save_path: Optional[str] = None
) -> plt.Figure:
    """睡眠負債のトレンドをプロット"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, sharex=True)

    # 上段: 睡眠時間と必要量
    ax1.plot(
        history_df['date'],
        history_df['sleep_need_hours'],
        label='Sleep Need',
        color='#2E4053',
        linestyle='--',
        linewidth=2
    )
    ax1.plot(
        history_df['date'],
        history_df['avg_sleep_hours'],
        label='Actual Sleep',
        color='#5DADE2',
        linewidth=2
    )
    ax1.fill_between(
        history_df['date'],
        history_df['sleep_need_hours'],
        history_df['avg_sleep_hours'],
        where=history_df['avg_sleep_hours'] < history_df['sleep_need_hours'],
        alpha=0.3,
        color='#FF9500',
        label='Deficit'
    )
    ax1.set_ylabel('Hours', fontsize=12)
    ax1.set_title('Sleep Duration vs. Sleep Need', fontsize=14, fontweight='bold')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)

    # 下段: 睡眠負債
    colors = {
        'None': '#27AE60',
        'Low': '#F39C12',
        'Moderate': '#E67E22',
        'High': '#E74C3C'
    }

    for category, color in colors.items():
        mask = history_df['category'] == category
        if mask.any():
            ax2.scatter(
                history_df.loc[mask, 'date'],
                history_df.loc[mask, 'sleep_debt_hours'],
                label=category,
                color=color,
                s=50,
                alpha=0.7
            )

    ax2.plot(
        history_df['date'],
        history_df['sleep_debt_hours'],
        color='gray',
        linewidth=1,
        alpha=0.5
    )

    # カテゴリ境界線
    ax2.axhline(y=0, color='#27AE60', linestyle=':', alpha=0.5)
    ax2.axhline(y=2, color='#F39C12', linestyle=':', alpha=0.5)
    ax2.axhline(y=5, color='#E74C3C', linestyle=':', alpha=0.5)

    ax2.set_xlabel('Date', fontsize=12)
    ax2.set_ylabel('Sleep Debt (hours)', fontsize=12)
    ax2.set_title('Sleep Debt Trend', fontsize=14, fontweight='bold')
    ax2.legend(loc='best')
    ax2.grid(True, alpha=0.3)

    # 日付フォーマット
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
    ax2.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(history_df) // 10)))
    plt.xticks(rotation=45)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')

    return fig


def format_debt_history_table(history_df: pd.DataFrame) -> pd.DataFrame:
    """
    睡眠負債履歴をレポート用テーブルにフォーマット

    Parameters
    ----------
    history_df : pd.DataFrame
        get_history()で取得した睡眠負債履歴データ

    Returns
    -------
    pd.DataFrame
        レポート用にフォーマットされたテーブル（日付, 実績, 負債, 増減, 回復）
    """
    df = history_df.copy()

    # 前日比の増減を計算
    df['debt_change'] = df['sleep_debt_hours'].diff()

    # テーブル用にフォーマット
    table_data = pd.DataFrame()
    table_data['日付'] = pd.to_datetime(df['date']).dt.strftime('%m/%d')
    table_data['実績'] = df['avg_sleep_hours'].apply(lambda x: f'{x:.1f}h')
    table_data['負債'] = df['sleep_debt_hours'].apply(lambda x: f'{x:.1f}h')

    # 増減：最初の日は'-'、それ以降は+/-付きで表示
    def format_change(change):
        if pd.isna(change):
            return '-'
        elif change > 0:
            return f'+{change:.1f}h'
        else:
            return f'{change:.1f}h'

    table_data['増減'] = df['debt_change'].apply(format_change)
    table_data['回復'] = df['recovery_days'].apply(lambda x: f'{x}日')

    return table_data


def print_debt_report(result: SleepDebtResult):
    """睡眠負債レポートをコンソール出力"""
    print("=" * 60)
    print(f"  睡眠負債レポート - {result.date.strftime('%Y-%m-%d')}")
    print("=" * 60)
    print()

    # カテゴリ別のメッセージ
    messages = {
        'None': "✓ 睡眠負債なし！理想的な睡眠習慣です。",
        'Low': "⚠ わずかな睡眠負債。今夜は早めに就寝を。",
        'Moderate': "⚠⚠ 睡眠負債が蓄積中。週末で回復を計画しましょう。",
        'High': "⚠⚠⚠ 深刻な睡眠負債。優先的に睡眠時間を確保してください。"
    }

    print(f"{messages[result.category]}")
    print()
    print(f"  睡眠必要量:       {result.sleep_need_hours:.1f}時間")
    print(f"  平均睡眠時間:     {result.avg_sleep_hours:.1f}時間")
    print(f"  睡眠負債:         {result.sleep_debt_hours:.1f}時間 ({result.category})")
    print(f"  回復予測:         {result.recovery_days_estimate}日")
    print()

    # 回復のアドバイス
    if result.sleep_debt_hours > 0:
        extra_hours = result.sleep_debt_hours / result.recovery_days_estimate
        suggested_sleep = result.sleep_need_hours + extra_hours
        print("推奨アクション:")
        print(f"  {result.recovery_days_estimate}日で回復するには:")
        print(f"  → 毎晩{suggested_sleep:.1f}時間睡眠（+{extra_hours:.1f}h追加）")
    else:
        print("推奨アクション:")
        print(f"  → 現在の睡眠習慣を維持（{result.sleep_need_hours:.1f}h/晩）")

    print()
    print("=" * 60)
