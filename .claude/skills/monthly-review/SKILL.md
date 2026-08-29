---
name: monthly-review
description: 月次レポート生成（日次×月＋週次インターバル）→AIレビューを実行する月次レビュースキル（GTD準拠・月末実施）
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# 月次レビュースキル

GTDのMonthly Reviewに合わせて月末に実施する。月内の事実確認（daily monthly）と中長期トレンド（interval）の両面から、月次の転換点・前月比の変化・戦略的な見直しを行う。
レビュー後のディスカッションを経て、記録は `/journal` スキルで保存する。

## オプション

| オプション | 説明 | デフォルト |
|------------|------|------------|
| `--month N` | 対象月を明示指定（例: `--month 4`） | current |
| `--year YYYY` | 年を明示指定 | 今年 |
| `--only body\|sleep\|mind` | 指定したレポートのみ生成・レビュー | 全3種 |
| `--no-interval` | intervalレポート生成をスキップ | なし |

例:
- `/monthly-review` → 今月の全3種＋intervalをレビュー
- `/monthly-review --month 4` → 4月分をレビュー
- `/monthly-review --only mind` → メンタルのみ
- `/monthly-review --no-interval` → 月次詳細のみ

## Step 1: 月次詳細レポート生成（daily --month）

`--only <type>` 指定時は該当のみ実行。

```bash
cd /home/tsu-nera/repo/dailybuild

# 体組成（月次詳細）
uv run python scripts/generate_body_report_daily.py --month current

# 睡眠（月次詳細）
uv run python scripts/generate_sleep_report_daily.py --month current

# メンタル（月次詳細）
uv run python scripts/generate_mind_report_daily.py --month current
```

出力先: `reports/{body,sleep,mind}/monthly/YYYY-MM/REPORT.md`

## Step 2: 週次インターバルレポート生成（interval --weeks 8）

`--no-interval` 指定時はスキップ。`--only` 指定時は該当のみ。

```bash
# 体組成（8週トレンド）
uv run python scripts/generate_body_report_interval.py --weeks 8

# 睡眠（8週トレンド）
uv run python scripts/generate_sleep_report_interval.py --weeks 8

# メンタル（8週トレンド）
uv run python scripts/generate_mind_report_interval.py --weeks 8
```

出力先: `reports/{body,sleep,mind}/interval/REPORT.md`（上書き）

## Step 3: 今月のweekly journalを読み込み

`reports/journal/JOURNAL.md` の索引から今月の週を特定し、該当する `reports/journal/YYYY-Wxx.md` を読む。月をまたぐ週は、月内の日数が多い方の月に含める。各ファイル先頭の Weekly Summary が主対象で、日次エントリは必要に応じて掘る。

これらは Step 4 のレビューで「定性的な文脈」として参照する：
- 各週の Highlights・Discussion
- Next Week's Adjustments の達成状況（次週以降のjournalで追跡可能なら）
- 月内の気づきの推移・繰り返しテーマ

## Step 4: AIレビュー

以下を統合して月次の観点でレビューする。

- `reports/{body,sleep,mind}/monthly/YYYY-MM/REPORT.md` … 月内の事実（量的データ）
- `reports/{body,sleep,mind}/interval/REPORT.md` … 8週トレンド（前月比含む）
- Step 3 で読み込んだ weekly journal … 定性的な文脈・週次の調整履歴

### レビュー観点（月次特化）

#### 体組成（Body）
- 月間の体重・筋肉量・体脂肪率の変化量と達成度
- 月間目標（+0.75kg/月、FFMI は `show_targets.py` の宣言値）に対する進捗
- 8週トレンドでの増量/減量カーブの形状
- カロリー収支の月平均と栄養バランス

#### 睡眠（Sleep）
- 月内の睡眠時間・効率の中央値とばらつき
- 8週トレンドでの就寝・起床時刻の規則性変化
- 睡眠負債の月間累積
- 月内の睡眠破綻日とその要因

#### メンタル（Mind）
- 月内のHRV/RHRトレンドと転換点
- 自律神経の月次バランス（緊張期/回復期の比率）
- 8週推移での不安定さの検出（前月比）
- 活動量・回復のサイクル評価

### 出力形式

```
## 月次ヘルスレビュー（YYYY-MM）

### 今月の総合コンディション
全体評価を一言で（例: 順調 / 停滞 / 不安定 / 改善傾向）

### Body（体組成）
- 月間変化量と目標達成度
- 8週トレンドの形状
- 良い点 / 課題

### Sleep（睡眠）
- 月間の質と規則性
- 8週トレンドの変化
- 良い点 / 課題

### Mind（メンタル・回復）
- 月内の安定性とトレンド
- 8週推移での転換点
- 良い点 / 課題

### 今月のハイライト
- 特に良かった週/悪かった週とその要因
- 月内に起きた構造変化（生活パターンの変化など）
- weekly journalで繰り返し現れたテーマ

### 週次調整の効果
各週の Next Week's Adjustments がどう機能したか
- 効いた調整 / 効かなかった調整
- 持ち越されたテーマ

### 来月の方針
- 戦略的な調整ポイント（2-3個）
- 継続すべき習慣 / 見直すべき習慣
- 週次レベルでは解決できなかった課題の取り扱い
```

レビュー後、ディスカッションを経て記録を残す場合は `/journal` を使用する。
