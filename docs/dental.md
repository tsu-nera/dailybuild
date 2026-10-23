# 歯科検診

取得スクリプトは無い。結果票を受け取るたびに、本人が撮った写真から agent が書く。

## data/dental_checkup.csv

縦持ち `date,clinic,item,value,note`。様式が変わっても列が動かないよう、項目は `item` に足す。

- `value` は用紙の記号・選択肢の文言のまま。歯式は `歯式_<FDI番号>` で `○` 処置歯・`/` 健全歯・`C` 未処置歯
- 用紙で空欄の欄は `value` も空にする（歯が無いとは書かれていないので推定で埋めない）
- 用紙に合計欄（健全歯数・現在歯数など）があれば、歯式を数え直して一致を確かめてから書く

## 結果票の写真

転記の根拠として `data/dental_checkup/YYYY-MM-DD_N.jpg` に置く。原寸は git に入れず、
`photo-shrink`（`~/repo/scripts`）で縮めてから置く。
