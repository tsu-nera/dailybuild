---
name: daily-review
description: データ取得→レポート生成→AIレビューを一括実行する日次レビュースキル
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# 日次レビュースキル

データ取得、レポート生成、AIレビューを3ステップで実行する。

## オプション

| オプション | 説明 | デフォルト |
|------------|------|------------|
| `--no-fetch` | Step 1（データ取得）をスキップ | なし |
| `--fetch N` | 取得日数を指定（例: `--fetch 7` で過去7日分） | 2 |
| `--only body\|sleep\|mind` | 指定したレポートのみ生成・レビュー | 全3種 |

例:
- `/daily-review` → 全3ステップ実行
- `/daily-review --no-fetch` → データ取得スキップ、レポート生成→レビュー
- `/daily-review --fetch 7` → 過去7日分取得してから全レポート生成
- `/daily-review --only body` → 体組成レポートのみ生成・レビュー
- `/daily-review --no-fetch --only sleep` → 睡眠レポートのみ生成・レビュー

## Step 1: データ取得

**`--no-fetch` が指定されている場合はこのステップをスキップする。**

`--fetch N` が指定されている場合はNを使用する。指定がなければ `2` を使用する。

```bash
cd /home/tsu-nera/repo/dailybuild
python scripts/generate_report.py body --fetch <N> --days 1
```

## Step 2: レポート生成

`--only <type>` が指定されている場合は該当するコマンドのみ実行する。指定がなければ3つすべて実行する。

```bash
# 体組成レポート（直近7日）-- --only body または指定なしの場合
python scripts/generate_body_report_daily.py --days 7

# 睡眠レポート（直近30日）-- --only sleep または指定なしの場合
python scripts/generate_sleep_report_daily.py --days 30

# メンタルレポート（直近14日）-- --only mind または指定なしの場合
python scripts/generate_mind_report_daily.py --days 14
```

エラーがあれば報告する。

## Step 3: AIレビュー

`--only <type>` が指定されている場合は該当するレポートのみ読み込む。指定がなければすべて読み込む。

- `tmp/body_report/REPORT.md`（body または指定なし）
- `tmp/sleep_report/REPORT.md`（sleep または指定なし）
- `tmp/mind_report/REPORT.md`（mind または指定なし）

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
