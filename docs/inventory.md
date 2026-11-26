# 持ち物と消耗品の台帳（`data/inventory/`）

dailybuild-private の `data/inventory/` に、持ち物まわりの台帳を全部置く。表示や編集の器（Homebox・Grafana・
将来の Notion など）は替わる前提で、**器を替えても台帳の CSV はここに残る**ようにする。

| ファイル | 1行 | 正本 | 書き手 |
|---|---|---|---|
| `items.csv` | 所持品（買い替える物）1つ | 今は Homebox。ここは日次 export の写し（docs/homebox.md） | `homebox.py`（export） |
| `consumables.csv` | 消耗品の品目1つ | Notion「生活 / 消耗品DB」。ここは日次同期の写し（`location` `keep` `subscription` `ended_on` だけはここが正本） | `notion_consumables.py fetch` |
| `purchase_rules.csv` | 注文の行 → 品目 の規則 | ここ | agent |
| `stocktake.csv` | 棚卸し1回の1品目（`date, key, quantity, note`） | ここ（Notion の `量` が変わった日の行は同期が足す） | `notion_consumables.py fetch`・agent（本人が言った残量を書く） |

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
- 定期購入＝この台帳の品目（野菜は載せない）。月額・年額はサブスクと同じ月割りで、使用量（棚卸し）があれば消費から、無ければ購入実績から出す。購入2回未満の品目は出さない
- 計算（次に買う頃・1単位あたりの値段）は `src/lib/consumables.py` → `dashboard.py` が `reports/dashboard/consumables.csv`
  `consumable_purchases.csv` に出す。器の側では計算しない
- agent が台帳を書いたら `uv run scripts/dashboard.py build --only consumables` で消耗品の2本だけ作り直す（約3秒。全体の build は約10秒）。日次でも全体の build が作り直す
- 品目の追加・名前・分類・単位・量・メモは本人が Notion「消耗品DB」で直す。agent も品目を足すなら Notion に足す（CSV に直接足すと翌日の同期で `ended_on` が付く）

## Notion からの同期（`scripts/notion_consumables.py fetch`、日次）

Notion の列は `品目`(title) `key`(text) `分類`(select) `単位`(select) `量`(number) `メモ`(text) `更新`(last_edited_time)。
読むのは公式 REST API（data source の query）。MCP は日次から呼べないので使わない。

- **key の採番**: `key` が空の行には同期が `n_` + ページ ID の先頭8桁（ハイフン除く）を振り、Notion の `key` 列へ書き戻す。
  既存の key（`protein` など）も振った key も変えない。本人も agent も key を手で決めなくてよい
- **key の重複**: 同じ key が2行以上あれば CSV を書かずに exit 1 し、重複した品目名を stderr に出す。片方の key を Notion で空にすれば次の同期が振り直す
- **Notion が0行**: 何も書かずに exit 1（ページ送りの取りこぼしや API 障害で全品目に `ended_on` が付くのを防ぐ）
- **consumables.csv**: `name`←品目・`category`←分類・`unit`←単位・`note`←メモ は Notion の値で上書きする。
  Notion に無い列（`location` `keep` `subscription` `ended_on`）は CSV の値を保ち、新しい key の行では空
- **Notion から消えた品目**: 行は消さず、`ended_on` が空なら同期した日を入れる
- **stocktake.csv**: `量` が空でない品目について、その key の最後の記録と量が違うときだけ、`更新` を JST の日付にして1行足す（`note` は空）。
  最後の記録が `更新` より後の日付なら足さない（agent が後から書いた棚卸しの方が新しい）。
  同じ量なら足さないので何度流しても増えない

## 器を替えるとき

- Homebox をやめてローカルに戻す: `items.csv` の export を止め、以後は agent が `items.csv` を直接書く（正本がここに移るだけで、列と key はそのまま）
- 消耗品は 2026-11-26 に Notion を正本にした（本人が 11-13 から Notion で直すようになったため）。CSV は写しとして残るので、
  Notion をやめるときは `notion_consumables.py` の日次ステップを外し、以後は agent が CSV を直接書く（列と key はそのまま）
