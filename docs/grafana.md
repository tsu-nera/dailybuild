# Grafana（週の目標ダッシュボード）

vaio で動く Grafana。週の目標（睡眠・部位別セット数）とデータ鮮度を、Claude のセッション無しで
スマホから見る。claude.ai の Dashboard 試作（`scripts/dashboard/index.html`）は更新に
セッションが要るので、日次で更新されるこちらが本線。

## データの流れ

```
daily-fetch.sh ─ dashboard.py build ─▶ reports/dashboard/*.csv ─▶ nginx(files) ─▶ Infinity ─▶ Grafana
```

- 計算は **`scripts/dashboard.py` に1本**。Grafana では集計も判定もしない（クエリは列の選択と並べ替えだけ）。
  claude.ai 版（同じスクリプトの JSON）と同じ数字になる
- CSV は7本（`nights` `weeks` `sets` `status` `current` `sets_now` `freshness`）。毎日**全上書き**で、
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
- bind mount は `DAILYBUILD_PRIVATE`（既定 `~/repo/dailybuild-private`）の `reports/dashboard` を直接指す
  （`reports` の symlink を docker に解決させない）
- 取得系の merge 後は vaio のコードが自動更新されないので ssh で pull する

## ダッシュボードの編集

**画面での編集を正本にする**（provisioning は `allowUiUpdates: true`）。画面で足したパネルは、agent が
HTTP API で取り出して `dashboards/goals.json` に書き戻して commit する:

```bash
curl -s -u admin:$GF_SECURITY_ADMIN_PASSWORD http://<host>:3000/api/dashboards/uid/goals \
  | jq '.dashboard | del(.id, .version)' > scripts/ops/grafana/dashboards/goals.json
```

## 表示規約

- 欠測は空白（null）。0に潰さない
- 今日（当日の行）は途中。週の平均・合計の比較には使わない
- 良し悪しのスコアや色分けは付けない。目標は列か線で示す

## パネル・指標を足す

1. 計算を `scripts/dashboard.py` に足し、`COLUMNS` に列を足す（CSV に出る）
2. Grafana では Infinity の query で列を選ぶだけにする。集計・今週の選択・達成判定を Grafana に書かない
3. Infinity の query は `type: csv` / `source: url` / `parser: backend` / `format: table` /
   `url: http://files/<name>.csv`、列は `selector` / `text` / `type` を明示する
4. query には `url_options: {method: GET}` を必ず入れる。無いと画面側の Infinity が
   `Cannot read properties of undefined (reading 'method')` で落ち、全パネルが空になる。
   `/api/ds/query` に直接投げると通るので API だけの確認では見つからない（2026-11-07）。
   確認は画面で開くか、ブラウザのコンソールを見る
5. `filterExpression` は `selector` ではなく列の `text` 名で評価する。絞る列も `columns` に入れる
