---
name: weekly-review
description: 週次レポート生成→AIレビューを実行する週次レビュースキル（GTD準拠・日曜実施）
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# 週次レビュースキル

GTDのWeekly Reviewに合わせて日曜に実施する。今週分のデータを集約し、曜日傾向・規則性・先週比を評価する。
レビュー後のディスカッションを経て、記録は `/journal` スキルで保存する。

## オプション

| オプション | 説明 | デフォルト |
|------------|------|------------|
| `--week N` | 対象ISO週を明示指定（例: `--week 17`） | current |
| `--year YYYY` | 年を明示指定 | 今年 |
| `--only body\|sleep\|mind` | 指定したレポートのみ生成・レビュー | 全3種 |

例:
- `/weekly-review` → 今週の全3種をレビュー
- `/weekly-review --week 17` → ISO週17をレビュー
- `/weekly-review --only mind` → メンタルのみ

## Step 1: レポート生成

`--only <type>` 指定時は該当のみ実行。`--week` `--year` 指定時はそのまま渡す。

```bash
cd /home/tsu-nera/repo/dailybuild

# 体組成
python scripts/generate_body_report_daily.py --week current

# 睡眠
python scripts/generate_sleep_report_daily.py --week current

# メンタル
python scripts/generate_mind_report_daily.py --week current
```

出力先: `reports/{body,sleep,mind}/weekly/YYYY-Wxx/REPORT.md`

エラーがあれば報告する。

## Step 2: 今週のdaily journalを読み込み

その週（月〜日）に該当する `reports/daily/YYYY-MM-DD.md` を全て読み込む。存在する分のみ。

```bash
# 今週の月曜〜日曜を計算（--week 指定時はその週）
# 該当する reports/daily/*.md を Read で全て取得
```

これらは Step 3 のレビューで「定性的な文脈」として参照する：
- 各日のDiscussion・Action Plan・Lessons Learned
- Action Plan の達成状況（Evening Check-inがあれば）
- 週内の気づきの推移

## Step 3: AIレビュー

生成された3つのREPORT.md（量的データ） + Step 2 のdaily journal（定性的データ）を統合してレビューする。

### レビュー観点（週次特化）

#### 体組成（Body）
- 週内の体重・筋肉量・体脂肪率の推移（増減トレンド）
- 週合計のカロリー収支とタンパク質摂取
- 平日/週末の食事パターンの違い
- 月間目標（+0.75kg/月）に対する週次進捗

#### 睡眠（Sleep）
- **就寝・起床時刻の規則性**（週次レビューで最重要）
- 平日/週末の睡眠負債とリカバリーパターン
- 週合計の睡眠時間・効率の傾向
- 中途覚醒の頻度傾向

#### メンタル（Mind）
- HRV/RHRの週内推移と曜日傾向
- 自律神経の緊張⇄回復サイクル
- 活動量と回復のバランス（過活動/過少活動の検出）
- 週内の不安定要因の特定

### 出力形式

```
## 週次ヘルスレビュー（YYYY-Wxx: MM/DD - MM/DD）

### 今週の総合コンディション
全体評価を一言で（例: 安定 / 軽度乱れ / 要調整）

### Body（体組成）
- 週内推移サマリー
- 良い点 / 注意点

### Sleep（睡眠）
- 規則性の評価
- 良い点 / 注意点

### Mind（メンタル・回復）
- 自律神経バランスの評価
- 良い点 / 注意点

### Action Plan の達成度
今週のdaily journalで宣言したAction Planの達成状況をレビュー
- 達成できたもの / できなかったもの
- 未達の要因分析

### 今週の振り返り
- 特に良かった日/悪かった日とその要因
- 曜日パターンや繰り返しの傾向
- daily journalで繰り返し現れたテーマ

### 来週への調整ポイント
具体的なアクション（2-3個）。今週のLessons Learnedを踏まえる。
```

レビュー後、ディスカッションを経て記録を残す場合は `/journal` を使用する。
