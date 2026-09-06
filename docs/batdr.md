# BATD-R（行動活性化）の一次資料

Issue #113 / #147 の行動活性化レイヤが依拠する原典。**手続きの構造（順序・
判定基準・分岐）は事実として書いてよいが、教示のセリフとフォームの文面を
そのまま貼らない**（PHQ-9 と同じ扱い。詳細は docs/forms.md）。

## 出典

Lejuez, C. W., Hopko, D. R., Acierno, R., Daughters, S. B., & Pagoto, S. L. (2011).
Ten Year Revision of the Brief Behavioral Activation Treatment for Depression:
Revised Treatment Manual. *Behavior Modification, 35*(2), 111–161.
<https://doi.org/10.1177/0145445510390929>

帳票（Form 1〜4）は本文ではなく SAGE の supplemental にある
（`http://bmo.sagepub.com/supplemental`。**2026-09-06 時点でこのホスト名は
既に死んでおり、本文中のリンクは辿れない**）。実際に取得できたのは
無関係な第三者サイトの再配布で、消える前提で扱う。

## ローカル複製

PDF と `pdftotext -layout` 済みの `.txt` を private 側に置いてある。
**public repo に実体を置かない**（SAGE の論文なので再配布になる）。

```
~/repo/dailybuild-private/refs/batdr/
  batdr-r-2011-lejuez.{pdf,txt}              # 本文（マニュアル全体）
  form1-daily-monitoring.{pdf,txt}
  form2-life-areas-values-activities.{pdf,txt}
  form3-activity-selection-ranking.{pdf,txt}
```

Form 4（協定書）は取得できていない。仕様は本文側に記述がある。

参照は Web 検索ではなく `.txt` を grep する。検索で辿り着くコピーは版が
不明で、帳票だけを切り出した PDF には教示が付いていない。

## 実装前に踏むと危ない点

原典を読まずに設計して食い違った箇所。**issue 本文より原典が優先する。**

- **Form 1 は1時間刻み22行（5am 開始・翌 5am まで）× 活動 / 楽しさ(0-10) /
  重要さ(0-10)、加えて末尾に「その日の総合気分(0-10)」1つ。** 時間ごとの気分
  評定は BATD-R で**意図的に削除**され、日1個に置き換えられた（短時間の微細な
  変化は報告できない、行動変化に対し気分は遅れる）。日1個は省略枠ではなく判断
- **負担が重い時に原典が許すのは「日数を減らす」であって粒度ではない**
  （週2〜3日・平日と週末を両方含める → 徐々に増やす）。1時間刻みの目的が
  「楽しくも重要でもない時間の**長さ**」の観測なので、ブロックに丸めると
  測りたい量が消える
- **自由記述を避ける公式の変種がある。** 低識字者向けに、活動を最大20個の
  番号付き語彙から選ぶ Form 1 Supplement が用意されている。選択式フォームは
  原典からの逸脱ではない
- **第4週以降、Form 1 は入力フォームでなく書き換え可能な予定表になる。**
  計画した活動を事前に時刻つきで記入し、実行したら丸、未実行なら線を引いて
  実際にやったことを書く。追記専用の Google Forms には構造的に載らない
- Form 2 の評定軸は活動ごとの楽しさ・重要さ（快・熟達 P/M ではない）。
  Form 3 は活動15個を難易度 1〜15 で並べるだけの1枚
