# 持ち物（Homebox）

持ち物の正本は vaio で動く [Homebox](https://github.com/sysadminsmedia/homebox)（sysadminsmedia の fork。本家 hay-kot/homebox は 2024 に凍結）。本人は UI で、agent は API で同じものを書く（#205・#263）。

| 物 | 場所 |
|---|---|
| 正本 | vaio の Homebox（`scripts/ops/homebox`、tailnet の `:3100`）。データは docker volume `homebox_homebox-data` |
| 写し | dailybuild-private の `data/inventory/items.csv`。日次の「持ち物」ステップが `homebox.py export` で全上書きする |
| 書き込み | `scripts/homebox.py add` / `dispose`（使い方は docstring） |

## items.csv の読み方

- **生成物なので直接書かない**。直しても翌日の export で消える
- 行が無い＝持っていない、ではなく「まだ登録していない」。対象は耐久品のうち、機器とつながる物・計測に効く物・毎日身につける物だけ
- `key` は購入データとの join 用（`amazon:<注文番号>:<ASIN>` など）。UI で足した物は `homebox:<id>`
- `category` は親タグ、`subcategory` はその子タグ。子タグの無い物に親タグが複数あれば `;` で連結する
- 手放した物は `status=disposed` と `disposed_on`。手放し方は `note` の末尾「手放し方: 」
- 写真・添付は入らない。Homebox を失うと写真は戻らない

## 中古相場（任意、2026-11-12〜の実験）

- 全部には付けない。売るかもしれない物にだけ custom field `相場検索` を付ける（`homebox.py market <key> --query '...'`）。書式は gtd の `scripts/shopping/price.py` と同じ引数（品名の語・`--min`・`--exclude`）
- 日次の「中古相場」ステップが、前回から30日空いた物だけメルカリ SOLD（直近90日）の中央値を引く。最新値は custom field `中古相場`、履歴は `data/inventory/market.csv`（1回1行）とメモ末尾の「相場 YYYY-MM-DD: …」
- SOLD が4件未満の日は `median` を空にした行だけ残し、`中古相場` は前の値のまま。品名の表記揺れで0件になりやすい（メルカリでは `Domane AL 2` でなく `AL2`）。照合は NFKC で全角を潰してから行う
- mercapi は非公式 API。取れなかった日はステップが失敗し、行が残らないので翌日引き直す
- custom field の number 型は PUT が 500 になる。`中古相場` は text に円の整数

## 場所とタグ

- 場所の大区分は Home Assistant のエリア名にそろえる（`メイン` / `玄関・キッチン`）。HA のエリアはセンサーのまとまりなので粗く、探す単位としては足りないので、その下に収納の単位（机・クローゼット・シンク下・靴箱など、agent-private `home/room-layout.md`）を置く。持ち出す物は `持ち歩き`（HA のエリア `持ち物` に当たる）
- 場所は分からなければ空のまま。推測で埋めない
- カテゴリ（親タグ）: PC / スマホ / 計測機器 / スマートホーム / 家電 / 家具 / スポーツ用品 / 日用品 / ファッション / おもちゃ。増やすのは本人が決める

## API の落とし穴（0.27.1）

- `GET /entities` は `includeArchived=true` を付けないと手放した物（archived）を返さない。付けずに key の有無を判定すると二重に作る
- `name` は `MaxLen(255)` を UTF-8 の**バイト数**で数える。超えると 500（ログに `validator failed for field "Entity.name"`）。Amazon の商品名はよく超えるので `fit_name` で縮める
- `PUT /entities/{id}` は全欄置き換え。GET の結果を body に戻してから欄を上書きする（`_update_body`）。送らなかった欄は消える
- 場所は 0.26 から entity の一種で、物の `parentId` に場所の id を入れる
- custom field の値は `q` 検索に引っかからない（docs は引っかかると書いているが 0 件だった）。key 引きは一覧＋詳細取得
- タグの `POST` で渡した `parentId` は無視される。作ってから `PUT /tags/{id}` で親を付ける
- 物に埋め込まれたタグには親が載らない（`parentId` が常に空）。親子はタグ一覧から引く
- 通貨はグループの設定（`PUT /groups` の `currency`）。既定は USD で、円の数値に `$` が付く
- 表示言語などのユーザー設定は `PUT /users/self/settings`（`{"language": "ja-JP"}`）

## 運用

- 版を上げるときは release notes を読み、`homebox.py export` を一度流して items.csv の差分を見てから日次に任せる（0.26 で API の形が変わった前例がある）。compose は版を固定している
- `HBOX_AUTH_API_KEY_PEPPER` を変えると発行済みの API key が全部無効になる
