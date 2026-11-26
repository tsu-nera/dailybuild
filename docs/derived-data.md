# 日次で生成する派生データ（`reports/`）

`daily-fetch.sh` の最後のステップだけは取得ではなく書き込みで、`journal_skeleton.py` がその日の
数値・7日平均の変化・欠測を `reports/journal/YYYY-Wxx.md` へ追記する。
レビューの記録（gtd の `/reviewing-health`）は対話が主目的なので、レビューを回さないと1行も残らず、
実際 2026-08-07 から3週間（うつエピソードで HRV が 25.9→44.7 まで動いた期間）が
丸ごと空いた。**記録が最も必要な状態が、記録が最も途切れやすい状態と一致する**ため、
数値だけは対話に依存せず機械が書く。

骨組みは `<!-- skeleton:start -->` 〜 `<!-- skeleton:end -->` に囲まれ、再実行では
この区間だけを差し替える。区間外の考察は保持し、**マーカーを持たない既存エントリ
（移行前に人と agent が書いたもの）には一切触れない**。

同じスクリプトが `reports/journal/STATE.md` も毎日**全上書き**で生成する。
ジャーナルの4ファイルは書き手と寿命で分かれている:

| ファイル | 書き手 | 更新 | 寿命 |
|---|---|---|---|
| `STATE.md` | script | 毎日 | 揮発（全上書き） |
| `ACTIONS.md` | agent | 発行時に1行 append / 結果が出たら1行 edit | 追記のみ |
| `YYYY-Wxx.md` | script（骨組み）+ agent（考察） | 毎日追記 | 不変 |
| `JOURNAL.md` | agent | 毎日1行更新 | 索引 |

同じスクリプトが `reports/metrics_daily.csv` も毎日**全上書き**で生成する。
日付 index の横持ちで、相関分析はこれ1本を読めばよい
（`pd.read_csv(..., index_col='date').corr()`）。**`data/` には置かない**
（あちらは取得の正本で、派生を混ぜると意味が壊れる）。

体重の全期間は `reports/weight_daily.csv`（`date, weight, source`。同じく毎日**全上書き**）。
`metrics_daily.csv` の `weight` は HealthPlanet だけで 2020-01 より前が無いので、長期の体重はこちらを読む。
経路は `lib.analytics.weight_daily.SOURCES` の優先順で日ごとに1つ採る（HealthPlanet → Google Health）。
`data/wearable/body_weight.csv`（Fitbit）は Google Health に全日が含まれるので使わない。体脂肪率は機器ごとに
推定式が違うので入れない。新しい体重計を足すときは `SOURCES` に1行足す。

`sleep_debt` は**意図的に入れていない**。欠測日を睡眠0hとして計上しており、
相関では実データとして扱われてしまう。0埋めは STATE.md のストリーク用途に
閉じ込めてある。**「便利だから」と足さないこと。**

`metrics_daily.csv` の interval グレイン版が `reports/events.jsonl`（`scripts/events.py build`。
日次の最後に毎日**全上書き**で生成）。「その日に何をしていたか」はこれ1本を読む。
1行1イベントで `{start, end, source, kind, name, attrs}`、`start` 昇順。`start` / `end` は
必ず tz-aware（`+09:00`。naive な入力は JST として解釈する）、点イベントの `end` は `null`。
ソースは Toggl（2026-10-27 より前は Track、以降は Focus。`toggl push` 由来を除く）・exercise（platform 重複解決済み）・メイン睡眠・
凍結した Habitica の履歴（2026-10-05 で記録停止・取得は退役済み。Daily は完了行、Habit は押下のある行のみ）・Calendar（終日は日付の JST 00:00 〜 排他端）。どれかが0件なら更新せず非ゼロ終了する。
Focus 由来の Toggl の行は `attrs.client_name`（`data/toggl/focus_projects.csv` を `project_id` で引いたクライアント名）を持つので、
`良い習慣` / `悪い習慣` の出来事の前後をそのまま引ける。Track 由来の行・一覧に無いプロジェクト・`focus_projects.csv` が無いときは持たない（生成は止めない）。
日次に潰すと4分の筋トレと63分の通勤が区別できないので `metrics_daily.csv` には混ぜない。
**`data/` には置かない**。

`scripts/dashboard.py build` は `reports/dashboard/*.csv`（Grafana が読む表を画面ごとに。`body` / `sleep` / `mind` 画面の `daily.csv` を含む。`--only` で一部のグループだけ作り直せる）を毎日**全上書き**で
生成する（`daily-fetch.sh` の「ダッシュボード」ステップ）。**`data/` には置かない**。詳細は [docs/grafana.md](docs/grafana.md)。

`scripts/habits.py build` は `reports/habits_daily.csv` を毎日**全上書き**で
生成する（`daily-fetch.sh` の「習慣」ステップ。Toggl Focus のクライアント「良い習慣」「悪い習慣」の
プロジェクトが習慣）。列は `date, habit, task_type, is_due, completed` の縦持ちで、習慣の
増減で列が動かないようにしてある。行はプロジェクトを観測できた日（`max(created_at, 2026-10-27)`
から `archived_at` または今日まで）だけで、範囲外の日の行は作らない（欠測と不生起を分ける）。
`task_type` は `toggl`、`is_due` は空。`metrics_daily.csv` の横持ちには**混ぜない**
（`is_due=False` と欠測を0埋めで潰す事故を持ち込むため）。こちらも**`data/` には
置かない**（あちらは取得の正本）。読み手は Grafana の「目標」画面（`dashboard.py` の `goals_list`。
習慣ごとの今週・先週の日数は `lib/habits/weekly.py`）と habits-review スキル。設定とのずれ（目標の無い良い習慣など）が
あっても CSV は書き、名前を stderr に出して非ゼロで終わる（[docs/habits.md](habits.md)）。

ストリーク（連続日数）・鮮度・未解決アクションは STATE.md が毎日計算し直すので、
**散文に書かない**。以前は週の rollup を agent が毎日書き直しており、事実が
変わっていないのに表現だけが毎日漂流していた。恒久的に効く知見は
ジャーナルではなく memory に置く（`~/.claude/projects/*/memory/`。リポジトリ外）。
