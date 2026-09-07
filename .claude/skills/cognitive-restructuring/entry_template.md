---
# 集計可能な欄はここだけに置く（本文に数値を再掲しない）。
# 語彙外の値を書かない: emotions.label は SKILL.md の感情語彙表、distortions は Burns 10種の固定名。
# 取らなかった値は null。**0 で埋めない**（0 は「強度0」として平均に混ざる）。
date: YYYY-MM-DD
mode: quick            # quick | 3col | 5col | 7col
emotions:
  - {label: [語彙表の label], raw: [本人の語が label と違うときだけ], before: NN, after: NN}
distortions: [歪み名, ...]
thought_confidence: {before: NN, after: NN}
belief_text: [その日に本人が言った信念の文。--quick は AI が付けた文]  # B番号は書かない（BELIEFS.md 側の生成物）
belief_confidence: NN
balanced_thought_origin: 本人   # 本人 | ヒントをそのまま | ヒントを編集
change: null                    # --quick のみ: 軽くなった | 変わらない | 重くなった
---
# CBT 思考記録 YYYY-MM-DD (曜) HH:MM
<!-- 曜日は `date +%A` の実行結果から書く。日付から推測しない -->

### 元の記述
<!-- --quick のみ。入力された自由記述を全文そのまま。他モードではこの節ごと省く -->
[原文]

### 状況
[いつ・どこ・誰・何が起きたか（事実）]

### 感情
<!-- 語だけ。強度は frontmatter に置く -->
- [感情]
- 身体感覚: [あれば]

### 自動思考
- [中心的な自動思考]

### 認知の歪みの仮説
<!-- 触れなかった場合はこの節ごと省く -->
- [歪み名]: [なぜそう考えられるかの簡潔なメモ]

### 支持証拠
<!-- 7コラム（--7col）のみ。--3col / --5col ではこの節ごと省く -->
- [事実]

### 反証証拠
<!-- 7コラム（--7col）のみ。--3col / --5col ではこの節ごと省く -->
- [事実・別の見方]

### バランス思考
<!-- --3col ではこの節ごと省く -->
[バランスのとれた代替思考]

### コア信念
[本人の言葉。B番号は書かない]

### 結果
<!-- --3col ではこの節ごと省く。再評価の数値は frontmatter の after に置き、ここには書かない -->
- 気づき / 次の小さな一歩: [本人の言葉]
