# 持ち物と消耗品の台帳（`data/inventory/`）

dailybuild-private の `data/inventory/` に、持ち物まわりの台帳を全部置く。表示や編集の器（Homebox・Grafana・
将来の Notion など）は替わる前提で、**器を替えても台帳の CSV はここに残る**ようにする。

| ファイル | 1行 | 正本 | 書き手 |
|---|---|---|---|
| `items.csv` | 所持品（買い替える物）1つ | 今は Homebox。ここは日次 export の写し（docs/homebox.md） | `homebox.py`（export） |
| `consumables.csv` | 補充する品目1つ | ここ | agent |
| `purchase_rules.csv` | 店の注文の行 → 品目 の規則 | ここ | agent |

- 補充する物（使えば無くなる）は `consumables.csv`、買い替える物（本・電子機器・服・取り付ける部品）は `items.csv`。
  迷う物は「補充のペースで買っているか」で決める
- もう買わない品目は行を消さず `consumables.csv` の `ended_on` に日付を入れる（`items.csv` の `disposed_on` と同じ考え方）。次に買う頃を出さず、表の最後に回る
- どの台帳も `key` 列で引く。key は変えない（購入履歴・Grafana・器への同期がこれでつながる）
- 店の注文そのものは `data/purchases/<店>.csv`（取り込みスクリプトが書く生データ）。台帳はそれを `purchase_rules.csv` で引く
- 計算（次に買う頃・1kg あたりの値段）は `src/lib/consumables.py` → `dashboard.py` が `reports/dashboard/consumables.csv`
  `consumable_purchases.csv` に出す。器の側では計算しない

## 器を替えるとき

- Homebox をやめてローカルに戻す: `items.csv` の export を止め、以後は agent が `items.csv` を直接書く（正本がここに移るだけで、列と key はそのまま）
- 消耗品を Notion に出す: `reports/dashboard/consumables*.csv` を Notion へ一方向に同期する（Notion のページ id は同期側で key と対応させる）。
  本人が Notion で直すようになったら、Homebox と同じく Notion を正本にして日次でここへ書き戻す
