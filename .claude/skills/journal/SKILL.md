---
name: journal
description: ヘルスジャーナル（日次/週次/月次レビュー + ディスカッション記録）を reports/journal/ に蓄積する
argument-hint: "[YYYY-MM-DD | --weekly [YYYY-Wxx] | --monthly [YYYY-MM]]"
user-invocable: true
allowed-tools: Bash, Read, Write, Edit
---

# Journal Skill

daily-review / weekly-review / monthly-review の結果とディスカッションを `reports/journal/` に蓄積する。

## 保存構造

```
reports/journal/
  JOURNAL.md      索引。新しい順の表。要約が検索キー
  STATE.md        現在の状態。**生成物。書かない**
  ACTIONS.md      アクション台帳。1行 append / 1行 edit だけで維持する
  YYYY-Wxx.md     週ファイル。Weekly Summary + 日次エントリ（## YYYY-MM-DD (曜)）
  YYYY-MM.md      月次サマリ
```

週ファイルは**不変の経過**（追記のみ）、STATE.md は**揮発する現在値**（毎日全上書き）で
性質が正反対。ストリーク・鮮度・未解決アクションは `journal_skeleton.py` が毎日
計算し直すので、散文に書かない。書くと事実が変わっていないのに毎日言い換えが発生する。

`reports/{daily,weekly,monthly}/` は2026-08-07に journal へ移行した**凍結アーカイブ**。読む必要も書き込む必要もない（内容は週ファイルに全て入っている）。

## マーカー

週ファイルには3種類の区間がある。**再実行では自分の区間だけを差し替え、区間外には触れない。**

| 区間 | 書き手 | 中身 |
|---|---|---|
| `<!-- skeleton:start/end -->` | `journal_skeleton.py`（毎日） | 数値・7日平均の変化・欠測 |
| `<!-- review:start/end -->` | このスキル | 日次の判断と Action Plan |
| `<!-- weekly:start/end -->` | このスキル | 週の rollup |

Discussion・Evening Check-in・Next Week's Adjustments はマーカーの外に置く（上書きされたくないため）。マーカーを持たない移行前のエントリには触れない。

**読み手はユーザーではなく将来のagent**。人が読み返す前提で書かない。後からagentが「いつ何が起きたか」を索引→1ファイルで辿れる密度を優先する。

**保守は自律実行・確認不要**。daily/weekly/monthly-review を回したらその流れで書く。「記録しますか?」と聞かない。

**恒久的な知見はジャーナルに書かない**。体質・運用方針・指標の落とし穴など今後も効く事実は memory に置き、ジャーナルには経過だけ残す（同じ知見を毎週書き直さない）。振り分けに迷ったら「来月も参照するか」で判断する。

## モード判定

- `--monthly`、または直前に monthly-review → **monthly**
- `--weekly`、または直前に weekly-review → **weekly**
- それ以外 → **daily**

日付・週・月の指定がなければ現在日時から決める。曜日は `date +%A` で確認する（コンテキストの日付から曜日を推測しない）。

```bash
date '+%Y-%m-%d %A'; date '+%G-W%V'   # 今日 / 今週のISO週
```

---

## daily

### Step 1: 週ファイルを特定

その日付のISO週から `reports/journal/YYYY-Wxx.md` を決める。ファイルが無ければ新規作成し、H1 は `# YYYY-Wxx (MM/DD - MM/DD)`（月曜〜日曜）。

### Step 2: 判定

`## YYYY-MM-DD` セクションは skeleton が既に作っている（無ければ日付順を保って作る）。

- `review:start` が**無い** → Step 3a
- **ある** → Step 3a で区間の中身を書き換える（再レビュー）
- 同日の Evening Check-in を足すだけなら Step 3b

### Step 3a: 日次レビュー

skeleton ブロックの直後に置く。

```markdown
<!-- review:start -->

**状態**: 良好 / 注意 / 要改善 — 一行で理由

- **Body**: 現状と注意点
- **Sleep**: 現状と注意点
- **Mind**: 現状と注意点
- **主観 vs 客観**: 一致か乖離か、乖離ならどの構成概念の差か

**Action Plan**
1. 具体的なアクション
2. …

<!-- review:end -->

**Discussion**: レビュー後の会話で深掘りした内容。無ければ省略
```

- 数値は skeleton と STATE.md が持っている。**再掲せず、判断を左右した値だけ根拠として引く**
- 連続日数を文中で数え直さない。STATE.md のストリークを引く
- daily-review の出力をそのまま貼らない。判断と根拠に圧縮する
- 情報が足りなければユーザーに確認する

### Step 3b: Evening Check-in 追補

該当日セクションの末尾に追記する。

```markdown
**Evening Check-in**

| アクション | 結果 | 備考 |
|---|---|---|
| 22時台就寝 | 達成 | 22:15 |
| 体重測定 | 未実施 | 帰宅が遅く失念 |

- 日中に気づいたこと
```

既に Evening Check-in がある場合は上書きせずユーザーに確認する。

### Step 4: ACTIONS.md を更新

- 前回の Action Plan に結果が出ていれば、**その行の状態と更新日だけ**を書き換える。行は消さない
- 今回出したアクションを1行ずつ append する
- `撤回` は「やって裏目に出たので取り下げた」。同じ助言を再発行しないための記録なので残す

**当週の Weekly Summary は書かない。** 週が完了してから1回だけ書く（weekly 節）。
書き忘れは `journal_skeleton.py` が「Weekly Summary が無い」と警告するので、
daily-review でそれを見たときに書けばよい。週の途中で毎日書き直すと、同じ事実の
言い換えを毎日生成することになる。

→ Step 5 へ

---

## weekly

同じ週ファイルの H1 直下に `## Weekly Summary` を置く。日次エントリはその下にそのまま残す。

```markdown
## Weekly Summary

<!-- weekly:start -->

**状態**: 安定 / 軽度乱れ / 要調整 — 一行で理由

- **Body**: 週間変化量と評価
- **Sleep**: 規則性の評価
- **Mind**: 自律神経バランスの評価

**Highlights**: 特に良かった日/悪かった日と要因、曜日パターン、週内の構造変化

<!-- weekly:end -->

**Next Week's Adjustments**
1. 来週への調整ポイント
2. …

**Discussion**: 深掘りした内容。無ければ省略
```

先週の週ファイルの Next Week's Adjustments を読み、達成状況に触れる。

→ Step 5 へ

---

## monthly

`reports/journal/YYYY-MM.md` に保存する。その月の週ファイル（月をまたぐ週は月内の日数が多い方）の Weekly Summary を読んでから書く。

```markdown
# YYYY-MM

**状態**: 順調 / 停滞 / 不安定 / 改善傾向 — 一行で理由

## Review
- **Body**: 月間変化量と目標達成度、8週トレンドの形状
- **Sleep**: 月間の質と規則性、8週トレンドの変化
- **Mind**: 月内の安定性と転換点

## Highlights
- 良かった週 / 悪かった週と要因
- 月内に起きた構造変化
- 週次で繰り返し現れたテーマ

## Weekly Adjustments の効果
- 効いた調整 / 効かなかった調整 / 持ち越したテーマ

## Next Month's Strategy
1. 週次では解決しなかった課題への戦略的アプローチ
2. 継続すべき習慣 / 見直すべき習慣
```

→ Step 5 へ

---

## Step 5: JOURNAL.md の索引を更新

保存したファイルに対応する行を `reports/journal/JOURNAL.md` に追加、または既存行の要約を書き換える。**この索引の要約がagentの唯一の検索面**なので、汎用的な語（「注意」「良好」だけ）で終わらせず、後から引くための固有名詞・数値を入れる。

```markdown
| 08/03-08/09 | [2026-W32](2026-W32.md) | 睡眠6.7-7.0hに改善も主観2/5据え置きで乖離継続。体重計29日欠測。Zone2目標を廃止 |
```

- 新しい週/月ほど上。年ごとに `## YYYY` 見出しで区切る
- daily 追記のたびに、その週の行の要約を最新化する（週の途中でも索引だけで状況が分かる状態を保つ）
- **1行100字程度まで。** 索引は毎セッション全文が読まれるので、行の長さがそのまま
  固定費になる。要約ではなく検索キーとして書く（どの週を開くか決められれば足りる）

## Step 6: 恒久知見の振り分け

そのセッションで「今後も効く事実」が出ていれば memory に書き、ジャーナルからは省く。事後に1-2文で報告する（確認は不要）。

保存後、ファイルパスと索引の更新内容をユーザーに提示する。GitHub Issue への投稿は行わない。
