# Google Health（カフェイン・安静時心拍数・SpO2・体重・体脂肪率）

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

## 安静時心拍数・SpO2

`fetch_googlehealth.py` の `heart_rate` / `spo2` エンドポイント。出力先は既存の
`data/fitbit/heart_rate.csv` / `spo2.csv`（スキーマ据え置き）。

- **`daily-resting-heart-rate` は FITBIT と HEALTH_CONNECT の2系統が同じ日付に
  届く。** FITBIT（`calculationMethod: WITH_SLEEP`）だけが既存 CSV と一致し、
  HEALTH_CONNECT（`com.google.android.apps.fitness`）は約5bpm低い。混ぜると
  存在しない段差になるため、HEALTH_CONNECT へのフォールバックはせず、FITBIT
  点が無い日は欠測のまま残す
- **`daily-oxygen-saturation` の日付は「その夜が始まった暦日」で、既存 CSV
  （起床日）より1日前になる。** 一律 +1 日ではなく、正午〜正午の窓で重なる
  睡眠セッションを引き当て、その `dateOfSleep` を採用して解決している
  （素朴な「開始日=セッション開始日」規則は実測で10日破綻する）
- 日付ズレがあるのは spo2 だけで、他の daily 型（hrv / breathing_rate /
  temperature_skin / active_zone_minutes / heart_rate）は lag 0。
  `test_no_date_lag_in_daily_types` で恒久確認している

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
