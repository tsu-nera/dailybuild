# 気分記録・PHQ-9（Google Forms）

## 気分記録

Google Form で入力し、Forms API で直接読む（回答先スプレッドシートは作らない。
Forms API にリンク設定が無く、そこだけ手作業として残るため）。3問構成
（選択式グリッド「いまの状態」1〜5（いまの気分／身体の軽さ／頭の冴えの3行）・
気持ち12個・何があった？）。**Issue #104** で、気分1問だけの scaleQuestion から
グリッド1問（`questionGroupItem`）へ移行した。身体・頭の疲労感を manual.csv の
1日1点でなく timestamp 付きで取るため。

- **サービスアカウントでは作れない。** Drive の `storageQuota.limit` が 0 で
  ファイルを所有できず、`forms.create` が **500 Internal** になる（quota だと
  分かるエラーは返らない）。OAuth で本人が所有する
- **フォームを画面で編集しない。** 語彙の正は `config/emotion_def.yaml` で、
  `setup-form --update` が画面の内容を上書きする
- 削除された回答は CSV に残り続ける（マージは追加・更新のみ）
- グリッドの列（1〜5）は **valence（高=良好）であって感情・身体感覚の強さでは
  ない**。`mind_score` / `body_score` と同じ向き。列見出しは全行共通のため、
  向きも全行で強制的に揃う（「疲労感」のように高=悪化の項目名は採れない）。
  グリッドの回答も `textAnswers` に文字列で入るので数値化はこちら側
  （`emotion.py`）で行う
- **`data/emotion_vocab_history.csv` に語彙の版を残している。** 語彙を後から
  変えると過去のデータが読めなくなる（0件が「感じなかった」のか「選択肢が
  無かった」のか区別できない）ため、**語彙そのものが変わったときだけ**
  1行追記する。per-row の版列は持たない（毎回全件取り直すのでマージが濁る）
- **`data/emotion_grid_history.csv` にグリッドの行構成（行タイトルの並び順）の
  版を残している。** 同じ理由・同じ実装（`update_vocab_history()` を labels
  でなく行タイトルのリストで呼ぶだけ）。ファイルを分けているのは、語彙と
  グリッド行が別の構成要素で、同じファイルに混ぜると revision_id だけでは
  「何の版か」が読み取れなくなるため。身体・頭の列は移行後にしか値が入らず、
  これが無いと空欄が「軽かった」のか「まだ聞いていなかった」のか区別できない
- **追記判定に `revisionId` を使ってはいけない。** `revisionId` は質問文の
  変更でも `setup-form --update` の空打ちでも上がる（実測: 08 → 09）ので、
  これをキーにすると語彙が同じ行が積み上がり、「いつ語彙が変わったか」を
  知るのに結局 `labels` を diff する羽目になる。`revision_id` 列は
  「その語彙が最初に観測された版」の記録として持つだけ
- **フォームの質問はタイトルでなく種類（scale/choice/text/グリッド）で突き
  合わせて更新している。** index で突き合わせると既存 item の型を作り変える
  ことになり、questionId が保持されたまま中身が変わって過去の回答が別の質問に
  化ける（`gforms_api.sync_questions()`）。グリッド（`questionGroupItem`）も
  1つの種類として扱うが、**フォーム全体でグリッドは1個の運用が前提**（現状の
  3問構成では他に同型が無いのでタイトルで揉めることは起きない）
- **グリッドの行（questions[] の中身）はタイトルでなく出現順（FIFO）で
  対応付ける。** これは気分記録が3問とも型が違う（scale/checkbox/text）ため
  問題にならなかった旧構成とは事情が異なる。**グリッド化で「同型が複数並ぶ」
  状態になったので、PHQ-9 の9問と同じ制約が行単位で効く。** `emotion_def.yaml`
  の `grid_rows` の並びを変えて `setup-form --update` を回すと、既存回答の
  questionId が別の行に付け替わる（`tests/test_emotion.py` の
  `test_sync_questions_grid_row_order_change_is_detected` で固定）。行を
  **足す**のは末尾に追加するだけで既存行の questionId は保持される
  （`test_sync_questions_grid_add_row_preserves_existing_row_ids`）
- **`updateItem` は `questionId` を明示しないと新しい ID を採番し直す。**
  タイトルだけの変更でも起きる。そうなると過去の回答は古い ID のまま孤立し、
  タイトル → questionId で引いている CSV 側から二度と読めない（実際に一度
  発生させ、回答に残っていた古い ID を明示指定して復旧した）。グリッドの行も
  同様に、行ごとの `questionId` を明示的に埋め込む

### 移行手順（気分1問 → グリッド化、Issue #104）

本番フォームと既存回答を書き換える取り消しにくい操作なので、**人間が手動で
実行する**（この Issue の PR ではコード・テストのみで実行しない）。

1. `data/emotion.csv` をバックアップする（例: `cp data/emotion.csv /tmp/emotion.csv.bak`）
2. `uv run scripts/emotion.py setup-form --update` を実行し、画面の質問構成を
   `config/emotion_def.yaml`（グリッド3行）に合わせる
3. `uv run scripts/emotion.py fetch` を実行し、最新の回答を取得する
4. 既存14件の `score` が保持されていることを差分確認する
   （例: `diff <(cut -d, -f1,3 /tmp/emotion.csv.bak) <(cut -d, -f1,3 data/emotion.csv)` で
   `timestamp,score` の対応がそのまま残っているか見る。列位置が変わっている
   場合は列名で見る）。`body` / `head` は移行前の回答では空欄のままでよい
   （まだ聞いていなかったので NA が正しい）

失敗時（`score` が別の値に化けている等、行順の付け替えを疑う場合）は、
バックアップした `data/emotion.csv` を戻し、フォーム側は Forms API の編集画面
（`setup-form` が出す「編集用URL」）で `questionId` を確認しながら手動修正する。
`gforms_api.sync_questions()` 自体は変更せず、`grid_rows` の並びを元に戻して
`setup-form --update` を再実行するのが基本の復旧手順。

## PHQ-9（週次）

うつの重症度を測る自己記入式の質問紙（0〜27点）。`mind_score`（毎日・1〜5）とは
別に、検証済みの尺度で施策の前後を判定するために足した（Issue #100）。
`mind_score` は廃止しない。気分記録（#87）とは別フォームにしてある（頻度が
毎日 vs 週次で違うため）。

**週次で運用し、`/weekly-review` の手順に組み込んである。** 想起期間が2週間なので
連続する2点は1週分の期間を共有するが、害は「平滑化」であって偏りではなく、
2週窓を週1でサンプリングした移動平均として読めばよい。**主要判定（ベースライン
と8週後）の2つの窓は重ならないので、MCID 5点の判定は隔週でも週次でも同一。**
週次にする理由は、8週間で取れる点数が4点→8点になること（4点では傾きも引けない）と、
既存の週末の儀式（`/weekly-review`）に相乗りできること。隔週は「今週はやる週か」を覚えておく必要があり、
手動記録が続かない要因になる。

**週ごとの差を「変化」と読まない。** 窓が半分重なるので1週で5点動くことは
構造的に起きにくい。MCID 5点を当てるのは窓が重ならない比較（0週 vs 4週、0週 vs 8週）。

**日本語版の設問文を追跡対象のファイルに書いてはいけない。** 出典・著作権:

> ©kumiko.muramatsu「PHQ-9 日本語版 2018版」
> Muramatsu K, Miyaoka H, Kamijima K et al. *General Hospital Psychiatry*
> 52: 64-69, 2018. https://www.cocoro.chiba-u.jp/recruit/tubuanDB/files/PHQ-9.pdf

日本語版は村松公美子氏が別途著作権を持ち、配布物に「無断複写・転載・改変を
禁じます」と明記されている（英語原版は複製・翻訳・配布に許可不要だが、日本語版は
別物）。設問文の実体は `config/phq9_def.yaml`（`.gitignore` 済み、手元にのみ置く）
が持ち、`config/phq9_def.yaml.sample` は構造・選択肢の配点・出典URLのみで設問文は
空。setup-form を回す前に `cp config/phq9_def.yaml.sample config/phq9_def.yaml` して
出典から書き写すこと。**agent による英語版からの翻訳で代替しない。** 規準値・MCID
（意味のある変化=5点）はその文言・その順序で検証された数字で、訳し直した時点で
自作スコアに戻る。

- **設問文・選択肢・並び順は凍結する。yaml の q1〜q9 の並び順を変えないこと。**
  PHQ-9 は9問すべて同型（ラジオボタン）で、`gforms_api.sync_questions()` は
  item 単位ではタイトルを見ず「種類ごとの出現順（FIFO）」で既存質問と対応付ける。
  同型が9問並ぶ PHQ-9 で質問順を変えて `setup-form --update` を回すと
  questionId が別の設問に引き継がれ、過去の回答が別の質問の回答として
  読めてしまう。**気分記録もグリッド化（Issue #104）以降は同じ制約を持つ**
  （グリッドの行 = questions[] の中身が出現順対応になったため。「気分記録の
  節」参照）。対応は運用規約とテスト（`tests/test_phq9.py` /
  `tests/test_emotion.py` が出現順対応を固定）で行い、`sync_questions()`
  自体（item 単位の kind マッチング）は変更しない
- 合計（`total`）は9問すべてに回答があるときだけ算出する。**未回答を0点として
  足さない。** 1つでも未回答なら NaN（成分表の「-」＝未測定と同じ原則）
- **機能障害の設問（10問目）は合計に含めない。** `impairment` 列に採点対象外の
  生ラベルで残す。yaml のフラグ（`impairment.enabled`）で有無を切り替えられる
  （既定は含める）
- 9項目目は死や自傷についての設問を含むが、データとして特別扱いはしない
- マージキーは気分記録と同じく `timestamp`
- **回答0件をエラーにしない。** 週1回なので大半の日は0件が正常（カフェインと
  同じ扱い）
- レポート・可視化への反映、`mind_score` との統合はスコープ外（Issue #100）。
  データが数点しか無いうちは意味がない
