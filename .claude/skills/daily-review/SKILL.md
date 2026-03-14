---
name: daily-review
description: データ取得→レポート生成→AIレビューを一括実行する日次レビュースキル
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# 日次レビュースキル

データ取得、レポート生成、AIレビューを3ステップで実行する。

## Step 1: データ取得

最新のFitbit・HealthPlanet・日出日入データを取得する。

```bash
cd /home/tsu-nera/repo/dailybuild
python scripts/generate_report.py body --fetch 2 --days 1
```

注意: `generate_report.py` の `--fetch` はデータ取得のみ行う。上記コマンドでデータ取得が実行される。レポート生成は次のステップで個別に行うため、この出力レポートは無視してよい。

## Step 2: レポート生成（3種類を個別実行）

レポートごとに適切な期間で生成する。出力先はデフォルトの `tmp/` を使用。

```bash
# 体組成レポート（直近7日）
python scripts/generate_body_report_daily.py --days 7

# 睡眠レポート（直近30日）
python scripts/generate_sleep_report_daily.py --days 30

# メンタルレポート（直近14日）
python scripts/generate_mind_report_daily.py --days 14
```

3つとも実行し、エラーがあれば報告する。

## Step 3: AIレビュー

生成された3つのレポートを読み込む:

- `tmp/body_report/REPORT.md`
- `tmp/sleep_report/REPORT.md`
- `tmp/mind_report/REPORT.md`

### レビュー観点

#### 体組成（Body）
- 体重・筋肉量・体脂肪率の直近トレンド
- 目標（FFMI 21.0、月間+0.75kg）に対する進捗
- カロリー収支とタンパク質摂取量（体重×2g推奨）
- 異常値や急激な変動の検出

#### 睡眠（Sleep）
- 睡眠時間の傾向（7-8時間が理想）
- 睡眠効率（85%以上が目標）
- 深い睡眠・REM睡眠の割合
- 就寝・起床時刻の規則性
- 睡眠負債の蓄積状況
- 曜日による傾向の違い

#### メンタル（Mind）
- HRVトレンド（上昇=回復良好、下降=疲労蓄積）
- 安静時心拍数の変動
- 呼吸数・SpO2の異常検出
- 運動負荷と回復のバランス

### 出力形式

以下の形式で日本語で報告:

```
## 日次ヘルスレビュー（YYYY-MM-DD）

### 総合コンディション
全体的な状態を一言で（例: 良好 / 注意 / 要改善）

### Body（体組成）
- 現状サマリー
- 良い点 / 注意点

### Sleep（睡眠）
- 現状サマリー
- 良い点 / 注意点

### Mind（メンタル・回復）
- 現状サマリー
- 良い点 / 注意点

### 今日のアドバイス
具体的なアクション（2-3個）
```
