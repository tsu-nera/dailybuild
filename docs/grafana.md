# Grafana（人が見るレポート画面）

vaio で動く Grafana。日次レポート（body / sleep / mind の markdown）に代わる人の画面で、
Claude のセッション無しにスマホから見る。claude.ai の Dashboard 試作（`scripts/dashboard/index.html`）は更新に
セッションが要るので、日次で更新されるこちらが本線。

## 画面

ジャンルごとのフォルダに分ける。JSON は `scripts/ops/grafana/dashboards/<ジャンル>/<uid>.json` に置き、ディレクトリ名がそのまま
Grafana のフォルダになる（provisioning の `foldersFromFilesStructure`）。フォルダはファイルの置き場所で決まるので、画面の UI では移さない。
各画面はタグ `dailybuild` とジャンルのタグ（`health` / `habits` / `money` / `home`）を持ち、上部の「健康 ▾ 習慣 ▾ お金 ▾ 暮らし ▾」のドロップダウン
（ジャンルのタグで引くリンク）で行き来する。リンクは `keepTime: false`（画面ごとに既定の期間が 6時間〜20年と違い、引き継ぐと週の目標の6時間で Mind 等の時系列が空になる）。画面を足すときはジャンルのディレクトリに置き、タグとリンクを既存の画面と揃える。
ジャンルを足すときは全画面の `links` に1つ足す（ドロップダウンは画面ごとに持つ）。

`habits` は習慣ごとの画面（瞑想・筋トレ・早起きなど）を置く場所で、`health` は体の状態（Body / Sleep / Mind）を見る場所。
2026-11-14 に週の目標を `health` から移した（uid は変えていないので `/d/goals` のリンクはそのまま）。

| uid | フォルダ | 画面 | 中身 | 既定の期間 |
|---|---|---|---|---|
| `goals` | habits | 週の目標 | 今週の睡眠・入床/離床の達成・負債・部位別セット数・データ鮮度 | 週単位の表 |
| `body` | health | Body | 体重・除脂肪量・筋肉量・体脂肪率・体水分率・FFMI・サイクリング・筋トレ・今週の部位別セット数・タンパク質 | 90日 |
| `sleep` | health | Sleep | 睡眠時間・負債・入床/起床・ステージ・効率・入眠潜時/起床後臥床・中途覚醒 | 30日 |
| `assets` | money | 資産（B/S） | 今日時点の資産の内訳・資産の推移（積み上げ）・持ち物の中古相場と買値の差（`lib/assets.py`） | 12年 |
| `consumables` | home | 消耗品 | 一覧。手放していない品目の分類・次に買う頃・尽きる頃・月額・最終購入。分類は見出しで絞り込める。品名をクリックすると詳細へ（台帳は docs/inventory.md） | 表のみ |
| `consumable-detail` | home | 消耗品の詳細 | 1品目の次に買う頃などの数字・1単位あたりの値段（店ごと）・購入履歴・台帳の欄。`?var-item=<key>` で開く（品目を指定しないと最初の品目） | 20年 |
| `mind` | health | Mind | HRV / RHR（ベースライン ±1SD の帯）・呼吸数・SpO2・歩数・朝の主観4指標 | 30日 |

`body` `sleep` `mind` は時系列で、期間は右上の時間範囲で変える（`daily.csv` は直近365日、`metrics_daily.csv` は全期間）。
日付だけの CSV を UTC 0時として読むので、3画面の timezone は `utc`（`browser` にすると日付が9時間ずれて見える）。
期間の終わりは `now+1d` にする。`now` だと当日の行（UTC 0時＝JST 09:00）が JST 09:00 まで範囲の外になり、朝の取得分が見えない。

日次レポートから移さなかったもの（2026-11-10、#255）:

- 心拍ゾーン（Z1〜Z5・Zone2）: 日次レポートでも全日 `-`。Zone2 目標は廃止済み
- カロリー分析（Balance / In / Out / TEF / EAT）: 摂取カロリーの記録が疎で、体重トレンドを kcal に換算しない方針
- 皮膚温Δ・深部体温・血圧: 疎で、日次の判断に使っていない。必要なら `scratch` で足す
- HRV の深睡眠 RMSSD・SpO2 / 呼吸数のベースライン: 判断に使っているのは HRV（日次）と RHR のベースラインだけ
- 睡眠中の心拍分析（Dip 率・最低心拍の時刻）・睡眠サイクル・栄養と睡眠: sleep レポート固有の探索用の節で、日次レビューの判断に使っていない

## データの流れ

```
daily-fetch.sh ─┬ dashboard.py build ─────▶ reports/dashboard/*.csv ─┬▶ nginx(files) ─▶ Infinity ─▶ Grafana
                └ journal_skeleton.py ───▶ reports/metrics_daily.csv ─┘
```

nginx が配るのは次の CSV（`http://files/<name>.csv`）。設定は `scripts/ops/grafana/nginx/default.conf`。

| CSV | 作り手 | 用途 |
|---|---|---|
| `nights` `weeks` `sets` `status` `current` `sets_now` `freshness` | `dashboard.py` | 週の目標画面 |
| `assets` `assets_now` `goods` | `dashboard.py` | お金の画面。MF の資産推移＋持ち物の中古相場（`data/inventory/market.csv`）。相場の無い物・相場の履歴が始まる前は空セル |
| `daily` | `dashboard.py` | Body / Sleep / Mind 画面。`metrics_daily.csv` に無い計算（FFMI・ステージ・負債・ベースライン帯・運動・タンパク質）を直近365日ぶん |
| `metrics_daily` | `journal_skeleton.py` | 日次の全指標（列は CLAUDE.md の「日次で生成する派生データ」）。対話で足すパネルの材料 |

`reports/` の他のファイル（journal の md など）は mount はされるが配らない（nginx の `alias` で1本だけ出す）。
`events.jsonl` は配らない。Infinity は JSON Lines を読む parser を持たず、確かめられていない（2026-11-10）。

- 計算は **`scripts/dashboard.py` に1本**（`metrics_daily.csv` は `journal_skeleton.py`）。Grafana では集計も判定もしない（クエリは列の選択と並べ替えだけ）。
  claude.ai 版（同じスクリプトの JSON）と同じ数字になる
- `dashboard.py` の CSV（上の表）は毎日**全上書き**で、
  `data/` には置かない。欠測は0でなく空セル
- `current.csv` は「今週」の1行（先週の値は `prev_` 接頭辞、`gap_h = total_h - goal_h`）。
  Grafana の filter 式で今週を選ばせると判定がダッシュボード側に入るので、今週・先週の選択は dashboard.py がやる
- 目標値は `config/targets.yaml`（`bed_time` / `rise_time` / `sleep_debt_h`）と
  `config/exercise_muscles.yaml` の `weekly_sets`。ダッシュボード JSON に目標を直書きしない（`status.csv` を参照）。
  例外は夜ごとの睡眠時間の 7h の参照線だけ（`status.csv` の `sleep_per_night_h` と同じ値）

## 起動・更新（vaio）

```bash
cd ~/repo/dailybuild/scripts/ops/grafana
cp .env.example .env   # GF_SECURITY_ADMIN_PASSWORD と GRAFANA_BIND（tailnet の IP）を編集
docker compose up -d
docker compose pull && docker compose up -d   # イメージ更新
```

- アクセスは tailnet の `http://<vaio の tailnet IP>:3000`。匿名閲覧は無効。nginx（`files`）はホストのポートを開けない
- bind mount は `DAILYBUILD_PRIVATE`（既定 `~/repo/dailybuild-private`）の `reports/dashboard` と `reports` を直接指す
  （`reports` の symlink を docker に解決させない）
- 取得系の merge 後は vaio のコードが自動更新されないので ssh で pull する

## ダッシュボードの編集

**画面での編集を正本にする**（provisioning は `allowUiUpdates: true`）。画面で足したパネルは、agent が
HTTP API で取り出して `dashboards/<ジャンル>/<uid>.json` に書き戻して commit する:

```bash
curl -s -u admin:$GF_SECURITY_ADMIN_PASSWORD http://<host>:3000/api/dashboards/uid/<uid> \
  | jq '.dashboard | del(.id, .version)' > scripts/ops/grafana/dashboards/<ジャンル>/<uid>.json
```

## 対話で足すパネル（scratch）

「この期間だけこれを見たい」は、正本の画面に足さず `scratch` ダッシュボード（uid `scratch`）に置く。

- agent が HTTP API（`POST /api/dashboards/db`）で直接書く。**commit しない**（`dashboards/` に置かない）
- 材料は主に `metrics_daily.csv` の列。Grafana では列を選ぶだけで、集計・判定は書かない（下の「パネル・指標を足す」と同じ規約）
- 期間は Grafana の時間範囲（URL の `from` / `to`）で指定し、パネルに日付を直書きしない
- 要らなくなったら `DELETE /api/dashboards/uid/scratch` で消す。残したいパネルは正本のダッシュボードへ移し、上の手順で JSON を取り出して commit する

## 表示規約

- 欠測は空白（null）。0に潰さない
- 今日（当日の行）は途中。週の平均・合計の比較には使わない
- 良し悪しのスコアや色分けは付けない。目標は列か線で示す

## パネル・指標を足す

1. 計算を `scripts/dashboard.py` に足し、`COLUMNS` に列を足す（CSV に出る）。新しい画面の表は `GROUPS`（対応表）に1グループ足す（サブコマンドを増やさない。`build --only <グループ>` で作り直せる）
2. Grafana では Infinity の query で列を選ぶだけにする。集計・今週の選択・達成判定を Grafana に書かない
3. Infinity の query は `type: csv` / `source: url` / `parser: backend` / `format: table` /
   `url: http://files/<name>.csv`、列は `selector` / `text` / `type` を明示する
4. query には `url_options: {method: GET}` を必ず入れる。無いと画面側の Infinity が
   `Cannot read properties of undefined (reading 'method')` で落ち、全パネルが空になる。
   `/api/ds/query` に直接投げると通るので API だけの確認では見つからない（2026-11-07）。
   確認は画面で開くか、ブラウザのコンソールを見る
5. `filterExpression` は `selector` ではなく列の `text` 名で評価する。絞る列も `columns` に入れる。空欄は `== ""` で引ける（`== null` は全行落ちる）
6. 時系列パネルは `date` 列を `type: timestamp`・`timestampFormat: 2006-01-02` で読み、ダッシュボードの timezone を `utc` にする
7. 一覧→詳細は、一覧の表の列に data link（`/d/<詳細の uid>?var-item=${__data.fields.key}`）を付け、詳細は変数で絞る。key 列は override の `custom.hidden` で隠す。変数の表示名と値を分けるには Infinity の列の `text` を `__text` / `__value` にする（`consumables` → `consumable-detail`）
