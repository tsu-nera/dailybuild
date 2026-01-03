# Fitbitデータを活用した睡眠負債機能の実装可能性検討

## 概要

Oura Ringの睡眠負債（Sleep Debt）機能をFitbit APIで取得したデータを活用して実装できるかを検討した結果をまとめる。

**検討日**: 2026-01-01
**対象**: Oura Ring Sleep Debt機能のFitbitデータによる再現

---

## 1. Oura Ring Sleep Debt機能の仕様

### 1.1 基本定義

睡眠負債は、過去2週間で個人の睡眠必要量に対してどれだけ睡眠が不足しているかを示す指標。

### 1.2 計算方法

| 項目 | 詳細 |
|------|------|
| **データ要件** | 過去14日以内に最低5夜分の睡眠データ |
| **基準値（睡眠必要量）の算出** | 過去90日間の睡眠パターンから個人のベースラインを確立（外れ値除外） |
| **負債計算** | 過去14日間の総睡眠時間と睡眠必要量を日ごとに比較 |
| **重み付け** | 最近の日により大きな重みを適用 |

### 1.3 睡眠負債カテゴリ

| レベル | 時間 | 説明 |
|--------|------|------|
| **None** | 0時間 | 睡眠必要量を一貫して満たしている |
| **Low** | <2時間 | ほぼ睡眠必要量を満たしているが、数日間やや不足 |
| **Moderate** | 2-5時間 | 中程度の睡眠負債が蓄積 |
| **High** | >5時間 | 大きな睡眠負債が蓄積 |

### 1.4 使用データ

Oura Ringが使用する主なデータソース：

- 総睡眠時間
- 睡眠ステージ（覚醒、浅い睡眠、深い睡眠、REM睡眠）
- 心拍数変動（HRV）
- 心拍数
- 動き
- 体温

---

## 2. Fitbitで利用可能なデータ

### 2.1 既存データ（`/data/fitbit/`）

現在収集済みのFitbitデータ：

#### sleep.csv
```
- dateOfSleep: 睡眠日
- startTime, endTime: 睡眠開始/終了時刻
- duration: 睡眠時間（ミリ秒）
- minutesAsleep: 総睡眠時間（分）
- minutesAwake: 覚醒時間（分）
- efficiency: 睡眠効率（%）
- deepMinutes, lightMinutes, remMinutes, wakeMinutes: 各睡眠ステージの時間
- deepAvg30, lightAvg30, remAvg30, wakeAvg30: 30日移動平均
```

#### sleep_levels.csv
```
- logId: 睡眠ログID
- dateTime: タイムスタンプ
- level: 睡眠ステージ（wake, light, deep, rem）
- seconds: 継続時間（秒）
- isShort: 短時間覚醒フラグ
```

#### hrv.csv
```
- date: 日付
- daily_rmssd: 日次HRV（全体）
- deep_rmssd: 深い睡眠中のHRV
```

#### heart_rate.csv
```
- date: 日付
- resting_heart_rate: 安静時心拍数
```

### 2.2 Fitbit API仕様

**Sleep API (v1.2)**
- 睡眠ステージ: 30秒単位のデータ（deep, light, rem, wake）
- 睡眠ログ: 開始/終了時刻、総睡眠時間
- 制限: Sleep Scoreは非サポート

**HRV & Heart Rate API**
- HRV: 日次データ（30日単位で取得可能）
- 安静時心拍数: 日次データ（30日単位で取得可能）

---

## 3. 実装可能性の分析

### 3.1 データ充足度

| 必要データ | Fitbitでの利用可能性 | 状態 |
|-----------|---------------------|------|
| 総睡眠時間 | ✅ `minutesAsleep` | **利用可能** |
| 睡眠ステージ | ✅ deep/light/rem/wake | **利用可能** |
| HRV | ✅ daily_rmssd, deep_rmssd | **利用可能** |
| 安静時心拍数 | ✅ resting_heart_rate | **利用可能** |
| 体温 | ✅ temperature_skin.csv | **利用可能** |
| 動き | ⚠️ 間接的（睡眠ステージから推定可能） | **推定可能** |
| 過去90日間データ | ✅ 履歴データ蓄積済み | **利用可能** |

**結論**: Oura Ringの睡眠負債機能を実装するための**基本データは揃っている**。

### 3.2 実装アプローチ

#### ステップ1: 個人の睡眠必要量を算出

```python
# 擬似コード
def calculate_sleep_need(sleep_data_90days):
    """
    過去90日間の睡眠データから個人の睡眠必要量を算出

    Parameters:
        sleep_data_90days: 過去90日間の睡眠データ（minutesAsleep）

    Returns:
        sleep_need_minutes: 個人の睡眠必要量（分）
    """
    # 外れ値を除外（例: IQR法）
    Q1 = sleep_data_90days.quantile(0.25)
    Q3 = sleep_data_90days.quantile(0.75)
    IQR = Q3 - Q1

    filtered_data = sleep_data_90days[
        (sleep_data_90days >= Q1 - 1.5 * IQR) &
        (sleep_data_90days <= Q3 + 1.5 * IQR)
    ]

    # 中央値または平均を使用（Ouraは具体的な方法を非公開）
    # より保守的な推定には中央値が適している
    sleep_need_minutes = filtered_data.median()

    return sleep_need_minutes
```

#### ステップ2: 睡眠負債を計算

```python
# 擬似コード
def calculate_sleep_debt(sleep_data_14days, sleep_need_minutes):
    """
    過去14日間の睡眠負債を計算

    Parameters:
        sleep_data_14days: 過去14日間の睡眠データ（minutesAsleep）
        sleep_need_minutes: 個人の睡眠必要量（分）

    Returns:
        sleep_debt_hours: 睡眠負債（時間）
    """
    # 最低5夜分のデータがあるか確認
    if len(sleep_data_14days) < 5:
        return None

    # 日ごとの負債を計算
    daily_deficits = sleep_need_minutes - sleep_data_14days['minutesAsleep']

    # 最近の日により重みづけ（例: 線形減衰）
    # 最新日の重み=1.0, 14日前の重み=0.5
    weights = np.linspace(0.5, 1.0, len(daily_deficits))

    # 重み付き睡眠負債の合計
    weighted_debt_minutes = (daily_deficits * weights).sum() / weights.sum()

    # 負の値（睡眠過剰）は0にクリップ
    total_debt_minutes = max(0, weighted_debt_minutes)

    sleep_debt_hours = total_debt_minutes / 60

    return sleep_debt_hours
```

#### ステップ3: カテゴリ分類

```python
def categorize_sleep_debt(sleep_debt_hours):
    """睡眠負債をカテゴリ分類"""
    if sleep_debt_hours == 0:
        return "None"
    elif sleep_debt_hours < 2:
        return "Low"
    elif sleep_debt_hours <= 5:
        return "Moderate"
    else:
        return "High"
```

### 3.3 拡張機能（オプション）

Oura Ringの完全な再現のため、以下の拡張も検討可能：

1. **睡眠品質スコアとの統合**
   - HRVや深い睡眠の割合を考慮
   - 単なる時間だけでなく、睡眠の質も評価

2. **動的な睡眠必要量調整**
   - 活動量（activity.csv）に基づいて必要量を調整
   - 高強度運動後は睡眠必要量を増やす

3. **季節変動の考慮**
   - 体温データ（temperature_skin.csv）から季節パターンを検出
   - 季節ごとの睡眠パターン変化に対応

---

## 4. 実装の課題と制約

### 4.1 データの制約

| 課題 | 影響度 | 対策 |
|------|--------|------|
| Ouraの具体的なアルゴリズムは非公開 | 中 | 論理的な近似アルゴリズムで実装 |
| 過去90日間のデータが必要 | 低 | 既存データで十分カバー可能 |
| データ欠損時の処理 | 中 | 最低5夜分のデータ要件を設定 |

### 4.2 精度の検証

Oura Ringとの直接比較ができないため、以下の方法で妥当性を検証：

1. **主観的評価との相関**
   - ユーザーの主観的な疲労感と睡眠負債の相関を確認

2. **睡眠時間の統計的妥当性**
   - 算出された睡眠必要量が一般的な成人の範囲（7-9時間）内か確認

3. **トレンドの一貫性**
   - 睡眠不足が続いた週と睡眠負債の増加が一致するか確認

---

## 5. 結論と推奨事項

### 5.1 実装可能性: **高い ✅**

Fitbitで収集済みのデータを使用して、Oura Ring風の睡眠負債機能を**実装可能**。

**理由**:
- 必要なデータ（総睡眠時間、睡眠ステージ、HRV、心拍数）が全て利用可能
- 過去90日間の履歴データが蓄積済み
- 計算ロジックは公開情報から合理的に推定可能

### 5.2 推奨実装フェーズ

#### フェーズ1: 基本機能（MVP）
- [ ] 過去90日間データから睡眠必要量を算出
- [ ] 過去14日間の睡眠負債を計算
- [ ] カテゴリ分類とシンプルな可視化

#### フェーズ2: 精度向上
- [ ] 外れ値除外アルゴリズムの最適化
- [ ] 重み付け方法の調整（線形 vs 指数減衰）
- [ ] 主観的評価データとの相関検証

#### フェーズ3: 拡張機能
- [ ] 活動量に基づく睡眠必要量の動的調整
- [ ] HRVや睡眠効率を考慮した質的評価
- [ ] 週次・月次レポートへの統合

### 5.3 次のステップ

1. **プロトタイプ実装**: `src/lib/analytics/sleep_debt.py` を作成
2. **データ分析**: 既存の睡眠データで睡眠必要量の妥当性を検証
3. **レポート統合**: 睡眠レポートに睡眠負債セクションを追加

---

## 6. 参考資料

### Oura Ring公式情報

- [New to the Oura App: Understanding Sleep Debt](https://ouraring.com/blog/sleep-debt/)
- [Sleep Debt – Oura Help](https://support.ouraring.com/hc/en-us/articles/46233324892691-Sleep-Debt)
- [How Does the Oura Ring Track My Sleep?](https://ouraring.com/blog/how-does-the-oura-ring-track-my-sleep/)
- [Oura's New Sleep Staging Algorithm](https://ouraring.com/blog/new-sleep-staging-algorithm/)
- [Your Oura Readiness Score](https://ouraring.com/blog/readiness-score/)
- [Heart Rate Variability – Oura Help](https://support.ouraring.com/hc/en-us/articles/360025441974-Heart-Rate-Variability)
- [Unlock Your Best Rest: How Oura Calculates Your Ideal Bedtime Window](https://ouraring.com/blog/ideal-bedtime/)
- [Bedtime Guidance – Oura Help](https://support.ouraring.com/hc/en-us/articles/360025445154-Bedtime-Guidance)
- [Sleep Score – Oura Help](https://support.ouraring.com/hc/en-us/articles/360025445574-Sleep-Score)
- [Your Oura Sleep Score & How To Interpret It](https://ouraring.com/blog/sleep-score/)
- [The Ultimate Guide to Improving Your Sleep With Oura](https://ouraring.com/blog/guide-to-better-sleep-with-oura/)

### Fitbit API情報

- [Fitbit Development: Sleep](https://dev.fitbit.com/build/reference/web-api/sleep/)
- [Fitbit Development: Get Sleep Log by Date Range](https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date-range/)

### 学術文献

- [Accuracy Assessment of Oura Ring Nocturnal Heart Rate and Heart Rate Variability](https://pmc.ncbi.nlm.nih.gov/articles/PMC8808342/)
- [The Sleep of the Ring: Comparison Against Polysomnography](https://pmc.ncbi.nlm.nih.gov/articles/PMC6095823/)
- [Validity and reliability of the Oura Ring Generation 3](https://www.sciencedirect.com/science/article/pii/S1389945724000200)

---

## 付録: 実装例コード

### A. データ読み込みと前処理

```python
import pandas as pd
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / 'data' / 'fitbit'

def load_sleep_data():
    """睡眠データを読み込み"""
    sleep_df = pd.read_csv(DATA_DIR / 'sleep.csv')
    sleep_df['dateOfSleep'] = pd.to_datetime(sleep_df['dateOfSleep'])
    sleep_df = sleep_df.sort_values('dateOfSleep')
    return sleep_df

def load_hrv_data():
    """HRVデータを読み込み"""
    hrv_df = pd.read_csv(DATA_DIR / 'hrv.csv')
    hrv_df['date'] = pd.to_datetime(hrv_df['date'])
    return hrv_df
```

### B. 睡眠負債分析モジュール（フルコード例）

```python
"""
睡眠負債分析モジュール

Oura Ring風の睡眠負債機能をFitbitデータで実装
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class SleepDebtAnalyzer:
    """睡眠負債分析クラス"""

    def __init__(self, sleep_data):
        """
        Parameters:
            sleep_data (pd.DataFrame): 睡眠データ（dateOfSleep, minutesAsleepを含む）
        """
        self.sleep_data = sleep_data.copy()
        self.sleep_data['dateOfSleep'] = pd.to_datetime(self.sleep_data['dateOfSleep'])
        self.sleep_data = self.sleep_data.sort_values('dateOfSleep')

    def calculate_sleep_need(self, end_date=None, lookback_days=90):
        """
        個人の睡眠必要量を算出

        Parameters:
            end_date (datetime): 基準日（デフォルト: 最新日）
            lookback_days (int): 遡る日数（デフォルト: 90日）

        Returns:
            float: 睡眠必要量（分）
        """
        if end_date is None:
            end_date = self.sleep_data['dateOfSleep'].max()

        start_date = end_date - timedelta(days=lookback_days)

        # 期間内のデータを抽出
        period_data = self.sleep_data[
            (self.sleep_data['dateOfSleep'] >= start_date) &
            (self.sleep_data['dateOfSleep'] <= end_date)
        ]['minutesAsleep']

        if len(period_data) < 5:
            raise ValueError(f"睡眠必要量の算出には最低5夜分のデータが必要です（現在: {len(period_data)}夜）")

        # IQR法で外れ値を除外
        Q1 = period_data.quantile(0.25)
        Q3 = period_data.quantile(0.75)
        IQR = Q3 - Q1

        filtered_data = period_data[
            (period_data >= Q1 - 1.5 * IQR) &
            (period_data <= Q3 + 1.5 * IQR)
        ]

        # 中央値を睡眠必要量とする
        sleep_need = filtered_data.median()

        return sleep_need

    def calculate_sleep_debt(self, end_date=None, window_days=14):
        """
        睡眠負債を計算

        Parameters:
            end_date (datetime): 基準日（デフォルト: 最新日）
            window_days (int): 計算対象日数（デフォルト: 14日）

        Returns:
            dict: 睡眠負債情報
                - sleep_debt_hours (float): 睡眠負債（時間）
                - sleep_debt_category (str): カテゴリ
                - sleep_need_hours (float): 睡眠必要量（時間）
                - avg_sleep_hours (float): 平均睡眠時間（時間）
        """
        if end_date is None:
            end_date = self.sleep_data['dateOfSleep'].max()

        # 睡眠必要量を算出
        sleep_need_minutes = self.calculate_sleep_need(end_date)

        # 過去14日間のデータを取得
        start_date = end_date - timedelta(days=window_days - 1)
        window_data = self.sleep_data[
            (self.sleep_data['dateOfSleep'] >= start_date) &
            (self.sleep_data['dateOfSleep'] <= end_date)
        ].copy()

        if len(window_data) < 5:
            raise ValueError(f"睡眠負債の計算には最低5夜分のデータが必要です（現在: {len(window_data)}夜）")

        # 日ごとの負債を計算
        window_data['daily_deficit'] = sleep_need_minutes - window_data['minutesAsleep']

        # 最近の日により重みづけ（線形: 最古0.5 → 最新1.0）
        weights = np.linspace(0.5, 1.0, len(window_data))
        window_data['weight'] = weights

        # 重み付き平均負債
        weighted_deficit = (window_data['daily_deficit'] * window_data['weight']).sum() / window_data['weight'].sum()

        # 負の値（睡眠過剰）は0にクリップ
        total_debt_minutes = max(0, weighted_deficit)
        sleep_debt_hours = total_debt_minutes / 60

        # カテゴリ分類
        category = self._categorize_debt(sleep_debt_hours)

        # 平均睡眠時間
        avg_sleep_minutes = window_data['minutesAsleep'].mean()

        return {
            'sleep_debt_hours': round(sleep_debt_hours, 2),
            'sleep_debt_category': category,
            'sleep_need_hours': round(sleep_need_minutes / 60, 2),
            'avg_sleep_hours': round(avg_sleep_minutes / 60, 2),
            'data_points': len(window_data),
        }

    def _categorize_debt(self, sleep_debt_hours):
        """睡眠負債をカテゴリ分類"""
        if sleep_debt_hours == 0:
            return "None"
        elif sleep_debt_hours < 2:
            return "Low"
        elif sleep_debt_hours <= 5:
            return "Moderate"
        else:
            return "High"

    def get_debt_history(self, start_date, end_date):
        """
        期間内の睡眠負債履歴を取得

        Parameters:
            start_date (datetime): 開始日
            end_date (datetime): 終了日

        Returns:
            pd.DataFrame: 日ごとの睡眠負債データ
        """
        date_range = pd.date_range(start_date, end_date)
        history = []

        for date in date_range:
            try:
                result = self.calculate_sleep_debt(end_date=date)
                result['date'] = date
                history.append(result)
            except ValueError:
                # データ不足の場合はスキップ
                continue

        return pd.DataFrame(history)


# 使用例
if __name__ == "__main__":
    # データ読み込み
    sleep_df = pd.read_csv('data/fitbit/sleep.csv')

    # 分析器を初期化
    analyzer = SleepDebtAnalyzer(sleep_df)

    # 最新の睡眠負債を計算
    result = analyzer.calculate_sleep_debt()

    print(f"睡眠必要量: {result['sleep_need_hours']}時間")
    print(f"平均睡眠時間: {result['avg_sleep_hours']}時間")
    print(f"睡眠負債: {result['sleep_debt_hours']}時間 ({result['sleep_debt_category']})")
```

---

**作成者**: Claude Code
**最終更新**: 2026-01-01
