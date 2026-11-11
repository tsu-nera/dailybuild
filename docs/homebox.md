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
