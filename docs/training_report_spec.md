# 筋トレレポート データ仕様

筋トレ・ボディメイクの効果を追跡するためのデータ仕様。

---

## データソース一覧

| カテゴリ | データソース | 取得方法 | 実装状況 |
|----------|--------------|----------|----------|
| 体組成 | HealthPlanet | API | ✅ 実装済み |
| 活動・消費 | Fitbit | API | 🔧 一部実装 |
| 睡眠 | Fitbit | API | ✅ 実装済み |
| 栄養 | 手動 or アプリ | CSV | ⬜ 未実装 |
| 筋トレ | 手動 | CSV | ⬜ 未実装 |
| 有酸素運動 | Fitbit / 手動 | API / CSV | ⬜ 未実装 |

---

## 1. 体組成（HealthPlanet）

**ソース**: `data/healthplanet_innerscan.csv`

| カラム名 | 説明 | 単位 |
|----------|------|------|
| date | 計測日 | YYYY-MM-DD |
| weight | 体重 | kg |
| muscle_mass | 筋肉量 | kg |
| body_fat_rate | 体脂肪率 | % |
| body_fat_mass | 体脂肪量 | kg |
| visceral_fat_level | 内臓脂肪レベル | - |
| basal_metabolic_rate | 基礎代謝量 | kcal |
| bone_mass | 推定骨量 | kg |
| body_age | 体内年齢 | 歳 |
| body_water_rate | 体水分率 | % |
| muscle_quality_score | 筋質点数 | - |

**派生指標**:
| 指標 | 計算式 | 用途 |
|------|--------|------|
| 除脂肪体重 (LBM) | 体重 − 体脂肪量 | 筋トレ効果の指標 |

---

## 2. 栄養

**ソース**: `data/nutrition.csv`（手動入力 or アプリ連携）

| カラム名 | 説明 | 単位 | 必須 |
|----------|------|------|------|
| date | 日付 | YYYY-MM-DD | ✅ |
| calories | 摂取カロリー | kcal | ✅ |
| protein | タンパク質 | g | ✅ |
| carbs | 炭水化物 | g | - |
| fat | 脂質 | g | - |
| note | メモ | text | - |

**目標値の目安**:
| 指標 | 目標 | 備考 |
|------|------|------|
| タンパク質 | 体重 × 1.5〜2.0g | 筋肥大期は2.0g |
| カロリー | 基礎代謝 × 1.5〜1.7 | 増量期/減量期で調整 |

---

## 3. 筋トレ

**ソース**: `data/workout.csv`（手動入力）

| カラム名 | 説明 | 単位 | 必須 |
|----------|------|------|------|
| date | 日付 | YYYY-MM-DD | ✅ |
| muscle_group | 部位 | text | ✅ |
| exercise | 種目名 | text | ✅ |
| weight | 重量 | kg | ✅ |
| reps | 回数 | 回 | ✅ |
| sets | セット数 | セット | ✅ |
| rpe | きつさ (1-10) | - | - |
| note | メモ | text | - |

**部位の分類**:
| muscle_group | 日本語 | 主な種目例 |
|--------------|--------|------------|
| chest | 胸 | ベンチプレス、チェストプレス |
| back | 背中 | ラットプルダウン、ローイング |
| shoulder | 肩 | ショルダープレス、サイドレイズ |
| arm | 腕 | アームカール、トライセプス |
| leg | 脚 | スクワット、レッグプレス |
| core | 腹/体幹 | アブマシン、プランク |

**派生指標**:
| 指標 | 計算式 | 用途 |
|------|--------|------|
| ボリューム | 重量 × 回数 × セット数 | トレーニング負荷の指標 |
| 週間ボリューム | 部位別の週合計 | 部位ごとの刺激量管理 |

---

## 4. 有酸素運動

**ソース**: `data/cardio.csv`（Fitbit API or 手動入力）

| カラム名 | 説明 | 単位 | 必須 |
|----------|------|------|------|
| date | 日付 | YYYY-MM-DD | ✅ |
| activity_type | 種類 | text | ✅ |
| duration | 時間 | 分 | ✅ |
| distance | 距離 | km | - |
| calories | 消費カロリー | kcal | - |
| avg_hr | 平均心拍数 | bpm | - |
| note | メモ | text | - |

**activity_type の分類**:
| 値 | 説明 |
|----|------|
| cycling | ロードバイク / サイクリング |
| treadmill | トレッドミル |
| walking | ウォーキング |
| running | ランニング |
| other | その他 |

---

## 5. 活動・消費（Fitbit）

**ソース**: Fitbit API（既存の `fitbit_api.py` を拡張）

| カラム名 | 説明 | 単位 |
|----------|------|------|
| date | 日付 | YYYY-MM-DD |
| calories_out | 総消費カロリー | kcal |
| calories_bmr | 基礎代謝 | kcal |
| calories_active | 活動消費カロリー | kcal |
| steps | 歩数 | 歩 |
| active_minutes | アクティブ時間 | 分 |
| sedentary_minutes | 座位時間 | 分 |

---

## 6. 睡眠・回復（Fitbit）

**ソース**: `data/fitbit/sleep.csv`

| カラム名 | 説明 | 単位 |
|----------|------|------|
| dateOfSleep | 日付 | YYYY-MM-DD |
| minutesAsleep | 睡眠時間 | 分 |
| efficiency | 睡眠効率 | % |
| deepMinutes | 深い睡眠 | 分 |
| remMinutes | レム睡眠 | 分 |

---

## レポート出力仕様

### 週次レポート

**出力先**: `reports/body/weekly/YYYY-WXX/REPORT.md`

**セクション構成**:
1. サマリー（体組成の変化）
2. 推移グラフ
3. 日別データ（全項目）
4. 栄養サマリー（実装後）
5. トレーニングサマリー（実装後）

---

## 実装優先度

| 優先度 | 機能 | 理由 |
|--------|------|------|
| 1 | 栄養記録 (CSV) | カロリー収支が筋肥大の基本 |
| 2 | 筋トレ記録 (CSV) | ボリューム管理が重要 |
| 3 | 有酸素運動 (Fitbit) | ロードバイクのデータ活用 |
| 4 | 活動データ (Fitbit) | 総消費カロリー把握 |
