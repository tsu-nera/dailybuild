# Toggl

## 区切り日: Track は 2026-10-27 で凍結

2026-10-27 から手動の時間記録は Toggl 2.0（Focus）に書いている。Track は同日で凍結し、
アーカイブ扱いにした（`data/wearable/activity_logs.csv` と同じ）。

| | 2026-10-27 より前 | 2026-10-27 以降 |
|---|---|---|
| 正本 | `data/toggl/time_entries.csv`（Track） | `data/toggl/focus_entries.csv`（Focus） |
| push 分の除外（events） | `pushed.csv` の ID | `focus_pushed.csv` の ID と `auto` タグ |

区切り日は `lib.toggl.store.CUTOVER_DATE`（JST の暦日）の1か所に置き、push・`toggl.py show`・
`events.jsonl` が共有する。移行済み期間は両ファイルに別 ID で入っているので、この区切りで
切らないと二重になる。`toggl.py show` は区切りの前を Track、以降を Focus から連結して表示する。

凍結したもの（消さない）: `time_entries.csv` / `pushed.csv` / `projects.json`。
`toggl.py fetch`（Track の取得）はアーカイブを取り直す手段として残してあるが、日次からは外した。
Toggl 側で削除されたエントリは Track の CSV に残り続ける（マージは追加・更新のみ）。

## 書き込み（push / start / stop）は Focus

`scripts/toggl.py start/stop/current/projects/open` は Focus を使う。プロジェクト名は完全一致 →
大文字小文字無視 → 部分一致の順に解決し、複数候補に当たったら黙って1つ選ばず候補を出して落とす。
名前 → ID の解決は `data/toggl/focus_projects.json` のキャッシュで行い、**キャッシュに無い名前を
引いたときだけ**取り直す（`--refresh-projects` で明示更新）。Track の `projects.json` とは
ID 体系が別なので混ぜない。2.0 のプロジェクトは archived の情報が返らないので絞り込まない。
`open` は `https://focus.toggl.com/` を開くだけ（個別画面の URL は未確認）。

**タグは名前でなく ID（`tag_ids`）でしか付かない。** タグ一覧の API は見つからなかったので、
`fetch-focus` が取得したエントリの `tags`（`{id, name}`）から名前 → ID の対応を
`data/toggl/focus_tags.json` に貯める（既存の対応は縮めない）。`start -t` と push はこれを引き、
**引けないタグがあれば投入せず（push は台帳にも入れず）次回へ回す。** タグ無しで投入して
「投入済み」になると直せず、`auto` タグで push 分を見分ける events の判定も壊れるため。

計測は `POST /tracking/start`（`type: "activity"`・`description`・`project_id`・`tag_ids`。
開始時刻はサーバが決める）、`GET /tracking/current`（計測中が無ければ 204）、
`POST /tracking/stop`（`{"end": <UTC RFC3339>}`）。計測結果は CSV に直接書かず、次回の
`fetch-focus` で入る（`focus.build_dataframe` は duration が無い/負の行を除外する）。

`scripts/toggl.py push` は Google Health 睡眠（昼寝含む）と Google Health の運動セッション
（サイクリング・筋トレ・瞑想）、Muse で測った瞑想の回（satoru の `logs/session_log.csv`）を
2.0 のタイムエントリとして書き込む。書き込みも
30req/h と仮定して `--max-writes`（既定10）で抑え、超過分は捨てずに次回へ繰り越す。
402 はクォータ超過として止まる。

**冪等性は「台帳」と「`focus_entries.csv` の照合」の2つだけ。**

1. `data/toggl/focus_pushed.csv`（列は `pushed.csv` と同じ）に `(source, source_id)` があれば投入済み
2. `focus_entries.csv` に、**同じプロジェクト名で start の差が60秒以内**のエントリがあれば投入済み。
   2026-10-27 の migrate でコピーされた auto エントリや、手で入れたものを二重にしないため
3. Muse の回（`satoru_meditation`）だけは、「瞑想」の既存エントリと**区間が1秒でも重なれば**投入しない
   （端が接するだけは重ならない扱い）。Muse の行は session-review の後に届く後発なので、
   同じ回が Fitbit の YOGA や手入力で先に入っていればそちらを残す。start が60秒以上ずれる
   ので2では拾えない

push が作ったエントリはその場で `focus_entries.csv` にも書く（次の fetch を待たずに2を効かせる）。
Track 時代にあった「台帳にあるが CSV に居ないものを手動削除とみなして再投入する」経路
（`fetch_window` / `fetched_at` / `confirm_deleted` / `fetch_state.json`）は**持たない**。
二重投入の事故が2回あった経路で、Focus には fetch 窓の記録も無い。したがって
**2.0 側で消した push 分は再投入されない**（台帳に残るため）。再投入したいときは台帳の行を消す。

**初回は `fetch-focus --start-date 2026-10-27` で `focus_tags.json` を作ってから push する。** 日次の `--days 2` の窓に `auto` タグのエントリが無いと対応が貯まらず、push は `auto` を引けずに全件見送る（見送りは警告に出る）。

`CUTOVER_DATE` より前に start がある Interval は警告を出して対象から外す（migrate でコピー済み）。
プロジェクトまたはタグを引けない Interval は投入せず、書き込み上限の枠も消費しない。
`focus_entries.csv` が無い/空、または投入対象の開始を覆っていないと、照合ができず二重になりうるので
警告する（`push --since` の前に `fetch-focus --start-date` で取り直す）。

**秒未満を含む時刻は避ける。** Health Connect 由来の運動セッションはミリ秒付きで届くので、
`build_payload` で秒に丸め、UTC の RFC3339（`...Z`）にして渡す。

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
`OUTDOOR_BIKE`/FITBIT と `BIKING`/HEALTH_CONNECT）。素通しすると 2.0 に同じ
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

## Toggl 2.0（Focus API）

Track v9 の `/me/time_entries` には 2.0 に書いたエントリが返らないので、
`toggl.py fetch-focus` が Focus API（`https://focus.toggl.com/api`、`Authorization: Bearer`）
から別に取り、`data/toggl/focus_entries.csv` へ保存する（`lib.toggl.focus`）。
日次は `fetch-focus` → `push` の順（`daily-fetch.sh`）。

書き込みの形（2026-11-02 に実測。base は
`/organizations/{org}/workspaces/{ws}`）:

| 用途 | リクエスト | 応答 |
|---|---|---|
| 作成 | `POST /time-entries`。`type: "activity"`（**必須**。無いと 400）・`start`（UTC RFC3339）・`duration`（秒）・`description`・`project_id`・`tag_ids` | 201 とエントリ |
| 削除 | `DELETE /time-entries/{id}` | 204 |
| プロジェクト一覧 | `GET /projects?page=N&per_page=100`（上限100、200は400、既定20件） | 配列 |
| 計測開始 | `POST /tracking/start` | 200 とエントリ（duration 無し） |
| 計測中 | `GET /tracking/current` | 無ければ 204 |
| 計測停止 | `POST /tracking/stop` `{"end": ...}` | 200 とエントリ |

- **タグは `tag_ids` でしか付かない。** `tags: ["auto"]` / `tag_names` / `tags: [{name}]` は
  201 が返るのにタグが空になる（黙って落ちる）。一方 `GET /time-entries` の各エントリは
  `tags: [{id, name}]` を持つ
- 書き込みでもクォータのヘッダは返らない

- **`include_taskless=true` を付けないと task 無しのエントリが返らない。** 手動エントリは
  ほぼ task 無しなので、外すと黙って大半を取り逃す
- **`stop` フィールドが無い。** `start + duration` で計算する。計測中の表現は未確認なので
  `duration` が None / 負値のものを除外している
- **id・project_id は Track と別の体系**（同名プロジェクトでも ID が違う）。だから
  `time_entries.csv` には混ぜない（id の `keep='last'` マージで重複・取り違えが起きる）。
  マージ・窓内置換のロジックは `store.save_merged(csv_path=...)` を共有する
- **migrate は一回きりのコピーで同期ではない。** 2026-10-27 の migrate までの Track の
  エントリ（auto タグの睡眠・サイクリング含む。例: 2026-10-05）は 2.0 にも別 ID で
  存在するが、その後 Track へ push したもの（例: 2026-10-28 の睡眠）は 2.0 に無い（push を Focus へ
  移したのはこのため）。両ファイルを素で足すと移行済みの期間が二重になるので、
  冒頭の区切り日で切る
- `date_from` / `date_to` は必須。JST の暦日を UTC の RFC 3339 に変換して渡す。
  ページ送りは `page`（1始まり）/ `per_page`（最大100）
- organization を列挙する API は無い。`/users/me/settings` の
  `tos_ack_decoupled_licenses` のキーが organization_id（`.env` の
  `TOGGL_FOCUS_ORGANIZATION_ID`）。workspace_id は Track と同じ値
- 2026-10-28 時点でクォータのヘッダは返っていない（Free プラン。docs 上 30 req/h、
  超過は 402）。ヘッダが付けば残量をログへ出す
