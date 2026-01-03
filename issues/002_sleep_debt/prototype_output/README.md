# 睡眠負債プロトタイプ - 実行結果

## 概要

Oura Ring方式の睡眠負債算出アルゴリズムをFitbitデータで実装したプロトタイプの実行結果。

**実行日**: 2026-01-01
**データ期間**: 2025-12-03 ~ 2026-01-01（30日間）
**データ点数**: 30夜分

---

## 分析結果サマリー

### 個人の睡眠必要量

- **6.3時間**（376分）
- 過去90日間のデータから算出（外れ値除外後の中央値）
- 一般的な成人の範囲（6-10時間）内で妥当

### 現在の睡眠負債（2026-01-01時点）

| 項目 | 値 |
|------|------|
| 睡眠必要量 | 6.3時間 |
| 平均睡眠時間 | 6.5時間 |
| **睡眠負債** | **0.0時間** |
| カテゴリ | **None（理想的）** |
| 回復予測 | 0日 |

✅ **ステータス**: 睡眠負債なし！理想的な睡眠習慣です。

### 過去30日間のトレンド

#### 統計

- 平均睡眠負債: 0.01時間
- 最大睡眠負債: 0.16時間
- 最小睡眠負債: 0.00時間

#### カテゴリ分布

| カテゴリ | 日数 | 割合 | 説明 |
|---------|------|------|------|
| **None** | 25日 | 83.3% | 睡眠負債なし |
| **Low** | 5日 | 16.7% | わずかな負債（<2h） |
| **Moderate** | 0日 | 0.0% | 中程度の負債（2-5h） |
| **High** | 0日 | 0.0% | 深刻な負債（>5h） |

**評価**: 過去30日間、ほぼ一貫して睡眠必要量を満たしている優秀な睡眠習慣。

---

## 重み付け方法の比較

Oura、WHOOP、RISEなど異なる重み付け方法を比較：

| 方法 | 睡眠負債 | カテゴリ | 説明 |
|------|---------|---------|------|
| **Linear** | 0.00h | None | 線形減衰（0.5-1.0）Oura方式 |
| **Exponential** | 0.00h | None | 指数減衰（最近をより重視） |
| **RISE** | 0.00h | None | 昨夜15%、過去13夜85% |

**結果**: 現在の睡眠習慣が良好なため、どの方法でも負債はほぼ0。

---

## 生成ファイル

### 1. sleep_debt_trend.png

睡眠時間と睡眠負債のトレンドグラフ：
- 上段: 睡眠必要量 vs 実際の睡眠時間
- 下段: 睡眠負債の推移（カテゴリ別色分け）

### 2. sleep_debt_summary.png

睡眠負債のサマリーダッシュボード：
- 左: ゲージチャート（負債レベル）
- 右: 日次の不足/過剰バーチャート

### 3. sleep_debt_history.csv

過去30日間の詳細データ：
- date: 日付
- sleep_need_hours: 睡眠必要量
- avg_sleep_hours: 平均睡眠時間（14日移動平均）
- sleep_debt_hours: 睡眠負債
- category: カテゴリ
- recovery_days: 推定回復日数

---

## アルゴリズムの詳細

### ステップ1: 個人の睡眠必要量算出

```python
# 過去90日間のデータから外れ値を除外（IQR法）
Q1, Q3 = percentile(sleep_data, [25, 75])
IQR = Q3 - Q1
filtered = sleep_data[(data >= Q1-1.5*IQR) & (data <= Q3+1.5*IQR)]

# 中央値を睡眠必要量とする（外れ値に頑健）
sleep_need = median(filtered)

# 妥当性チェック: 6-10時間の範囲
sleep_need = clip(sleep_need, 360, 600)  # 分単位
```

### ステップ2: 睡眠負債計算

```python
# 過去14日間の日ごとの不足分を計算
daily_deficits = sleep_need - actual_sleep

# 重み付け（線形: 最古の日 0.5 → 最新の日 1.0）
weights = linspace(0.5, 1.0, 14)

# 重み付き平均
weighted_deficit = sum(daily_deficits * weights) / sum(weights)

# 負の値（睡眠過剰）は0にクリップ
sleep_debt = max(0, weighted_deficit)
```

### ステップ3: カテゴリ分類

| 睡眠負債 | カテゴリ |
|---------|---------|
| 0時間 | None |
| <2時間 | Low |
| 2-5時間 | Moderate |
| >5時間 | High |

### ステップ4: 回復日数推定

```python
# 研究ベース: 1時間の睡眠負債 = 3-4日で回復
# 保守的に1日あたり0.3時間の回復と仮定
recovery_days = ceil(sleep_debt / 0.3)
```

---

## 実装の特徴

### ✅ 実装済み機能

1. **統計的ベースライン算出**
   - 過去90日間のパターン分析
   - IQR法による外れ値除外
   - 中央値/平均の選択可能

2. **重み付き累積負債計算**
   - 線形、指数、RISE方式をサポート
   - 最近の日をより重視

3. **4段階カテゴリ分類**
   - Oura Ring方式の閾値

4. **回復日数予測**
   - 科学研究に基づく推定

5. **可視化**
   - トレンドグラフ
   - サマリーダッシュボード
   - CSV出力

### 📊 データ品質管理

- 最低データ数要件: 5夜分
- 妥当性チェック: 6-10時間範囲
- 外れ値除外: IQR法（1.5倍）

### 🔬 科学的根拠

- Oura Ring公式アルゴリズム
- Nature Scientific Reports研究
- 二プロセスモデル（睡眠科学）
- WHOOP、Garminの実装参考

---

## 今後の拡張案

### フェーズ2: 質的評価（1-2ヶ月後）

- [ ] HRVベースの睡眠質調整
- [ ] 深い睡眠割合の考慮
- [ ] 睡眠効率との統合

### フェーズ3: 動的調整（3-6ヶ月後）

- [ ] 活動量に基づく睡眠必要量調整（WHOOPストレイン方式）
- [ ] 週ごとのパターン分析
- [ ] 季節変動の考慮

### レポート統合

- [ ] 睡眠レポートに睡眠負債セクション追加
- [ ] 週次/月次サマリー
- [ ] アクションアイテム生成

---

## 実行方法

```bash
# venv環境で実行
source .venv/bin/activate
python scripts/test_sleep_debt.py
```

---

## 参考資料

- [Oura Ring Sleep Debt](https://ouraring.com/blog/sleep-debt/)
- [Scientific Reports: Sleep Debt](https://www.nature.com/articles/srep35812)
- [WHOOP Sleep Guidance](https://www.whoop.com/us/en/thelocker/what-is-sleep-debt-catch-up/)
- [Sleep Foundation: Sleep Debt](https://www.sleepfoundation.org/how-sleep-works/sleep-debt-and-catch-up-sleep)

---

**作成者**: Claude Code
**最終更新**: 2026-01-01
