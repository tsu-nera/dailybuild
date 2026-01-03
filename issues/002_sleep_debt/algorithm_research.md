# 睡眠負債アルゴリズムの包括的調査

## 概要

睡眠負債機能の実装に向けて、学術研究、商用ウェアラブルデバイス、睡眠科学の観点から包括的に調査した結果をまとめる。

**調査日**: 2026-01-01
**目的**: 科学的根拠に基づいた睡眠負債実装アルゴリズムの設計

---

## 1. 睡眠科学の理論的基礎

### 1.1 二プロセスモデル（Two-Process Model）

睡眠調節の基本理論として、**二プロセスモデル**が広く受け入れられている。

#### プロセスS（ホメオスタティックプロセス）

**定義**: 睡眠圧（Sleep Pressure）の蓄積と解消を表す

- **覚醒中**: 睡眠圧が指数関数的に増加
- **睡眠中**: 睡眠圧が指数関数的に減少
- **数式モデル**:
  ```
  dS/dt = (1 / τ_wake) × (S_max - S)  # 覚醒時
  dS/dt = -(1 / τ_sleep) × S          # 睡眠時
  ```
  - τ_wake: 覚醒時の時定数（増加率）
  - τ_sleep: 睡眠時の時定数（減少率）
  - S_max: 最大睡眠圧

**睡眠負債との関係**: プロセスSは「睡眠負債」そのものと見なされる

#### プロセスC（サーカディアンプロセス）

**定義**: 概日リズムによる睡眠傾向の周期的変動

- 24時間周期で睡眠傾向が変化
- 睡眠圧（プロセスS）と相互作用し、実際の睡眠・覚醒を調節

#### 分子メカニズム

**アデノシン**: ホメオスタティック睡眠圧の分子的基盤

- 細胞のエネルギー消費に伴いアデノシンが蓄積
- アデノシン濃度が神経シグナルに変換され、睡眠圧を生成

### 1.2 睡眠負債の科学的定義

| 定義方法 | 説明 | 出典 |
|---------|------|------|
| **PSD方式** | PSD (Potential Sleep Debt) = OSD - HSD | Nature Scientific Reports, 2016 |
| | OSD: 最適睡眠時間 (Optimal Sleep Duration) | |
| | HSD: 習慣的睡眠時間 (Habitual Sleep Duration) | |
| **累積方式** | 日ごとの不足分を累積 | 多数の研究 |
| **重み付き方式** | 最近の不足により大きな重み | Oura, WHOOP, 他 |

### 1.3 睡眠負債の回復

#### 回復に必要な時間

| 睡眠負債 | 回復期間 | 研究結果 |
|---------|---------|---------|
| **1時間** | 3-4日間 | 平均3晩で回復 |
| **2時間** | 6-9日間 | 6晩で回復 |
| **慢性的制限（10日間）** | 7日間以上 | 1週間では不十分 |

#### 重要な知見

- **回復は単純な線形プロセスではない**
  - 気分、眠気、認知機能は異なる速度で回復
  - 回復睡眠の長さと回数に依存

- **週末の寝だめは限定的**
  - 眠気や疲労感は軽減できる
  - 代謝異常や体重増加のリスクは回復しない
  - 睡眠負債の完全な解消には不十分

- **タイプによる違い**
  - 急性睡眠不足 vs 慢性睡眠制限で回復動態が異なる

---

## 2. 商用デバイス・アプリの実装

### 2.1 Oura Ring

#### 計算方法

```
睡眠負債 = Σ(睡眠必要量 - 実際の睡眠時間) × 重み
```

| パラメータ | 値 | 詳細 |
|-----------|---|------|
| **計算期間** | 過去14日間 | 最低5夜分のデータが必要 |
| **基準値算出** | 過去90日間 | 外れ値除外後の個人パターン分析 |
| **重み付け** | 最近の日 > 古い日 | 直近の睡眠がより大きく影響 |

#### カテゴリ分類

| カテゴリ | 範囲 | 説明 |
|---------|------|------|
| None | 0時間 | 睡眠必要量を満たしている |
| Low | <2時間 | わずかな不足 |
| Moderate | 2-5時間 | 中程度の負債 |
| High | >5時間 | 大きな負債 |

#### 使用データ

- 総睡眠時間
- 睡眠ステージ（wake, light, deep, REM）
- HRV
- 心拍数
- 体温
- 動き

### 2.2 WHOOP

#### 計算方法

```
その日の睡眠必要量 = ベースライン + ストレイン + 睡眠負債 - 仮眠
```

| 要素 | 説明 |
|------|------|
| **ベースライン** | 個人の生理学的基礎睡眠必要量（WHOOPが学習） |
| **ストレイン** | 運動、ストレス、日常活動による身体負荷 |
| **睡眠負債** | 前日までの累積不足分 |
| **仮眠** | 日中の仮眠時間（その夜の必要量から減算） |

#### 特徴

- **動的調整**: 活動量に応じて必要量が変動
- **継続性**: 睡眠負債は数日間持続
- **回復予測**: Sleep Plannerが就寝時刻を提案

#### 回復の考え方

- 累積的な睡眠負債は数日〜数週間かけて回復
- 30分の仮眠で1時間の睡眠負債を半減可能

### 2.3 Garmin（Body Battery）

#### 計算方法

睡眠負債を直接算出する機能はなく、**Body Battery**で間接的に評価

```
Body Battery = f(HRV, ストレスレベル, 睡眠品質, 活動データ)
```

| 要素 | 役割 |
|------|------|
| **HRV** | 自律神経のバランスを評価 |
| **ストレス** | エネルギー消費を測定 |
| **睡眠** | エネルギー回復を測定 |
| **活動** | 身体的負荷を測定 |

#### アルゴリズム提供元

- **Firstbeat Analytics**（Garmin子会社、スポーツ科学企業）

#### 重要な知見

- 7時間以上睡眠する人は、Body Battery 80以上に達する確率が50%高い
- 一晩の睡眠不足は即座に低エネルギーにつながらない
- 5晩の睡眠不足が累積すると影響が顕著

### 2.4 Apple Watch（ネイティブアプリ）

#### 制限事項

**Apple Watchの標準Sleep appには睡眠負債機能なし**

提供される機能：
- 睡眠スコア
- 睡眠ステージ
- 過去14日間の平均睡眠時間

#### サードパーティアプリ

##### AutoSleep

```
睡眠負債 = 推奨睡眠時間 - 実際の睡眠時間
```

- 過去7日間のデータを使用
- 8時間未満を単純に悪とせず、個人パターンを考慮
- 睡眠効率と次の日の起床予測時刻から就寝時刻を提案

##### RISE App

```
重み付け: 昨夜 15% + 過去13夜 85%
```

- 最近の夜により重みづけ
- 睡眠負債とサーカディアンリズムの整合性を重視

---

## 3. 個人の睡眠必要量の算出

### 3.1 個人差の要因

| 要因 | 影響 | 範囲 |
|------|------|------|
| **年齢** | 若年層ほど長時間必要 | 成人: 7-9時間 |
| **遺伝** | 個人の基礎睡眠必要量 | ±1-2時間 |
| **活動量** | 高強度運動後は増加 | +0.5-2時間 |
| **ストレス** | 精神的負荷で増加 | +0.5-1時間 |
| **体調** | 病気や回復期で増加 | +1-3時間 |

### 3.2 算出手法の比較

#### 手法1: 統計的ベースライン（Oura, AutoSleep）

```python
# 過去90日間の中央値/平均
sleep_need = median(sleep_duration_90days[filtered])

# 外れ値除外（IQR法）
Q1, Q3 = quantile(data, [0.25, 0.75])
IQR = Q3 - Q1
filtered = data[(data >= Q1 - 1.5*IQR) & (data <= Q3 + 1.5*IQR)]
```

**長所**:
- 実装が容易
- 個人の実際のパターンを反映

**短所**:
- 慢性的に睡眠不足の人は低く見積もられる
- 90日間のデータが必要

#### 手法2: パフォーマンスベース（WHOOP）

```python
# 高パフォーマンス時の睡眠時間を学習
sleep_need = median(sleep_duration[high_recovery_days])
```

**長所**:
- より科学的に妥当
- 最適な睡眠時間を推定

**短所**:
- 回復指標（HRV、主観評価など）が必要
- データ収集期間が長い

#### 手法3: 活動量調整型（WHOOP, Garmin）

```python
# 基礎睡眠必要量 + 活動による追加分
sleep_need = baseline + strain_factor(activity_data)
```

**長所**:
- 日ごとの変動に対応
- より正確な必要量

**短所**:
- 活動量の定量化が必要
- 複雑な計算

### 3.3 2025年最新研究の知見

#### Sleep Variability（睡眠変動性）

**Scripps Research（2025年12月）**:
- 夜ごとの睡眠時間の変動が1時間異なるだけで：
  - 睡眠時無呼吸のリスク: 2倍以上
  - 高血圧のリスク: 71%増加

**示唆**: 睡眠の一貫性（regularity）も重要な指標

#### SONA理論（Sleep Opportunity, Need, Ability）

睡眠必要量を個人レベルで評価する理論的フレームワーク

| 要素 | 定義 |
|------|------|
| **Sleep Opportunity** | 睡眠の機会（環境、時間的制約） |
| **Sleep Need** | 生理学的睡眠必要量 |
| **Sleep Ability** | 実際に眠る能力（睡眠障害など） |

#### AI/機械学習アプローチ

- HRVと睡眠質の関係を人工ニューラルネットワークで予測
- 個人ごとにパーソナライズされた予測モデル構築

---

## 4. 実装アルゴリズムの設計指針

### 4.1 推奨アプローチの比較

| アプローチ | 複雑度 | 精度 | データ要件 | 推奨度 |
|-----------|--------|------|-----------|--------|
| **統計的ベースライン** | 低 | 中 | 睡眠時間のみ | ⭐⭐⭐⭐⭐ MVP向き |
| **パフォーマンスベース** | 中 | 高 | HRV + 主観評価 | ⭐⭐⭐⭐ フェーズ2 |
| **活動量調整型** | 高 | 最高 | 活動量 + HRV | ⭐⭐⭐ フェーズ3 |
| **二プロセスモデル** | 最高 | 理論的 | 高頻度データ | ⭐⭐ 研究用 |

### 4.2 MVP（最小実用製品）の推奨設計

#### ステップ1: 個人の睡眠必要量算出

```python
def calculate_sleep_need(sleep_history_90days):
    """
    Oura/AutoSleep方式: 統計的ベースライン

    Args:
        sleep_history_90days: 過去90日間の睡眠時間（分）

    Returns:
        sleep_need: 個人の睡眠必要量（分）
    """
    # 外れ値除外（IQR法）
    Q1 = percentile(sleep_history_90days, 25)
    Q3 = percentile(sleep_history_90days, 75)
    IQR = Q3 - Q1

    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR

    filtered_data = sleep_history_90days[
        (sleep_history_90days >= lower_bound) &
        (sleep_history_90days <= upper_bound)
    ]

    # 中央値を使用（外れ値に頑健）
    sleep_need = median(filtered_data)

    # サニティチェック: 成人の一般的範囲（6-10時間）
    sleep_need = clip(sleep_need, min=360, max=600)

    return sleep_need
```

#### ステップ2: 睡眠負債の計算

```python
def calculate_sleep_debt(sleep_history_14days, sleep_need):
    """
    重み付き累積方式（Oura/RISE方式）

    Args:
        sleep_history_14days: 過去14日間の睡眠時間（分）
        sleep_need: 個人の睡眠必要量（分）

    Returns:
        sleep_debt_info: {
            'total_debt_hours': 総睡眠負債（時間）,
            'category': カテゴリ,
            'daily_deficits': 日ごとの不足分
        }
    """
    # 最低データ要件チェック
    if len(sleep_history_14days) < 5:
        raise ValueError("最低5夜分のデータが必要")

    # 日ごとの負債計算
    daily_deficits = sleep_need - sleep_history_14days['minutes_asleep']

    # 重み付け（線形: 最古の日 0.5 → 最新の日 1.0）
    n = len(daily_deficits)
    weights = linspace(0.5, 1.0, n)

    # 重み付き平均
    weighted_avg_deficit = sum(daily_deficits * weights) / sum(weights)

    # 負の値（睡眠過剰）は0にクリップ
    total_debt_minutes = max(0, weighted_avg_deficit)
    total_debt_hours = total_debt_minutes / 60

    # カテゴリ分類
    if total_debt_hours == 0:
        category = "None"
    elif total_debt_hours < 2:
        category = "Low"
    elif total_debt_hours <= 5:
        category = "Moderate"
    else:
        category = "High"

    return {
        'total_debt_hours': round(total_debt_hours, 2),
        'category': category,
        'daily_deficits': daily_deficits.tolist(),
        'avg_deficit_per_night': round(total_debt_minutes / n, 1)
    }
```

#### ステップ3: 重み付け関数の選択肢

```python
# オプション1: 線形減衰（シンプル、Oura風）
weights_linear = linspace(0.5, 1.0, n)

# オプション2: 指数減衰（より急激に最近を重視）
decay_rate = 0.1
weights_exponential = exp(decay_rate * arange(n))
weights_exponential = weights_exponential / max(weights_exponential)  # 正規化

# オプション3: RISE方式（昨夜15%, 過去13夜85%）
weights_rise = [0.85/13] * 13 + [0.15]  # 14日間
```

### 4.3 拡張機能の設計

#### フェーズ2: HRVベースの睡眠質調整

```python
def calculate_quality_adjusted_debt(sleep_history, hrv_history, sleep_need):
    """
    HRVを考慮した質的調整

    低HRV日 → 睡眠の質が低い → 実効睡眠時間を減算
    """
    quality_factor = []

    for i, (sleep, hrv) in enumerate(zip(sleep_history, hrv_history)):
        # 個人のHRVベースラインと比較
        hrv_baseline = median(hrv_history)
        hrv_ratio = hrv / hrv_baseline

        # HRVが低い = 質が悪い = 実効時間減少
        # 例: HRVが80% → 睡眠時間を95%で計算
        quality_multiplier = 0.7 + 0.3 * min(hrv_ratio, 1.3)

        effective_sleep = sleep * quality_multiplier
        quality_factor.append(effective_sleep)

    # 質調整後の睡眠時間で負債計算
    return calculate_sleep_debt(quality_factor, sleep_need)
```

#### フェーズ3: 活動量による動的調整

```python
def calculate_dynamic_sleep_need(base_need, activity_data):
    """
    WHOOPストレイン方式: 活動に応じた必要量調整

    Args:
        base_need: 基礎睡眠必要量（分）
        activity_data: {
            'calories': 消費カロリー,
            'intensity_minutes': 高強度運動時間,
            'steps': 歩数
        }

    Returns:
        adjusted_need: 調整後の睡眠必要量（分）
    """
    # 活動ストレインスコア計算（0-21点、WHOOPを参考）
    strain_score = (
        activity_data['calories'] / 100 +  # 100kcalごとに1点
        activity_data['intensity_minutes'] / 10  # 10分ごとに1点
    )
    strain_score = min(strain_score, 21)  # 上限21

    # ストレインに応じた追加睡眠時間
    # 軽度（0-9）: +0分、中度（10-13）: +15分、高度（14-17）: +30分、極度（18-21）: +60分
    if strain_score < 10:
        additional_sleep = 0
    elif strain_score < 14:
        additional_sleep = 15
    elif strain_score < 18:
        additional_sleep = 30
    else:
        additional_sleep = 60

    adjusted_need = base_need + additional_sleep

    return adjusted_need
```

---

## 5. 実装上の重要な考慮事項

### 5.1 データ品質の管理

| 課題 | 対策 |
|------|------|
| **欠損データ** | 最低5夜/14日間のしきい値を設定 |
| **外れ値** | IQR法で除外、または中央値を使用 |
| **手動ログ** | 自動検出データと区別（信頼性が低い） |
| **短時間仮眠** | メインスリープと分けて扱う |

### 5.2 計算パラメータのチューニング

| パラメータ | 推奨値 | 調整の余地 |
|-----------|--------|-----------|
| **lookback期間** | 90日 | 60-120日 |
| **計算window** | 14日 | 7-21日 |
| **最低データ数** | 5夜 | 3-7夜 |
| **重みの範囲** | 0.5-1.0 | 0.3-1.0 |
| **外れ値係数** | 1.5×IQR | 1.0-2.0×IQR |

### 5.3 ユーザー体験の設計

#### 視覚化

```
睡眠負債: 2.3時間 (Moderate)

[■■■■■□□□□□] 50% - 回復まで4-6日必要

今週の推移:
月 ▼ -0.5h
火 ▼ -0.3h
水 ▲ +0.2h
木 ▼ -0.8h
金 ▼ -0.5h
土 ▲ +1.5h (回復中)
日 ▲ +0.5h (回復中)
```

#### 推奨メッセージ

| カテゴリ | メッセージ例 |
|---------|------------|
| **None** | "睡眠負債なし！理想的な睡眠習慣です" |
| **Low** | "わずかな睡眠負債。今夜は早めに就寝を" |
| **Moderate** | "睡眠負債が蓄積中。週末で回復を計画しましょう" |
| **High** | "深刻な睡眠負債。優先的に睡眠時間を確保してください" |

### 5.4 検証とテスト

#### 妥当性チェック

```python
def validate_sleep_debt_calculation(result):
    """計算結果の妥当性チェック"""
    assert 0 <= result['total_debt_hours'] <= 24, "負債は0-24時間の範囲"
    assert 6 <= result['sleep_need_hours'] <= 10, "睡眠必要量は6-10時間"
    assert result['category'] in ['None', 'Low', 'Moderate', 'High']

    # 論理的整合性
    if result['total_debt_hours'] == 0:
        assert result['category'] == 'None'
    if result['category'] == 'High':
        assert result['total_debt_hours'] > 5
```

#### ユニットテスト例

```python
def test_sleep_debt_calculation():
    # ケース1: 完璧な睡眠
    perfect_sleep = [480] * 14  # 8時間 × 14日
    result = calculate_sleep_debt(perfect_sleep, sleep_need=480)
    assert result['category'] == 'None'

    # ケース2: 一貫した不足
    insufficient_sleep = [360] * 14  # 6時間 × 14日
    result = calculate_sleep_debt(insufficient_sleep, sleep_need=480)
    assert result['category'] in ['Moderate', 'High']

    # ケース3: 最近の不足
    recent_deficit = [480] * 10 + [300] * 4  # 最後4日が不足
    result = calculate_sleep_debt(recent_deficit, sleep_need=480)
    # 最近の日に重みがあるため、負債が検出されるべき
    assert result['total_debt_hours'] > 0
```

---

## 6. 比較まとめ

### 6.1 各アプローチの特徴

| アプローチ | データ要件 | 計算複雑度 | 精度 | 個人化 | MVP適性 |
|-----------|-----------|-----------|------|--------|---------|
| **Oura方式** | 睡眠時間 | 低 | 中 | 高 | ⭐⭐⭐⭐⭐ |
| **WHOOP方式** | 睡眠+活動+HRV | 中 | 高 | 最高 | ⭐⭐⭐⭐ |
| **Garmin方式** | HRV+ストレス | 中 | 中-高 | 高 | ⭐⭐⭐ |
| **二プロセスモデル** | 高頻度データ | 最高 | 理論的 | 中 | ⭐ |
| **統計ベースライン** | 睡眠時間のみ | 最低 | 中 | 中 | ⭐⭐⭐⭐⭐ |

### 6.2 Fitbitデータでの実装可能性

| 手法 | Fitbitデータでの実装 | 評価 |
|------|---------------------|------|
| **Oura方式** | ✅ 完全実装可能 | 推奨 |
| **WHOOP方式（基本）** | ✅ 実装可能 | 推奨（フェーズ2） |
| **WHOOP方式（完全）** | ⚠️ ストレインスコア要開発 | 可能（フェーズ3） |
| **Garmin方式** | ✅ HRVデータで実装可能 | 可能（代替アプローチ） |
| **AutoSleep方式** | ✅ 完全実装可能 | シンプル版として有用 |

---

## 7. 最終推奨事項

### 7.1 推奨実装ロードマップ

#### フェーズ1: MVP（2-3週間）

**目標**: 基本的な睡眠負債機能を実装

**実装内容**:
- Oura方式の統計的ベースライン算出
- 重み付き累積方式の睡眠負債計算
- 4段階カテゴリ分類
- シンプルな可視化

**技術スタック**:
```python
# 必要データ
- sleep.csv (minutesAsleep)
- 過去90日間の履歴

# 推奨アルゴリズム
- 睡眠必要量: IQR除外 + 中央値
- 負債計算: 線形重み付け（0.5-1.0）
- カテゴリ: Ouraの4段階
```

**成功基準**:
- [ ] 個人の睡眠必要量が6-10時間の妥当な範囲
- [ ] 睡眠不足時に負債が増加
- [ ] 十分な睡眠で負債が減少

#### フェーズ2: 質的評価（1-2ヶ月後）

**目標**: HRVを活用した睡眠の質的評価

**実装内容**:
- HRVベースの睡眠質調整
- 深い睡眠とHRVの相関分析
- 質調整後の負債計算

**追加データ**:
```python
- hrv.csv (daily_rmssd, deep_rmssd)
- sleep_levels.csv (deep/light/rem)
```

**成功基準**:
- [ ] HRV低下時に実効睡眠時間が減算
- [ ] 深い睡眠割合との相関確認

#### フェーズ3: 動的調整（3-6ヶ月後）

**目標**: 活動量に応じた睡眠必要量の動的調整

**実装内容**:
- WHOOPストレイン風のスコア算出
- 活動量に基づく必要量調整
- 週ごとのパターン分析

**追加データ**:
```python
- activity.csv (calories, steps)
- activity_logs.csv (運動ログ)
```

### 7.2 重要な設計原則

1. **段階的実装**: シンプルなMVPから開始
2. **データ駆動**: 仮定ではなく実データで検証
3. **個人化**: 集団平均ではなく個人パターンを尊重
4. **科学的根拠**: 学術研究とデバイス実装の両方を参考
5. **ユーザー価値**: 数値だけでなく実用的な推奨を提供

### 7.3 次のアクションアイテム

- [ ] MVP実装: `src/lib/analytics/sleep_debt.py` を作成
- [ ] データ分析: 既存の睡眠データで睡眠必要量の分布を確認
- [ ] 妥当性検証: 主観的な疲労感と睡眠負債の相関を記録
- [ ] レポート統合: 睡眠レポートに睡眠負債セクションを追加
- [ ] 可視化: グラフとトレンドの実装

---

## 8. 参考文献

### 学術論文

- [Estimating individual optimal sleep duration and potential sleep debt | Scientific Reports](https://www.nature.com/articles/srep35812)
- [Estimating individual optimal sleep duration and potential sleep debt - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5075948/)
- [A unified mathematical model to quantify performance impairment for both chronic sleep restriction and total sleep deprivation](https://www.sciencedirect.com/science/article/pii/S0022519313001811)
- [Dynamics of recovery sleep from chronic sleep restriction - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10108639/)
- [The two‐process model of sleep regulation: Beginnings and outlook - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC9540767/)
- [The complexity and commonness of the two-process model of sleep regulation](https://www.nature.com/articles/s44323-025-00039-z)
- [A new mathematical model for the homeostatic effects of sleep loss](https://pmc.ncbi.nlm.nih.gov/articles/PMC2657297/)

### 2025年最新研究

- [Scripps Research: Sleep variability linked with sleep apnea and hypertension](https://www.scripps.edu/news-and-events/press-room/2025/20251223-jaiswal-sleep.html)
- [The Sleep Opportunity, Need and Ability (SONA) Theory - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC12592830/)
- [Predicting sleep quality with digital biomarkers and artificial neural networks](https://www.frontiersin.org/journals/psychiatry/articles/10.3389/fpsyt.2025.1591448/full)
- [Identification of five sleep-biopsychosocial profiles](https://journals.plos.org/plosbiology/article?id=10.1371/journal.pbio.3003399)

### 商用デバイス・アプリ

- [Sleep Debt Calculator](https://www.omnicalculator.com/health/sleep-debt)
- [How Much Sleep Debt Do I Have? RISE App](https://www.risescience.com/blog/how-much-sleep-debt-do-i-have)
- [AutoSleep - Overview](https://autosleepapp.tantsissa.com/home/overview)
- [What is Sleep Debt? WHOOP](https://www.whoop.com/us/en/thelocker/what-is-sleep-debt-catch-up/)
- [Understanding Sleep Debt: Impact on Performance and Recovery | WHOOP](https://www.whoop.com/us/en/thelocker/understanding-sleep-debt-impact-on-performance-and-recovery/)
- [How Much Sleep Do I Need? | Sleep Planner | WHOOP](https://www.whoop.com/us/en/thelocker/how-much-sleep-do-i-need/)
- [How Does Garmin Measure Body Battery?](https://www.slashgear.com/1989498/how-does-garmin-measure-body-battery/)
- [Garmin Body Battery: Is it useful for health and fitness?](https://www.androidauthority.com/garmin-body-battery-1209128/)

### 睡眠負債の回復

- [Sleep Debt: The Hidden Cost of Insufficient Rest](https://www.sleepfoundation.org/how-sleep-works/sleep-debt-and-catch-up-sleep)
- [Yes, You Can Catch Up on Sleep. A Sleep Expert Explains How](https://www.risescience.com/blog/can-you-catch-up-on-sleep)
- [How Long Does it Take to Recover From Sleep Deprivation?](https://www.risescience.com/blog/how-long-does-it-take-to-recover-from-sleep-deprivation)

### ツール・実装例

- [GitHub - neuroccm/sleepbetter: A command-line sleep tracking tool](https://github.com/neuroccm/sleepbetter)
- [Alternate approaches to calculating sleep debt | ResearchGate](https://www.researchgate.net/figure/Alternate-approaches-to-calculating-sleep-debt-Different-ways-of-calculating-sleep-debt_fig2_345007261)

---

**作成者**: Claude Code
**最終更新**: 2026-01-01
