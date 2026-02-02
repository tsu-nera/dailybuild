# 血糖値スコアの科学的定式化

**作成日**: 2026-02-02

---

## 🔬 既存研究のスコア・予測式

### 1. グリセミック負荷（GL）予測モデル【2021年研究】

**出典**: [Development of a Prediction Model to Estimate the Glycemic Load of Ready-to-Eat Meals (2021)](https://www.mdpi.com/2304-8158/10/11/2626)

**予測式**:
```
GL = 19.27 + (0.39 × AC) - (0.21 × Fat) - (0.01 × Protein²) - (0.01 × Fiber²)
```

**変数**:
- `AC` (Available Carbohydrate): 利用可能炭水化物 = 総炭水化物 - 食物繊維
- `Fat`: 脂質 (g)
- `Protein`: タンパク質 (g)
- `Fiber`: 食物繊維 (g)

**特徴**:
- ✅ タンパク質と食物繊維は**二次項**（²）で負の効果
- ✅ 脂質は**線形**で負の効果
- ✅ 利用可能炭水化物は**線形**で正の効果

**検証結果**:
- R² = 0.82（非常に高い予測精度）
- 炭水化物と正の相関、脂質・タンパク質・食物繊維と負の相関

---

### 2. タンパク質・脂質の効果量【2006年研究】

**出典**: [The Effects of Fat and Protein on Glycemic Responses (2006)](https://pubmed.ncbi.nlm.nih.gov/16988118/)

**主要な発見**:
- **タンパク質**: 0-30gの範囲で用量依存的に血糖反応を低下
- **脂質**: 0-30gの範囲で用量依存的に血糖反応を低下
- **タンパク質の効果は脂質の約3倍**

**追加知見**:
- 50gのタンパク質追加 → グルコースAUC、GI、GLすべて低下
- タンパク質はアミノ酸を介してインスリン分泌を刺激
- 脂質は血糖値上昇を抑えるが、インスリン濃度は変化させない

---

### 3. 混合食の血糖反応【2019年研究】

**出典**: [Effect of nutrient composition in a mixed meal on postprandial glycemic response (2019)](https://pubmed.ncbi.nlm.nih.gov/30984356/)

**発見**:
- 混合食（米 + 卵 + 油 + もやし） < 米のみ
- 脂質、タンパク質、食物繊維を含む混合食 → 初期ピークが低く、回復が遅い
- **実際の血糖値測定で検証済み**

---

### 4. 機械学習による予測【2025年研究】

**出典**: [Predicting Postprandial Glycemic Responses With Limited Data (2025)](https://journals.sagepub.com/doi/10.1177/19322968251321508)

**発見**:
- マクロ栄養素だけで **R = 0.61-0.72** の予測精度
- 食品カテゴリを追加すると精度向上
- 侵襲的データ（腸内細菌叢など）なしでも高精度

---

## ✅ 推奨する定式化

### 方法A: 研究ベースのGL予測式【最も科学的】

2021年の研究式をそのまま使用：

```python
def calc_predicted_glycemic_load(carbs, fiber, protein, fat):
    """
    研究ベースのGL予測式

    出典: Pongutta et al. (2021)
    Foods 10(11), 2626
    """
    # 利用可能炭水化物
    available_carbs = max(0, carbs - fiber)

    # 予測GL
    gl = (19.27 +
          0.39 * available_carbs -
          0.21 * fat -
          0.01 * (protein ** 2) -
          0.01 * (fiber ** 2))

    return max(0, gl)  # 負の値は0に
```

**GLの解釈**:
- **低 (< 10)**: 血糖値への影響が小さい
- **中 (10-20)**: 中程度の血糖値上昇
- **高 (> 20)**: 大きな血糖値上昇

---

### 方法B: タンパク質効果を強調した修正版【推奨】

タンパク質の効果が脂質の3倍という知見を反映：

```python
def calc_glycemic_impact_score_v2(carbs, fiber, protein, fat):
    """
    タンパク質効果を強調したGISv2

    - タンパク質の効果 = 脂質の3倍
    - 食物繊維の効果も強調
    """
    # 正味炭水化物
    net_carbs = max(0, carbs - fiber)

    # タンパク質の低減効果（非線形、飽和効果あり）
    # 30gまで効果的、それ以上は飽和
    protein_effect = min(protein / 30.0, 1.0) * 0.4  # 最大40%減

    # 脂質の低減効果（タンパク質の1/3）
    fat_effect = min(fat / 30.0, 1.0) * 0.13  # 最大13%減

    # 食物繊維の追加低減効果（炭水化物から既に引かれているが追加効果）
    fiber_effect = min(fiber / 25.0, 1.0) * 0.15  # 最大15%減

    # 修正係数
    modifier = max(0.1, 1.0 - protein_effect - fat_effect - fiber_effect)

    # GIS
    gis = net_carbs * modifier

    return gis
```

**GISの解釈**:
- **低 (< 50)**: 血糖値安定 → 良好な睡眠が期待
- **中 (50-100)**: 中程度の血糖変動
- **高 (> 100)**: 血糖スパイクのリスク → 睡眠の質低下の可能性

---

### 方法C: シンプル版【理解しやすい】

わかりやすさを重視したシンプルな式：

```python
def calc_simple_glycemic_score(carbs, fiber, protein, fat):
    """
    シンプルな血糖値スコア

    正味炭水化物から、他の栄養素の効果を引く
    """
    # 正味炭水化物（基準値）
    net_carbs = max(0, carbs - fiber)

    # 各栄養素の低減ポイント
    protein_reduction = protein * 0.5  # タンパク質1gあたり0.5ポイント減
    fat_reduction = fat * 0.17  # 脂質1gあたり0.17ポイント減（タンパク質の1/3）
    fiber_bonus = fiber * 0.3  # 食物繊維の追加効果

    # スコア計算
    score = net_carbs - protein_reduction - fat_reduction - fiber_bonus

    return max(0, score)
```

---

## 📊 3つの方法の比較

| 方法 | 科学的根拠 | 精度 | 実装の容易性 | 解釈性 |
|------|-----------|------|--------------|--------|
| A: 研究ベースGL | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ (R²=0.82) | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| B: 修正GIS | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| C: シンプル版 | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 💡 最終推奨

### 優先度1: 方法A（研究ベースのGL予測式）

**理由**:
1. ✅ 査読論文で検証済み（R² = 0.82）
2. ✅ 実際の血糖値測定データで構築
3. ✅ タンパク質・食物繊維の非線形効果を反映
4. ✅ 国際的に認知されている指標（GL）

**使用時の注意**:
- GLの基準値は既存のGI/GL研究と比較可能
- 食事1回あたりのGLとして評価
- 1日の合計GLも計算可能

### 優先度2: 方法Bも並行実装

**理由**:
- タンパク質の効果を強調（睡眠研究との整合性）
- より直感的な0-150のスケール
- 方法Aとの相関を検証できる

---

## 🔬 実装例

### 完全な実装コード

```python
import numpy as np
import pandas as pd

def calc_predicted_gl(carbs, fiber, protein, fat):
    """
    研究ベースのGL予測式 (Pongutta et al., 2021)

    Parameters
    ----------
    carbs : float
        炭水化物 (g)
    fiber : float
        食物繊維 (g)
    protein : float
        タンパク質 (g)
    fat : float
        脂質 (g)

    Returns
    -------
    float
        予測グリセミック負荷
    """
    available_carbs = max(0, carbs - fiber)
    gl = (19.27 +
          0.39 * available_carbs -
          0.21 * fat -
          0.01 * (protein ** 2) -
          0.01 * (fiber ** 2))
    return max(0, gl)


def calc_gis_v2(carbs, fiber, protein, fat):
    """
    修正GISv2（タンパク質効果強調版）
    """
    net_carbs = max(0, carbs - fiber)

    # 飽和効果を持つ非線形関数
    protein_effect = min(protein / 30.0, 1.0) * 0.4
    fat_effect = min(fat / 30.0, 1.0) * 0.13
    fiber_effect = min(fiber / 25.0, 1.0) * 0.15

    modifier = max(0.1, 1.0 - protein_effect - fat_effect - fiber_effect)
    gis = net_carbs * modifier

    return gis


def categorize_score(score, method='gl'):
    """
    スコアをカテゴリに分類

    Parameters
    ----------
    score : float
        スコア値
    method : str
        'gl' または 'gis'

    Returns
    -------
    str
        カテゴリラベル
    """
    if method == 'gl':
        if score < 10:
            return "低"
        elif score < 20:
            return "中"
        else:
            return "高"
    else:  # gis
        if score < 50:
            return "低"
        elif score < 100:
            return "中"
        else:
            return "高"


def analyze_glycemic_scores(df):
    """
    データフレームに両方のスコアを追加して分析

    Parameters
    ----------
    df : pd.DataFrame
        carbs, fiber, protein, fatを含むデータフレーム

    Returns
    -------
    pd.DataFrame
        スコアが追加されたデータフレーム
    """
    # GL計算
    df['predicted_gl'] = df.apply(
        lambda row: calc_predicted_gl(
            row['carbs'], row['fiber'],
            row['protein'], row['fat']
        ), axis=1
    )

    # GISv2計算
    df['gis_v2'] = df.apply(
        lambda row: calc_gis_v2(
            row['carbs'], row['fiber'],
            row['protein'], row['fat']
        ), axis=1
    )

    # カテゴリ分類
    df['gl_category'] = df['predicted_gl'].apply(
        lambda x: categorize_score(x, 'gl')
    )
    df['gis_category'] = df['gis_v2'].apply(
        lambda x: categorize_score(x, 'gis')
    )

    return df


# 使用例
def main():
    # データ読み込み
    df_nutrition = pd.read_csv('data/fitbit/nutrition.csv')
    df_nutrition = df_nutrition[df_nutrition['calories'] > 0].copy()

    # スコア計算
    df_nutrition = analyze_glycemic_scores(df_nutrition)

    # 統計表示
    print("=== Predicted GL Statistics ===")
    print(df_nutrition['predicted_gl'].describe())
    print(f"\nGL Categories:")
    print(df_nutrition['gl_category'].value_counts())

    print("\n=== GIS v2 Statistics ===")
    print(df_nutrition['gis_v2'].describe())
    print(f"\nGIS Categories:")
    print(df_nutrition['gis_category'].value_counts())

    # 相関分析（GLとGISv2の比較）
    correlation = df_nutrition[['predicted_gl', 'gis_v2']].corr()
    print(f"\nCorrelation between GL and GIS: {correlation.iloc[0, 1]:.3f}")

    return df_nutrition


if __name__ == '__main__':
    df_result = main()
```

---

## 📈 検証方法

### 1. スコア間の相関確認

```python
# 2つの方法の相関を確認
correlation = df[['predicted_gl', 'gis_v2']].corr()
print(f"Correlation: {correlation.iloc[0, 1]:.3f}")

# 期待: r > 0.90（非常に高い相関）
```

### 2. 睡眠指標との相関

```python
# 睡眠データとマージ
df_merged = merge_sleep_data(df)

# 相関分析
sleep_correlations = df_merged[[
    'predicted_gl', 'gis_v2',
    'sleep_minutes', 'deep_minutes',
    'sleep_efficiency', 'dip_rate'
]].corr()

print(sleep_correlations.loc[
    ['predicted_gl', 'gis_v2'],
    ['sleep_minutes', 'deep_minutes', 'sleep_efficiency', 'dip_rate']
])
```

### 3. カテゴリ別の睡眠比較

```python
# GL別の睡眠統計
category_stats = df_merged.groupby('gl_category')[
    ['sleep_minutes', 'deep_minutes', 'sleep_efficiency', 'dip_rate']
].agg(['mean', 'count'])

print(category_stats)
```

---

## 🎯 期待される結果

### 仮説

1. **低GL/GIS → 良好な睡眠**
   - 深い睡眠 ↑
   - 睡眠効率 ↑
   - ディップ率 ↑

2. **高GL/GIS → 睡眠の質低下**
   - 浅い睡眠 ↑
   - 覚醒回数 ↑
   - ディップ率 ↓

3. **GLとGISv2は高い相関（r > 0.90）**
   - 両方のスコアが同じ傾向を示す

4. **既存の発見との整合性**
   - 食物繊維が多い → GL/GIS低い → 睡眠良好
   - タンパク質が多い → GL/GIS低い → ディップ率高い

---

## 📚 参考文献

### スコア開発の基礎論文

1. [Development of a Prediction Model to Estimate the Glycemic Load of Ready-to-Eat Meals (2021)](https://www.mdpi.com/2304-8158/10/11/2626)
   - GL予測式の開発（R² = 0.82）
   - タンパク質・脂質・食物繊維の効果を定量化

2. [The Effects of Fat and Protein on Glycemic Responses (2006)](https://pubmed.ncbi.nlm.nih.gov/16988118/)
   - タンパク質の効果は脂質の3倍
   - 用量依存的効果を実証

3. [Effect of macronutrients and fiber on postprandial glycemic responses (2017)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5366046/)
   - マクロ栄養素の相互作用
   - 混合食の血糖反応

### 最新の機械学習アプローチ

4. [Predicting Postprandial Glycemic Responses With Limited Data (2025)](https://journals.sagepub.com/doi/10.1177/19322968251321508)
   - マクロ栄養素だけで高精度予測（R = 0.61-0.72）
   - 限られたデータでの実用性を実証

5. [Effect of nutrient composition in a mixed meal (2019)](https://pubmed.ncbi.nlm.nih.gov/30984356/)
   - 混合食の実測データ
   - 米+卵+油+もやし vs 米のみ

---

## 💬 結論

### 推奨される実装方針

1. **方法A（研究ベースGL）を主として実装** ✅
   - 最も科学的根拠が強い
   - 国際的に認知されている指標
   - 他の研究と比較可能

2. **方法B（GISv2）も並行実装**
   - タンパク質効果を強調
   - 睡眠研究の発見と整合的
   - より直感的なスケール

3. **両方のスコアを比較検証**
   - 相関係数を確認（r > 0.90を期待）
   - 睡眠指標との関係を両方で分析
   - どちらがより睡眠を予測するか評価

---

*Generated: 2026-02-02*
