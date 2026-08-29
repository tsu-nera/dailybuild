# Toggl Track

Toggl 側で削除されたエントリは CSV に残り続ける（マージは追加・更新のみ）。

`scripts/toggl.py start/stop` は手動計測。プロジェクト名は完全一致 → 大文字小文字
無視 → 部分一致の順に解決し、複数候補に当たったら黙って1つ選ばず候補を出して落とす。
名前 → ID の解決は `data/toggl/projects.json` のキャッシュで行い、**キャッシュに
無い名前を引いたときだけ**取り直す（`--refresh-projects` で明示更新）。start のたびに
一覧を取ると /me 系 30req/h の枠を fetch と食い合って日次取得が落ちるため。

計測中のエントリは duration が負値で表現される（stop を含めない POST）。既に計測中の
ものがある状態で start すると Toggl 側が古い方を自動で停止するので、こちらからは
stop を呼ばない。計測結果は CSV には直接書かず、次回の fetch で入る
（`store.build_dataframe` は duration が負の行を除外する）。

`scripts/toggl.py push` は Fitbit 睡眠（昼寝含む）と Google Health の運動セッション
（サイクリング・筋トレ・瞑想）を Toggl のタイムエントリとして書き込む。書き込みも
`/me` 系と同じ 30req/h 枠を消費する前提で `--max-writes`（既定10）で抑え、超過分は捨てずに次回へ繰り越す。冪等性は
`data/toggl/pushed.csv` の台帳を主に、直前 fetch の `time_entries.csv` を
突き合わせに使う二段構え。台帳にあるが CSV に居ないエントリは「手動削除された」
とみなして再投入するが、判定は**直近 fetch が実際に取りに行った期間**
（`data/toggl/fetch_state.json`）内に限る。範囲外は「未取得」と区別できず、
無限に再投入してしまうため。

この窓に `time_entries.csv` の start の min/max を使ってはいけない。CSV は過去分が
積み上がるだけなので min は何ヶ月も前になり、一度も fetch していない日まで
「カバー済み」と誤認する。睡眠エントリの start は dateOfSleep の**前日夜**にあるので、
fetch と push を同じ `--days N` で回すと投入したエントリがどの fetch 窓にも入らず、
毎日「削除された」と誤判定されて重複投入されていた（2026-08-25 に修正）。

CSV が古い/無い場合、`fetch_state.json` が無い場合、fetch 窓が push 対象期間の前日を
カバーしていない場合は、いずれも台帳のみで判定し、手動削除を検出しない旨を警告する。

なお削除されたエントリは CSV に残り続けるため、**一度 CSV に入った投入済みエントリの
手動削除は原理的に検出できない**。検出が効くのは CSV にまだ入っていないものだけ。

削除判定にはもう一段の条件がある。**直近 fetch（`fetch_state.json` の `fetched_at`）
より後に投入したエントリは判定対象から外す。** push が書いたエントリは、次の fetch
までは CSV に居なくて当たり前なので、これを見ないと fetch を挟まずに push を2回
叩いただけで「削除された」と誤読して重複投入する（2026-08-25 に実際に発生し、
サイクリング2件が Toggl 上で二重になった）。台帳の `pushed_at` が読めない場合も、
疑わしきは再投入しない側へ倒す。

**Toggl は秒未満を含む RFC3339 を 400 で弾く。** Health Connect 由来の運動セッションは
ミリ秒付きで届くので、`build_payload` で秒に丸めてから渡す。

投入先プロジェクトが Toggl 側に無い場合は投入せず次回に回す。project 無しで
投入してしまうと、台帳に「投入済み」として残り、後からプロジェクトを作っても
直せなくなるため。

## 運動セッションの Toggl 反映

ソースは `data/googlehealth/exercise.csv`（`fetch_googlehealth.py` の `exercise`
エンドポイント）。`exerciseType` → プロジェクトの対応は `config/toggl_push.yaml`
の `googlehealth_exercise.categories` に持たせてある。ここに載っていない型
（WALKING / RUNNING 等）は投入しない。

**`YOGA` は瞑想として投入する。** Charge 6 のエクササイズ一覧（41種類）に瞑想は
無く、本体で計測する手段が他に無いため、YOGA を瞑想の代用モードとして使っている。
ヨガを実際にやり始めたらこの対応は破綻する。

**同じ運動が複数プラットフォームから重複して届く。** Fitbit の Charge 6 と、
Health Connect 経由の Google Fit / Hevy が、ほぼ同じ時間帯を別セッションとして
返す（2026年の実測で74組。`WEIGHTS`/FITBIT と `STRENGTH_TRAINING`/HEALTH_CONNECT、
`OUTDOOR_BIKE`/FITBIT と `BIKING`/HEALTH_CONNECT）。素通しすると Toggl に同じ
運動が2本入るため、時間が重なったら `platform_priority` の先頭に近い方だけを残す。

優先度は**重なりの解決にのみ**使う。重なっていないセッションは platform に関係なく
残すので、Fitbit Web API 廃止後に Fitbit 側が途切れても Health Connect 側で
穴が埋まる。

`exercise` は `dailyRollUp` 非対応で `list` のページングだけ（全履歴242ページ）。
既存の `data/fitbit/activity_logs.csv` とはスキーマを揃えていない別ファイルで、
統合は Issue #77 の担当。マージのキーは日付でなく `id`（19桁の整数なので
読み戻しは `dtype=str` 必須。int で読むと新旧のキーが一致せず二重に残る）。
