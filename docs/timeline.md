# Timeline（場所ごとの訪問）

Google マップ Timeline の**訪問（visit）**を place ID 単位で取り込む経路。
場所ごとの訪問日数・滞在時間・最終訪問日と、「よく行く場所に新しく入った／
来なくなった」を読むための材料。移動（activity）や経路（timelinePath）は取り込まない。

## 取得は手動 export が前提

Timeline は端末内保存で API が無い。端末からの export が唯一の経路。

1. 端末の Google マップアプリで Timeline の export を実行する
2. できた `タイムライン.json` を Google Drive の `dailybuild/timeline` フォルダへ置く
3. 月1回ほど。**毎回全期間**（現状 2025-03〜）が入る

`daily-fetch.sh` から日次で `scripts/timeline.py fetch` を回すが、Drive 側の
`modifiedTime` が `data/timeline/fetch_state.json` の記録と同じなら何もしない
（数十MBを毎日落とさない）。export しなければ何も新しくならない。

```bash
uv run scripts/timeline.py fetch
uv run scripts/timeline.py names --limit 100
uv run scripts/timeline.py show --start 2026-10-01 --end 2026-10-07
```

フォルダ ID は `config/personal.yaml` の `gdrive.timeline_folder_id`。親フォルダは
service account から見えないので ID を直接持つ（[docs/hevy.md](hevy.md) と同じ事情）。

## 出力

`data/timeline/visits.csv`（1行1訪問）:

| 列 | 中身 |
|---|---|
| `start_time` / `end_time` | export の offset 付き ISO のまま（`2025-03-09T14:46:12.000+09:00`） |
| `duration_min` | 滞在分（小数1桁） |
| `place_id` | Google の place ID。名前は持たない（名前は places.csv） |
| `semantic_type` | `UNKNOWN` `INFERRED_WORK` `HOME` `INFERRED_HOME` `SEARCHED_ADDRESS` など |
| `probability` | 場所の同定の確度（`topCandidate` のもの） |
| `lat` / `lon` | float |

`data/timeline/fetch_state.json` は最後に取り込んだ Drive ファイルの `id` と
`modifiedTime`。CSV を書き終えてから更新する。

## 場所の名前（places.csv）

export に名前は無いので、place ID → 正式名の辞書を Places API (New) の Place Details で
作る。`data/timeline/places.csv`（1行1場所）:

| 列 | 中身 |
|---|---|
| `place_id` | visits.csv の `place_id` |
| `display_name` | 正式名（`languageCode=ja`）。`not_found` は空 |
| `primary_type` | Google の主タイプ。応答に無い場所は空 |
| `status` | `ok` / `not_found` |
| `resolved_at` | 引いた時刻（offset 付き ISO） |

`scripts/timeline.py names [--limit N]`（既定 100）が `daily-fetch.sh` の Timeline の次に走る。
引く対象は次をすべて満たす place ID:

- `places.csv` にまだ無い（`not_found` も含め、一度引いたものは二度と引かない）
- `HOME` / `INFERRED_HOME` が1件も付いていない
- 全期間の訪問日数が2日以上
- 訪問日数の多い順に `--limit` 件まで

`show` は `HOME` > 辞書の名前（`status=ok`）> place ID の順で表示する。`places.csv` が
無くても従来どおり動く。

- FieldMask は `id,displayName,primaryType` の3つに固定。課金の SKU がフィールドで
  決まるので増やさない
- `languageCode=ja` を付ける。付けないと `displayName` が英語表記で返る
- `primaryType` は応答に無い場所がある。空欄で保存する
- `GOOGLE_MAPS_API_KEY`（`.env`）が無いときは warning を出して終了コード0
  （キー用意前でも日次を失敗させない）
- 404 は `not_found` で記録する。それ以外のエラー（認証・クォータ・5xx）は、そこまでに
  引いた分を書いてから非0で終了する
- `places.csv` は実行の最後（またはエラー時）にまとめて書く。既存行は消さず、新しい
  place ID の行だけを足す

辞書は正式名だけを持つ。呼び名・意味づけは gtd 側が place ID で結んで持つ。

## 落とし穴

**同じ訪問が `hierarchyLevel` 違いで重複して出る。** 全 visit のうち約半数が
level 0 で、残りは同じ時間帯を粗く切り直したもの。素で数えると訪問日数・滞在時間が
倍近くになる。`hierarchyLevel == 0` だけを残す。

**座標は度記号付きの文字列。** `"12.34°, 56.78°"` の形で届く。`°` を外して
`,` で分け、float にする。

**`probability` は場所の同定の確度。** 集計が place ID 単位なので
`visit.probability`（訪問の確度）ではなく `topCandidate.probability` を採る。

**時刻は offset 付き ISO のまま保存する。** 訪問日は `start_time` の先頭10文字
（現地日付）で数える。日をまたぐ滞在は開始日に1回数える。同じ日の同じ場所への
複数回の訪問は訪問日数としては1。

**書き込みは期間置換で、古い行は消えない。** `replace_csv_period()` は新しい export に
ある日付の既存行だけを置き換える。export の保持期間が将来短くなっても、
取り込み済みの古い訪問は残る。同じ export を再取り込みしても行は増えない。

**パースに失敗したら CSV にもステートにも触れない。** `semanticSegments` が無い、
visit の必須項目が欠けている export は例外で落とす（欠測を捏造しない）。

**export が古いと警告する（40日）。** 月1回の運用なので、40日を超えて更新が
無ければ export を忘れている。警告を無視すると最近の訪問が丸ごと無いまま
「来なくなった」に見える。

**place ID と座標は公開しない。** 本人の生活圏が分かるので、コード・テスト・
ドキュメントには架空の値だけを書く。
