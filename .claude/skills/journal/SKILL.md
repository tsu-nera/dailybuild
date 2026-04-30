---
name: journal
description: ヘルスジャーナル（日次/週次レビュー + ディスカッション記録）を生成・保存する
argument-hint: [YYYY-MM-DD | --weekly [YYYY-Wxx] | --monthly [YYYY-MM]]
user-invocable: true
allowed-tools: Bash, Read, Write
---

# Journal Skill

daily-review または weekly-review の結果とディスカッションを元に、ヘルスジャーナルエントリーを生成・保存する。

## モード判定

引数および会話コンテキストから判定する：

- `--monthly` 指定、または直前に monthly-review が実行されている → **monthlyモード**
- `--weekly` 指定、または直前に weekly-review が実行されている → **weeklyモード**
- それ以外 → **dailyモード**（現行動作）

## 引数パース

### dailyモード
- 引数があればその日付を使用（YYYY-MM-DD 形式）
- 引数がなければ今日の日付を使用

### weeklyモード
- `--weekly YYYY-Wxx` 形式で週を指定
- `--weekly` のみなら今週（ISO週）

### monthlyモード
- `--monthly YYYY-MM` 形式で月を指定
- `--monthly` のみなら今月

---

## dailyモード

### Step 1: 日付決定

引数または今日の日付から `YYYY-MM-DD` を決定する。

### Step 2: モード判定（新規/追記）

`reports/daily/YYYY-MM-DD.md` が既に存在するか確認する。

- **存在しない** → **新規モード**（Step 3a へ）
- **存在する** → **追記モード**（Step 3b へ）

### Step 3a: 新規モード — Journal エントリー生成

現在の会話コンテキスト（daily-review 結果 + ディスカッション内容）から、以下のフォーマットで journal エントリーを生成する。

**フォーマット**:

```markdown
# Health Journal YYYY-MM-DD

## Review

### 総合コンディション
[良好 / 注意 / 要改善]

### Body（体組成）
- 現状サマリー
- 良い点 / 注意点

### Sleep（睡眠）
- 現状サマリー
- 良い点 / 注意点

### Mind（メンタル・回復）
- 現状サマリー
- 良い点 / 注意点

## Discussion

- [ディスカッションで得た気づき・深掘りした内容]

## Action Plan

- [具体的なアクション（2-3個）]

## Lessons Learned

- [判断の根拠となった気づき・次回に活かすべき教訓]
```

**生成ルール**:
- Review は daily-review のレビュー結果を反映
- Discussion はレビュー後の会話で深掘りした内容を記載。なければ省略可
- Action Plan はディスカッションを踏まえた具体的なアクション
- Lessons Learned は「なぜこうなったか」「次回どうするか」の振り返り。なければ省略可
- 情報が不足している場合はユーザーに確認する

→ Step 4 へ

### Step 3b: 追記モード — 振り返り追記

日中の実行結果や追加の気づきを、既存の journal ファイルの末尾に追記する。

**追記フォーマット**:

```markdown

## Evening Check-in

### Action Plan の実行結果

| アクション | 結果 | 備考 |
|------------|------|------|
| 22時台就寝 | 達成 | 22:15に就寝 |
| 中強度トレーニング | 未実施 | 残業で時間なし |

### 追加の気づき

- [日中に気づいたこと・体調の変化など]
```

**生成ルール**:
- 既存ファイルを Read で読み込み、末尾に追記する
- Action Plan の各項目について、計画と実際の結果を対比する
- 既に `## Evening Check-in` セクションが存在する場合は上書きせず、ユーザーに確認する

→ Step 4 へ

### Step 4: ファイル保存

`reports/daily/YYYY-MM-DD.md` に保存する。ディレクトリが存在しない場合は作成する。

### Step 5: GitHub Issueへの投稿

`weekly-review` ラベルが付いたOpenなIssueを検索し、Step 4 で保存したファイルの内容をコメントとして投稿する。

```bash
ISSUE_NUMBER=$(gh issue list --label "weekly-review" --state open --json number --jq '.[0].number')
gh issue comment "$ISSUE_NUMBER" --body "$(cat reports/daily/YYYY-MM-DD.md)"
```

- Issueが見つからない場合: `bash scripts/create_weekly_issue.sh` で新規作成してから投稿
- 投稿後、IssueのURLを表示する

---

## weeklyモード

dailyの集積を週末に締めくくり、週次サマリーとして週次Issueに投稿してIssueをcloseする。

### Step 1: 週決定

引数 `--weekly YYYY-Wxx` または今週のISO週から `YYYY-Wxx` を決定する。

```bash
# 今週のISO週を取得
YEAR=$(date +%G)
WEEK=$(date +%V)
WEEK_LABEL="${YEAR}-W${WEEK}"
```

### Step 2: Weekly Journal エントリー生成

会話コンテキスト（weekly-review の結果 + ディスカッション内容）から、以下のフォーマットで生成する。

**フォーマット**:

```markdown
# Weekly Health Journal YYYY-Wxx (MM/DD - MM/DD)

## Review

### 今週の総合コンディション
[安定 / 軽度乱れ / 要調整 など]

### Body（体組成）
- 週内推移と週間変化量
- 良い点 / 注意点

### Sleep（睡眠）
- 規則性の評価
- 良い点 / 注意点

### Mind（メンタル・回復）
- 自律神経バランスの評価
- 良い点 / 注意点

## Weekly Highlights

- 特に良かった日 / 悪かった日とその要因
- 曜日パターンや繰り返しの傾向
- 今週の構造変化（生活パターンの変化など）

## Discussion

- [ディスカッションで深掘りした内容]

## Next Week's Adjustments

- [来週への調整ポイント（2-3個）]

## Lessons Learned

- [今週の気づき・次週以降に活かすべき教訓]
```

**生成ルール**:
- Review は weekly-review のレビュー結果を反映
- Highlights は週内の特徴的な日や傾向を抽出
- Next Week's Adjustments はディスカッションを踏まえた具体的な調整
- 情報が不足している場合はユーザーに確認する

### Step 3: ファイル保存

`reports/weekly/YYYY-Wxx.md` に保存する。ディレクトリが存在しない場合は作成する。

### Step 4: 週次Issueへの投稿とclose

該当週の `weekly-review` ラベルOpen Issueに「週次サマリー」コメントとして投稿し、Issueをcloseする。

```bash
ISSUE_NUMBER=$(gh issue list --label "weekly-review" --state open --json number --jq '.[0].number')
gh issue comment "$ISSUE_NUMBER" --body "$(cat reports/weekly/YYYY-Wxx.md)"
gh issue close "$ISSUE_NUMBER" --comment "週次レビュー完了。次週のIssueは別途作成。"
```

- Issueが見つからない場合: 該当週のIssueがすでにcloseされているか、未作成の可能性。ユーザーに確認する
- 投稿・close後、IssueのURLを表示する

---

## monthlyモード

月末に weekly の積み上げを締めくくり、月次サマリーとして保存する。

### Step 1: 月決定

引数 `--monthly YYYY-MM` または今月から `YYYY-MM` を決定する。

```bash
# 今月を取得
MONTH_LABEL=$(date +%Y-%m)
```

### Step 2: Monthly Journal エントリー生成

会話コンテキスト（monthly-review の結果 + ディスカッション内容）から、以下のフォーマットで生成する。

**フォーマット**:

```markdown
# Monthly Health Journal YYYY-MM

## Review

### 今月の総合コンディション
[順調 / 停滞 / 不安定 / 改善傾向 など]

### Body（体組成）
- 月間変化量と目標達成度
- 8週トレンドの形状
- 良い点 / 課題

### Sleep（睡眠）
- 月間の質と規則性
- 8週トレンドの変化
- 良い点 / 課題

### Mind（メンタル・回復）
- 月内の安定性と転換点
- 8週推移の評価
- 良い点 / 課題

## Monthly Highlights

- 特に良かった週 / 悪かった週とその要因
- 月内に起きた構造変化
- weekly journal で繰り返し現れたテーマ

## Weekly Adjustments の効果

- 効いた調整 / 効かなかった調整
- 持ち越されたテーマ

## Discussion

- [ディスカッションで深掘りした内容]

## Next Month's Strategy

- [来月の戦略的調整ポイント（2-3個）]
- 継続すべき習慣 / 見直すべき習慣

## Lessons Learned

- [今月の気づき・次月以降に活かすべき教訓]
```

**生成ルール**:
- Review は monthly-review のレビュー結果を反映
- Highlights は月内の特徴的な週や繰り返しテーマを抽出
- Weekly Adjustments の効果は、その月の weekly journal の Next Week's Adjustments を追跡できた範囲で評価
- Next Month's Strategy は週次レベルでは解決できなかった課題への戦略的アプローチを記載
- 情報が不足している場合はユーザーに確認する

### Step 3: ファイル保存

`reports/monthly/YYYY-MM.md` に保存する。ディレクトリが存在しない場合は作成する。

保存後、ファイルパスをユーザーに提示する（GitHub Issueへの投稿はmonthlyモードでは行わない）。
