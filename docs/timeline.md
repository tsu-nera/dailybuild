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
| `place_id` | Google の place ID。名前は持たない |
| `semantic_type` | `UNKNOWN` `INFERRED_WORK` `HOME` `INFERRED_HOME` `SEARCHED_ADDRESS` など |
| `probability` | 場所の同定の確度（`topCandidate` のもの） |
| `lat` / `lon` | float |

`data/timeline/fetch_state.json` は最後に取り込んだ Drive ファイルの `id` と
`modifiedTime`。CSV を書き終えてから更新する。

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

**場所の名前は解決していない。** `show` の場所は place ID のまま（`HOME` /
`INFERRED_HOME` が1件でもある place は `HOME` と表示）。名前付けは別 Issue。

**place ID と座標は公開しない。** 本人の生活圏が分かるので、コード・テスト・
ドキュメントには架空の値だけを書く。
