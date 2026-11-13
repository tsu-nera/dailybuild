# Dawarich（位置の履歴）

位置のライフログを地図で見る・agent が期間で引くためのセルフホストのサービス。
#290 の試用を経て 2026-11-13 に採用した。`scripts/ops/dawarich/`・`scripts/dawarich.py`・`src/lib/dawarich/`。

## 正本は data/、Dawarich の DB は派生物

精度の問題で使わなくなる可能性があるので、Dawarich の DB にしかないデータを作らない。
DB は data/ から作り直せる前提で扱う。

| 入るもの | 正本（private の data/） | Dawarich へ |
|---|---|---|
| スマホの点（GPSLogger の GPX、1日1ファイル） | `data/gpslogger/*.gpx`（`gpslogger.py fetch`、前日分まで） | `import-routes`（日次） |
| Fitbit の GPS 付き運動 | `data/googlehealth/tcx/`（[googlehealth.md](googlehealth.md)） | `import-routes`（日次） |
| サイコンのライド | `data/xoss/fit/`（[xoss.md](xoss.md)） | `import-routes`（日次） |
| Google Timeline の書き出し | Drive（[timeline.md](timeline.md)） | 手動で `POST /api/v1/imports` |
| Swarm のチェックイン | `data/swarm/`（#92） | 手動 |
| UI で直した Place（改名・merge・アーカイブ） | `data/dawarich/places.csv`（`capture-places`、日次） | `name-places` が当て直す |
| 旅行（Trip） | `data/dawarich/trips.yaml`（agent が1件ずつ追記） | rails runner |
| 公式アプリの点（2026-11-12〜13 だけ。アプリは止めた） | `data/dawarich/app_points.csv`（以後は増えない） | mouse にあるのは 11-13 朝に vaio の DB を写した時点まで |

## 配置

```
bv5200（GPSLogger、60秒ごと）→ Syncthing（送信のみ）→ vaio ~/gpslogger/ → 日次で data/ → mouse の Dawarich
```

- **Dawarich は mouse で動かす。** 試用では vaio で動かしていたが、常駐させるほど使わないので 2026-11-13 に mouse へ移し、vaio からは volume・image ごと消した。
  mouse は使っていないと寝るので、`~/repo/scripts/wake-mouse` か HA のボタンで起こしてから開く
- mouse の自動スリープ（`~/repo/scripts/mouse-idle-suspend`）は、app のログに直近2分の外からのリクエストがあれば寝ない。
  公開ポートは DNAT なので mouse 本体の `ss` には接続が出ない。ログで見る
- 記録係は GPSLogger。公式アプリは記録しない（止めてある）。サーバーが寝ている間の点を後で送る保証が無く、
  初日に12時間分が端末に溜まった。GPSLogger 組み込みの Dawarich 送信も失敗時に再送しないので使わない
- mouse がスリープ中は日次の「Dawarich 軌跡」「Dawarich 場所」が失敗する。翌日の日次で追いつく

## 落とし穴

- **初回起動で管理者 `demo@dawarich.app` / `safepassword` ができる**（`db/seeds.rb`）。作り直したら最初に変える
- 自動で更新しない。image は版を固定し、上げるときはリリースノートを読み、db を `pg_dump -Fc` してから
- **import 名で二重投入を判定する。** 同じ名前で POST すると Dawarich は時刻を足した別名で受け付ける。
  上げる前に `GET /api/v1/imports` と突き合わせる（`import-routes` がやっている）。API に import の削除は無い（rails runner で消す）
- watched フォルダは同じファイル名を二度と取り込まない。伸び続ける当日の GPX は置かない
- **取り込みを消しても、そこから作られた Visit は消えず取り込み元なしで残る**（`dependent: :nullify`）。入れ替えるときは先に Visit を消す
- **Timeline の取り込みは hierarchyLevel 違いの同じ訪問を残し、Dawarich 自身の滞在判定も同じ時間帯に重なる。**
  Visit の件数・滞在時間を素で集計しない。開始時刻が同じ Visit が2つの Place にあると Place の merge が
  VisitConflict で止まる（削除済みの Visit も判定に入る）。`name-places` が先に `dedupe_visits.rb` で減らす
- **取り込み直すと Place の改名が消える。** DB を一回限りで直さず、`name-places` を取り込みのたびに流す
- 逆ジオコーディングは既定で無効で、場所名は Unknown。外部の提供元に向けると座標が出るので入れていない。
  名前は気になった場所だけ、UI か Places API で付ける
- **日の移動距離はトラックの合計で、同じ走行が出どころの数だけ数えられる。** `import-routes` は TCX・FIT の時間帯にある他の点を消す
- GPSLogger の network / fused の点は数 km 飛ぶ。`import-routes` は飛びを除いた写しを上げ、data/ の GPX は生のまま残す
- 飛行機は分けられない。月合計で日常の移動量を語らない
- 移動手段の判定で running が自転車に勝つので、設定 `enabled_transportation_modes` から running を外してある
- rails runner は `docker compose exec -T app bin/rails runner <file>`（インラインは SQL に混ざって壊れる）。
  `ssh <host> 'bash -s' < script` で流すと `exec -T` が残りの行を stdin から食う。`</dev/null` を付けるか scp してから実行する
- 公式 MCP（`/api/v1/mcp`）は読むだけだが、API キー自体はすべての操作ができる
