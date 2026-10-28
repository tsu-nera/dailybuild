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

`scripts/toggl.py push` は Google Health 睡眠（昼寝含む）と Google Health の運動セッション
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
運動が2本入るため、時間が重なったら優先度の高い方だけを残す。

優先度・重なり閾値は **`config/toggl_push.yaml` ではなく
`src/lib/exercise_source.py` の `PLATFORM_PRIORITY` / `OVERLAP_THRESHOLD_SEC`**
（`lib/toggl/sources.py` の `googlehealth_exercise_intervals` はここを
import して使う）。push とレポート（body / mind / circadian）が同じ集合を
見る必要があるため、consumer 別に yaml で持たせず一箇所に固定してある。
優先度は**重なりの解決にのみ**使う。重なっていないセッションは platform に関係なく
残すので、Fitbit Web API 廃止後に Fitbit 側が途切れても Health Connect 側で
穴が埋まる。

`exercise` は `dailyRollUp` 非対応で `list` のページングだけ（全履歴242ページ）。
既存の `data/wearable/activity_logs.csv` とはスキーマを揃えていない別ファイルで、
**統合しない**（Issue #96 で決定。id 空間・`activeZoneMinutes` の構造・距離の
単位系がいずれも別物）。`activity_logs.csv` は Fitbit Web API 廃止後のアーカイブ
として凍結し、レポート3経路（body / mind / circadian）は `exercise.csv` だけを
読む。マージのキーは日付でなく `id`（19桁の整数なので読み戻しは `dtype=str`
必須。int で読むと新旧のキーが一致せず二重に残る）。

## Toggl 2.0（Focus API）の取得

2026-10-27 から手動の時間記録は Toggl 2.0 に書いている。Track v9 の `/me/time_entries`
には 2.0 に書いたエントリが返らないので、`toggl.py fetch-focus` が Focus API
（`https://focus.toggl.com/api`、`Authorization: Bearer`）から別に取り、
`data/toggl/focus_entries.csv` へ保存する（`lib.toggl.focus`）。push・start・stop の
書き先は Track のまま。

- **`include_taskless=true` を付けないと task 無しのエントリが返らない。** 手動エントリは
  ほぼ task 無しなので、外すと黙って大半を取り逃す
- **`stop` フィールドが無い。** `start + duration` で計算する。計測中の表現は未確認なので
  `duration` が None / 負値のものを除外している
- **id・project_id は Track と別の体系**（同名プロジェクトでも ID が違う）。だから
  `time_entries.csv` には混ぜない（id の `keep='last'` マージで重複・取り違えが起きる）。
  マージ・窓内置換のロジックは `store.save_merged(csv_path=...)` を共有する
- **migrate は一回きりのコピーで同期ではない。** 2026-10-27 の migrate までの Track の
  エントリ（auto タグの睡眠・サイクリング含む。例: 2026-10-05）は 2.0 にも別 ID で
  存在するが、その後 Track へ push したもの（例: 2026-10-28 の睡眠）は 2.0 に無い。両ファイルを素で足すと移行済みの期間が二重になる。
  `events.jsonl` がどちらを正本にするかは未決
- `date_from` / `date_to` は必須。JST の暦日を UTC の RFC 3339 に変換して渡す。
  ページ送りは `page`（1始まり）/ `per_page`（最大100）
- organization を列挙する API は無い。`/users/me/settings` の
  `tos_ack_decoupled_licenses` のキーが organization_id（`.env` の
  `TOGGL_FOCUS_ORGANIZATION_ID`）。workspace_id は Track と同じ値
- 2026-10-28 時点でクォータのヘッダは返っていない（Free プラン。docs 上 30 req/h、
  超過は 402）。ヘッダが付けば残量をログへ出す
