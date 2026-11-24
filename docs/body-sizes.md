# 体のサイズ（`data/body_sizes.csv`。agent が書く・取得スクリプト無し）

`data/body_sizes.csv` は服・靴・メガネを買うための体のサイズ（胸囲・股下・足長・度数など）。
縦持ち `date,measure,value,unit,source,note` で、測った・伝えられた時に agent が1行足す。
`date` は測った日（不明なら記録した日にして `note` に書く）。身長・腹囲は `data/checkup.csv`
にあるので写さない。物の表記サイズと合ったかは持ち物の note（正本は Homebox、[docs/homebox.md](docs/homebox.md)）に書く。
本人と agent が共に書く置き場は未設計で、具体例が集まったら決め直す（2026-10-18）。
