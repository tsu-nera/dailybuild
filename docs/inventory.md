# 持ち物と消耗品の台帳（`data/inventory/`）

dailybuild-private の `data/inventory/` に、持ち物まわりの台帳を全部置く。表示や編集の器（Homebox・Grafana・
将来の Notion など）は替わる前提で、**器を替えても台帳の CSV はここに残る**ようにする。

| ファイル | 1行 | 正本 | 書き手 |
|---|---|---|---|
| `items.csv` | 所持品（買い替える物）1つ | 今は Homebox。ここは日次 export の写し（docs/homebox.md） | `homebox.py`（export） |
| `consumables.csv` | 消耗品の品目1つ | ここ | agent |
| `purchase_rules.csv` | 注文の行 → 品目 の規則 | ここ | agent |
| `stocktake.csv` | 棚卸し1回の1品目（`date, key, quantity, note`） | ここ | agent（本人が言った残量を書く） |

店の注文そのものは `data/purchases/<店>.csv`（取り込みスクリプトが書く生データ）。店頭で買った分は
`data/purchases/store.csv`（`date, order_id, shop, item, quantity, price, jan`。agent がレシートから書く。`price` はレシートの表示価格のまま＝業務スーパーは税抜）。

## 消耗品のデータモデル

一から設計せず Grocy の形を借りる。迷ったら Grocy がどう表しているかを見て写す。

| Grocy | ここ | 決め |
|---|---|---|
| product | `consumables.csv` の品目 | 一般名（「プロテイン」「卵」）。置き換えて使える物は1品目にまとめる（ホエイとソイはどちらも「プロテイン」） |
| product barcode | `purchase_rules.csv` | 銘柄・容量・店ごとの商品を品目に結ぶ。`size` が1注文1個あたりの量 |
| quantity unit | 品目の `unit` | 量と値段を比べる単位。重さは kg、数える物は 個（パックで買う物は1パック=1個） |
| shopping location | 購入の行の `shop` | 店はチェーン・モールの単位（Amazon・楽天市場・マイプロテイン・業務スーパー）。モール内のショップ名は商品名に残す |
| stock_log（purchase） | `reports/dashboard/consumable_purchases.csv` | 生データから毎日作り直す。1注文の行=1行 |
| product の active | `ended_on` | もう買わない品目は行を消さず日付を入れる（`items.csv` の `disposed_on` と同じ考え方） |
| stock の手動補正（inventory） | `stocktake.csv` | その日の終わりに残っていた量（品目の unit）。消費の記録は持たない |

消費を記録して在庫を減らす操作は持たない（手間なので 2026-11-11 にやめた）。全品目で購入間隔の中央値から「次に買う頃」を出す。
棚卸しのある品目だけ、在庫も推定する（2026-11-11 からミックスナッツとオートミールで試行）:

- 1日の使用量 = （最初の棚卸しの量 + その間の購入 − 最後の棚卸しの量）÷ 日数。棚卸しが2回そろうまでは出さない
- その間に量が増えていたら購入の書き漏れなので、使用量を出さない（0 で埋めると減らない在庫を捏造する）
- 推定在庫 = 最後の棚卸しの量 + その後の購入 − 使用量 × 経過日数。尽きる頃はそこから割る
- 棚卸しの日に買った分は、その日の量に含まれている前提（量は「その日の終わり」に数える）

- 補充する物（使えば無くなる）は `consumables.csv`、買い替える物（本・電子機器・服・取り付ける部品）は `items.csv`。
  迷う物は「補充のペースで買っているか」で決める
- どの台帳も `key` 列で引く。key は変えない（購入履歴・Grafana・器への同期がこれでつながる）
- 計算（次に買う頃・1単位あたりの値段）は `src/lib/consumables.py` → `dashboard.py` が `reports/dashboard/consumables.csv`
  `consumable_purchases.csv` に出す。器の側では計算しない
- agent が台帳を書いたら `uv run scripts/dashboard.py consumables` で消耗品の2本だけ作り直す（約3秒。全体の build は約10秒）。日次でも全体の build が作り直す

## 器を替えるとき

- Homebox をやめてローカルに戻す: `items.csv` の export を止め、以後は agent が `items.csv` を直接書く（正本がここに移るだけで、列と key はそのまま）
- 消耗品を Notion に出す: `reports/dashboard/consumables*.csv` を Notion へ一方向に同期する（Notion のページ id は同期側で key と対応させる）。
  本人が Notion で直すようになったら、Homebox と同じく Notion を正本にして日次でここへ書き戻す
