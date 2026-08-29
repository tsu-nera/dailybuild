# Google Health（カフェイン・体重・体脂肪率）

## カフェイン摂取

ソースは Caffeine Clock（`com.AWSoft.CaffeineClock`、Android）が Health Connect に
書き込んだ記録。Google Health API の `nutrition-log` から読める
（`fetch_googlehealth.py` の `caffeine` エンドポイント、`data/googlehealth/caffeine.csv`）。
**分析・レポートへの反映は未着手で、今は蓄積だけしている。**

- **単位は grams で返る。** CSV では取り違え防止のため mg に直し、列名にも
  単位を入れてある（`caffeine_mg`）
- マージキーは `exercise` と同じく `id`（19桁の整数。`dtype=str` 必須）
- `nutrition-log` は Cronometer / Fitbit の食事ログ（macros）と同居している。
  `nutrients` に `CAFFEINE` を含む点だけを拾い、`packageName` ではフィルタしない
  （他アプリからカフェインが届いても拾えるように）
- **ページング打ち切りは CAFFEINE 行でなく、ページ内の全 dataPoint の日付で
  行う。** カフェイン記録は疎なので、CAFFEINE 行だけで打ち切り判定すると
  1ページに1件も無いことがあり、判定が効かず全履歴を引いてしまう
- **0件はエラーにしない（`allow_empty`）。** 「飲んでいない/記録していない」が
  正常状態なため。他の Google Health エンドポイントは0件を取得の沈黙故障として
  扱うが、caffeine だけ例外

## 体重・体脂肪率（Google Health 経由）

`fetch_googlehealth.py` の `weight` / `body_fat` エンドポイントで
`data/googlehealth/weight.csv` / `body_fat.csv` に取り込む。

- 既存の `data/fitbit/body_weight.csv` / `body_fat.csv` とも
  `data/healthplanet_innerscan.csv` とも統合しない。bmi が返らない
  （Google は身長を持たない）のと、logId 空間が別物（Fitbit は epoch-ms、
  Google は19桁の dataPoint ID）のため、統合すると同じ列に別空間の ID が
  混在する
- 2025 以降の dataSource は HealthPlanet アプリ（`jp.healthplanet.healthplanetapp`）
  が Health Connect に書いたもので、Fitbit 由来ではない。HealthPlanet 非公式API
  が落ちたときの予備経路になる
- 体組成の計測は数日〜週おきで疎なので、0件を正常扱いにしてある（`allow_empty`）
- マージキーは `exercise` / `caffeine` と同じく `id`（19桁の整数。`dtype=str` 必須）
