#!/usr/bin/env python
# coding: utf-8
"""
最適睡眠時間推定ライブラリ

個人の睡眠必要量を複数の手法で推定し、
データの信頼性に応じて適切な値を算出する。

主要クラス:
    SleepNeedEstimate: 推定結果のデータクラス
    SleepNeedEstimator: 睡眠必要量推定器
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, Dict, List


@dataclass
class SleepNeedEstimate:
    """
    睡眠必要量の推定結果

    Attributes:
        method: 推定方法
        value_hours: 推定値（時間）
        confidence: 信頼度 (low/medium/high)
        sample_size: サンプル数
        note: 説明・注意事項
        weight: 重み（統合時に使用）
    """
    method: str
    value_hours: float
    confidence: str
    sample_size: int
    note: str
    weight: float = 1.0


@dataclass
class IntegratedSleepNeed:
    """
    統合推定結果

    Attributes:
        recommended_hours: 推奨睡眠時間（時間）
        habitual_hours: 習慣的睡眠時間（時間）
        potential_debt_hours: 潜在的睡眠負債（時間）
        confidence: 全体の信頼度
        estimates: 各推定方法の結果
        note: 推奨理由
    """
    recommended_hours: float
    habitual_hours: float
    potential_debt_hours: float
    confidence: str
    estimates: Dict[str, SleepNeedEstimate]
    note: str


class SleepNeedEstimator:
    """
    最適睡眠時間推定器

    複数の手法で睡眠必要量を推定し、データの質に応じて重み付けを行う。

    Parameters:
        sleep_data: 睡眠データ（dateOfSleep, minutesAsleep, efficiencyを含む）
        hrv_data: HRVデータ（オプション）
        lookback_days: 分析対象期間（デフォルト: 90日）
        rebound_top_percentile: 睡眠リバウンド法で使用する上位パーセンテージ（デフォルト: 4.0%）
    """

    # 成人の推奨睡眠時間（米国睡眠財団）
    RECOMMENDED_MIN = 7.0
    RECOMMENDED_MAX = 9.0
    RECOMMENDED_CENTER = 8.0

    def __init__(
        self,
        sleep_data: pd.DataFrame,
        hrv_data: Optional[pd.DataFrame] = None,
        lookback_days: int = 90,
        rebound_top_percentile: float = 4.0
    ):
        """初期化"""
        self.sleep_data = sleep_data.copy()
        self.hrv_data = hrv_data
        self.lookback_days = lookback_days
        self.rebound_top_percentile = rebound_top_percentile

        # 日付処理
        if 'dateOfSleep' in self.sleep_data.columns:
            self.sleep_data['dateOfSleep'] = pd.to_datetime(self.sleep_data['dateOfSleep'])
            self.date_column = 'dateOfSleep'
        else:
            self.sleep_data.index = pd.to_datetime(self.sleep_data.index)
            self.date_column = None

        # HRVデータのマージ
        if hrv_data is not None:
            self._merge_hrv_data()

    def estimate(self, end_date: Optional[datetime] = None) -> IntegratedSleepNeed:
        """
        睡眠必要量を推定

        複数の手法で推定し、データの質に応じて重み付けして統合する。

        Args:
            end_date: 分析終了日（デフォルト: 最新日）

        Returns:
            IntegratedSleepNeed: 統合推定結果
        """
        if end_date is None:
            end_date = self._get_latest_date()

        # 各手法で推定
        estimates = self._estimate_all_methods(end_date)

        # 統合推奨値を計算
        integrated = self._integrate_estimates(estimates)

        # 習慣的睡眠時間
        habitual = estimates['habitual'].value_hours

        # 潜在的睡眠負債
        potential_debt = max(0, integrated - habitual)

        # 信頼度を判定
        confidence = self._assess_confidence(estimates)

        # 推奨理由
        note = self._generate_recommendation_note(integrated, habitual, estimates)

        return IntegratedSleepNeed(
            recommended_hours=round(integrated, 1),
            habitual_hours=round(habitual, 1),
            potential_debt_hours=round(potential_debt, 1),
            confidence=confidence,
            estimates=estimates,
            note=note
        )

    def _estimate_all_methods(self, end_date: datetime) -> Dict[str, SleepNeedEstimate]:
        """全ての推定手法を実行"""
        start_date = end_date - timedelta(days=self.lookback_days - 1)
        period_data = self._filter_by_period(start_date, end_date)

        estimates = {}

        # 1. 習慣的睡眠時間（HSD）
        estimates['habitual'] = self._estimate_habitual(period_data)

        # 2. 一般推奨値
        estimates['recommended'] = self._estimate_recommended()

        # 3. 複合パフォーマンススコア（HRV + 効率 + 深い睡眠）
        if 'daily_rmssd' in period_data.columns and 'efficiency' in period_data.columns:
            estimates['performance'] = self._estimate_by_performance(period_data)

        # 4. 高効率日
        if 'efficiency' in period_data.columns:
            estimates['efficiency'] = self._estimate_by_efficiency(period_data)

        # 5. HRV上位日（重みは小さく）
        if 'daily_rmssd' in period_data.columns:
            estimates['hrv'] = self._estimate_by_hrv(period_data)

        # 6. 睡眠リバウンド法
        estimates['sleep_rebound'] = self._estimate_by_sleep_rebound(period_data)

        return estimates

    def _estimate_habitual(self, period_data: pd.DataFrame) -> SleepNeedEstimate:
        """習慣的睡眠時間（HSD）を推定"""
        sleep_minutes = period_data['minutesAsleep'].values

        # 外れ値除外（IQR法）
        Q1 = np.percentile(sleep_minutes, 25)
        Q3 = np.percentile(sleep_minutes, 75)
        IQR = Q3 - Q1
        filtered = sleep_minutes[
            (sleep_minutes >= Q1 - 1.5 * IQR) &
            (sleep_minutes <= Q3 + 1.5 * IQR)
        ]

        value_hours = np.median(filtered) / 60

        # 推奨範囲との比較
        if value_hours < self.RECOMMENDED_MIN:
            confidence = 'low'
            note = f'⚠ 推奨範囲（{self.RECOMMENDED_MIN}-{self.RECOMMENDED_MAX}h）を下回っています。慢性的睡眠不足の可能性。'
            weight = 0.5  # 推奨範囲外なので重みを下げる
        elif value_hours > self.RECOMMENDED_MAX:
            confidence = 'medium'
            note = '推奨範囲を上回っていますが、個人差の範囲内の可能性。'
            weight = 1.0
        else:
            confidence = 'high'
            note = '推奨範囲内です。'
            weight = 2.0  # 推奨範囲内なら重みを上げる

        return SleepNeedEstimate(
            method='習慣的睡眠時間（HSD）',
            value_hours=round(value_hours, 2),
            confidence=confidence,
            sample_size=len(filtered),
            note=note,
            weight=weight
        )

    def _estimate_recommended(self) -> SleepNeedEstimate:
        """一般推奨値（科学的根拠）"""
        return SleepNeedEstimate(
            method='一般推奨値（米国睡眠財団）',
            value_hours=self.RECOMMENDED_CENTER,
            confidence='high',
            sample_size=0,  # 研究ベース
            note='大規模研究に基づく成人の推奨値。個人差があります。',
            weight=5.0  # 最も重視
        )

    def _estimate_by_performance(self, period_data: pd.DataFrame) -> SleepNeedEstimate:
        """複合パフォーマンススコアによる推定"""
        # データのクリーニング
        valid_data = period_data.dropna(subset=['daily_rmssd', 'efficiency', 'minutesAsleep'])

        if len(valid_data) < 10:
            return SleepNeedEstimate(
                method='複合パフォーマンススコア',
                value_hours=0.0,
                confidence='low',
                sample_size=len(valid_data),
                note=f'データ不足（{len(valid_data)}日）。最低10日必要。',
                weight=0.0
            )

        # 深い睡眠の割合を計算
        if 'deepMinutes' in valid_data.columns:
            valid_data = valid_data.copy()
            valid_data['deepPercent'] = valid_data['deepMinutes'] / valid_data['minutesAsleep'] * 100
        else:
            valid_data['deepPercent'] = 0

        # 正規化して複合スコア算出
        def normalize(series):
            return (series - series.mean()) / series.std()

        valid_data['hrv_norm'] = normalize(valid_data['daily_rmssd'])
        valid_data['eff_norm'] = normalize(valid_data['efficiency'])
        valid_data['deep_norm'] = normalize(valid_data['deepPercent']) if valid_data['deepPercent'].std() > 0 else 0

        valid_data['composite_score'] = (
            valid_data['hrv_norm'] * 0.4 +
            valid_data['eff_norm'] * 0.4 +
            valid_data['deep_norm'] * 0.2
        )

        # 上位30%の日
        threshold = valid_data['composite_score'].quantile(0.70)
        top_days = valid_data[valid_data['composite_score'] >= threshold]

        value_hours = top_days['minutesAsleep'].median() / 60

        # 信頼度の判定
        if len(top_days) >= 10:
            confidence = 'high'
            weight = 3.0
        elif len(top_days) >= 5:
            confidence = 'medium'
            weight = 2.0
        else:
            confidence = 'low'
            weight = 1.0

        return SleepNeedEstimate(
            method='複合パフォーマンススコア上位日',
            value_hours=round(value_hours, 2),
            confidence=confidence,
            sample_size=len(top_days),
            note=f'HRV、効率、深い睡眠の複合評価で上位30%の日の睡眠時間。',
            weight=weight
        )

    def _estimate_by_efficiency(self, period_data: pd.DataFrame) -> SleepNeedEstimate:
        """高効率日の睡眠時間"""
        valid_data = period_data.dropna(subset=['efficiency', 'minutesAsleep'])

        if len(valid_data) < 10:
            return SleepNeedEstimate(
                method='高効率日',
                value_hours=0.0,
                confidence='low',
                sample_size=len(valid_data),
                note='データ不足。',
                weight=0.0
            )

        threshold = valid_data['efficiency'].quantile(0.70)
        top_days = valid_data[valid_data['efficiency'] >= threshold]

        value_hours = top_days['minutesAsleep'].median() / 60

        return SleepNeedEstimate(
            method='高効率日（上位30%）',
            value_hours=round(value_hours, 2),
            confidence='medium',
            sample_size=len(top_days),
            note=f'睡眠効率≥{threshold:.0f}%の日の睡眠時間。',
            weight=2.0
        )

    def _estimate_by_hrv(self, period_data: pd.DataFrame) -> SleepNeedEstimate:
        """HRV上位日の睡眠時間（注意: 相関が弱い）"""
        valid_data = period_data.dropna(subset=['daily_rmssd', 'minutesAsleep'])

        if len(valid_data) < 10:
            return SleepNeedEstimate(
                method='HRV上位日',
                value_hours=0.0,
                confidence='low',
                sample_size=len(valid_data),
                note='データ不足。',
                weight=0.0
            )

        threshold = valid_data['daily_rmssd'].quantile(0.70)
        top_days = valid_data[valid_data['daily_rmssd'] >= threshold]

        value_hours = top_days['minutesAsleep'].median() / 60

        return SleepNeedEstimate(
            method='HRV上位日（上位30%）',
            value_hours=round(value_hours, 2),
            confidence='low',  # HRVとの相関が弱いため
            sample_size=len(top_days),
            note=f'⚠ HRVと睡眠時間の相関は弱い（r≈0.12）。参考程度。',
            weight=1.0  # 重みを下げる
        )

    def _estimate_by_sleep_rebound(self, period_data: pd.DataFrame) -> SleepNeedEstimate:
        """睡眠リバウンド法による推定（RISE式）

        睡眠時間が最も長かった上位N%の日の平均を、真の睡眠必要量とする。
        RISEアプリと同じアルゴリズムを実装。

        アルゴリズム:
        1. 全データから上位N%（デフォルト4%）の最も睡眠時間が長い日を抽出
        2. その平均値を最適睡眠時間とする
        3. 外れ値除外は行わない（9時間以上の睡眠も重要なデータ）

        理論的根拠:
        - 睡眠負債からの完全回復日が真の睡眠必要量を示す
        - 短期的な睡眠不足で習慣的睡眠時間が低下している可能性を考慮
        - 相対的な割合を使うことで期間依存性を排除

        Parameters:
            period_data: 分析対象の睡眠データ

        Returns:
            SleepNeedEstimate: 推定結果
        """
        valid_data = period_data.dropna(subset=['minutesAsleep']).copy()

        if len(valid_data) < 30:
            return SleepNeedEstimate(
                method='睡眠リバウンド法',
                value_hours=0.0,
                confidence='low',
                sample_size=len(valid_data),
                note='データ不足。最低30日必要。',
                weight=0.0
            )

        # 上位N%のサンプル数を計算
        n_samples = max(1, int(len(valid_data) * self.rebound_top_percentile / 100))

        # 睡眠時間が最も長い上位N%を抽出
        top_days = valid_data.nlargest(n_samples, 'minutesAsleep')

        # 平均値を計算
        value_hours = top_days['minutesAsleep'].mean() / 60

        # 信頼度判定（サンプル数ベース）
        if n_samples >= 10:
            confidence = 'high'
            weight = 2.5
        elif n_samples >= 5:
            confidence = 'medium'
            weight = 1.5
        else:
            confidence = 'low'
            weight = 0.5

        # 習慣的睡眠時間（参考情報）
        habitual_hours = valid_data['minutesAsleep'].median() / 60

        return SleepNeedEstimate(
            method='睡眠リバウンド法',
            value_hours=round(value_hours, 2),
            confidence=confidence,
            sample_size=n_samples,
            note=f'睡眠時間上位{self.rebound_top_percentile:.1f}%（{n_samples}日）の平均。習慣的睡眠（{habitual_hours:.1f}h）より{value_hours - habitual_hours:.1f}h長く、睡眠不足からの回復を示唆。',
            weight=weight
        )

    def _integrate_estimates(self, estimates: Dict[str, SleepNeedEstimate]) -> float:
        """複数の推定値を重み付き平均で統合"""
        valid_estimates = {
            key: est for key, est in estimates.items()
            if est.value_hours > 0 and est.weight > 0
        }

        if not valid_estimates:
            # フォールバック: 一般推奨値
            return self.RECOMMENDED_CENTER

        total_weight = sum(est.weight for est in valid_estimates.values())
        weighted_sum = sum(est.value_hours * est.weight for est in valid_estimates.values())

        integrated = weighted_sum / total_weight

        # 推奨範囲内にクリップ
        return np.clip(integrated, self.RECOMMENDED_MIN, self.RECOMMENDED_MAX)

    def _assess_confidence(self, estimates: Dict[str, SleepNeedEstimate]) -> str:
        """全体の信頼度を評価"""
        # 7時間以上のデータがあるか
        habitual = estimates['habitual'].value_hours

        # データ充足度
        total_samples = estimates['habitual'].sample_size

        if total_samples < 30:
            return 'low'
        elif habitual >= self.RECOMMENDED_MIN:
            # 推奨範囲内のデータがある
            return 'high'
        else:
            # データはあるが推奨範囲外
            return 'medium'

    def _generate_recommendation_note(
        self,
        integrated: float,
        habitual: float,
        estimates: Dict[str, SleepNeedEstimate]
    ) -> str:
        """推奨理由を生成"""
        diff = integrated - habitual

        if diff > 0.5:
            return (
                f'現在の習慣的睡眠時間（{habitual:.1f}h）は推奨値より'
                f'{diff:.1f}h少ない可能性があります。'
                f'7時間以上の睡眠を試して、パフォーマンスの変化を観察することを推奨します。'
            )
        elif diff < -0.5:
            return f'現在の睡眠時間は十分です。'
        else:
            return f'現在の睡眠時間は適切です。'

    # -------------------------------------------------------------------------
    # ユーティリティ
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

    def _merge_hrv_data(self):
        """HRVデータをマージ"""
        if self.hrv_data is None:
            return

        hrv_df = self.hrv_data.copy()

        # 日付カラムの処理
        if 'date' in hrv_df.columns:
            hrv_df['date'] = pd.to_datetime(hrv_df['date'])
        else:
            hrv_df.index = pd.to_datetime(hrv_df.index)
            hrv_df = hrv_df.reset_index()
            hrv_df.rename(columns={hrv_df.columns[0]: 'date'}, inplace=True)

        # マージ
        if self.date_column:
            self.sleep_data = pd.merge(
                self.sleep_data,
                hrv_df[['date', 'daily_rmssd', 'deep_rmssd']],
                left_on=self.date_column,
                right_on='date',
                how='left'
            )


def print_sleep_need_report(result: IntegratedSleepNeed):
    """睡眠必要量推定結果のレポート出力"""
    print("=" * 80)
    print("  睡眠必要量推定レポート")
    print("=" * 80)
    print()

    print(f"★ 推奨睡眠時間: {result.recommended_hours:.1f}時間")
    print(f"   信頼度: {result.confidence.upper()}")
    print()
    print(f"   習慣的睡眠時間: {result.habitual_hours:.1f}時間")
    print(f"   潜在的睡眠負債: {result.potential_debt_hours:.1f}時間/日 ({int(result.potential_debt_hours * 60)}分)")
    print()
    print(f"推奨理由:")
    print(f"  {result.note}")
    print()

    print("-" * 80)
    print("推定方法の詳細")
    print("-" * 80)
    print()

    for method_key, est in result.estimates.items():
        if est.value_hours > 0:
            print(f"■ {est.method}")
            print(f"  推定値: {est.value_hours:.1f}h")
            print(f"  重み: {est.weight:.1f}")
            print(f"  信頼度: {est.confidence}")
            print(f"  サンプル数: {est.sample_size}日")
            print(f"  {est.note}")
            print()

    print("=" * 80)
