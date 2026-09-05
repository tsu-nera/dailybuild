# Google Health（カフェイン・栄養・安静時心拍数・SpO2・体重・体脂肪率・運動・intraday）

## 活動量（activity）

`data/fitbit/activity.csv` は Issue #50 の型別方針で **(b) 全再取得**（Google に統一）を選んだ
（#50 の型別リストに `activity` が抜けていたのを埋めた形）。2025-11-27〜2026-09-05 の全 283 日を
Google で取り直した（#120）。正典コマンド:

```
uv run python scripts/fetch_googlehealth.py --endpoint activity \
    --start-date 2025-11-27 --end-date 2026-09-05 --allow-history-rewrite
```

- **再取得には `--allow-history-rewrite` が要る**（`HISTORY_BOUNDARY = 2026-06-01`）
- `fetch_activity` は steps / distance / active-minutes / total-calories の4型を1エンドポイントで
  まとめて叩く実装で、そもそも列単位では分離できない。`steps` / `distance` / `*ActiveMinutes` も
  `caloriesOut` と同時に取り直した
- **段差は `caloriesOut` だけだった。** 再取得前に想定していた steps / distance /
  `*ActiveMinutes` の折れ目は無かった（2026-08-25 より前の旧 Fitbit 期間、部分日行36行を
  除いた201日で比較）:

  | 列 | Δ（Google − Fitbit）中央値 | 備考 |
  |---|---|---|
  | caloriesOut | -93.5 kcal | 201日中196日でGoogleが低い。系統差 |
  | steps | -24 | 平均+63.7。中央値は小さく系統差ではない |
  | distance | 0.000 | 非0の日122/201だが中央値0 |
  | lightlyActiveMinutes | 0 | 非0の日155/201、中央値0 |
  | fairlyActiveMinutes | 0 | 非0の日**1**/201 |
  | veryActiveMinutes | 0 | 非0の日**1**/201 |

- **由来は端数の有無で判別できる。** Google は `total-calories` の `kcalSum`（float）を
  そのまま入れ、Fitbit は整数を返す。再取得後は `caloriesOut` の全283行が端数あり
  （= 全て Google 由来）
- 段差が生まれた仕組み: `daily-routine.sh` は Fitbit → Google の順に同じ CSV を書くので、
  取得窓（`--days`）に入った直近日は必ず Google が後勝ちし、窓から外れた過去は Fitbit 値の
  まま凍結される。この境界が毎日1日ずつ前進していた（折れ目 2026-08-25）
- `activityCalories` / `sedentaryMinutes` は Google に対応型が無い（#82）が、**再取得しても
  過去の Fitbit 値は消えない**（`merge_csv` のセル単位マージ。実測でも変更0行）。非空の
  最終日は 2026-09-03。列は履歴保持のため残し、レポートは `active_minutes`（light/fairly/very
  の合成）を使う
- 副次的に部分日行（#70、`caloriesOut` が極端に低い行）が36行→1行（当日のみ）に解消された。
  ただし**当日の行が部分日になる構造そのものは変わっていない**ので #70 は閉じない
- `sedentary-period` は叩かない（Google の定義が Fitbit の `sedentaryMinutes` と違う。詳細は
  `fetch_activity` の docstring）

## 運動（exercise）

`fetch_googlehealth.py` の `exercise` エンドポイントで
`data/googlehealth/exercise.csv` に取り込む（#83）。Toggl push
（`lib/toggl/sources.py`）とレポート3経路（body / mind / circadian）は
`lib/exercise_source.py` を共通の入口として使う。

- **同じ運動が platform 違いで二重に届く。** FITBIT（Charge 6）と
  HEALTH_CONNECT（Google Fit 経由の Hevy 等）が、ほぼ同じ時間帯を別
  セッションとして返す（2026年実測で74組）。時間が重なったら
  `PLATFORM_PRIORITY = ('FITBIT', 'HEALTH_CONNECT')` の優先度が高い方だけを
  残し、`OVERLAP_THRESHOLD_SEC = 60` 秒を超える重なりだけを同一セッション
  とみなす。重なっていないセッションは platform に関係なく両方残す
  （Fitbit を外したときに Health Connect 側で穴が埋まらないように）
- **優先度・閾値は `exercise_source.py` のモジュール定数に固定してあり、
  `config/toggl_push.yaml` からは読まない。** consumer（push / レポート）
  ごとに yaml キーを持たせると、片方だけ設定がずれても誰も気づけないため
- `data/fitbit/activity_logs.csv`（Fitbit Web API 由来、2025-12-03〜）とは
  **統合しない。** id 空間が別物（Fitbit の logId と Google の dataPoint
  id）、`activeZoneMinutes` の構造が別（dict の JSON 文字列 vs 数値）、
  距離の単位系が別（Mile 混在 vs m）。Fitbit Web API 廃止（2026年9月）後
  `activity_logs.csv` は更新が止まるが、削除はせず Fitbit 時代のアーカイブ
  として凍結する。体組成・体重で Fitbit と Google を統合していない前例に
  揃えた形（#48/#66 の駆け込み取得は不要。関連: `docs/googlehealth.md` の
  「体重・体脂肪率」節）
- `exercise.csv` は 2026-01-03〜。日次（最大 `--days N`）・週次インターバル
  （最大8週）のレポート窓はこの開始日で覆える
- マージキーは `caffeine` / `weight` / `body_fat` と同じく `id`（19桁の
  整数。`dtype=str` 必須）
- **`distance_m` はほぼ空。** 実測で埋まっているのは WALKING（175/175）だけで、
  OUTDOOR_BIKE は 1/530、BIKING は 44/140、WEIGHTS・STRENGTH_TRAINING は
  0/43・0/44。レポートはサイクリングの距離を出さない（docs/reports.md 参照）

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

## 栄養（食事ログ）

ソースは Google Health API の `nutrition-log`（`fetch_googlehealth.py` の
`nutrition` / `nutrition_logs` エンドポイント、`data/fitbit/nutrition.csv` /
`nutrition_logs.csv`）。

- `nutrition-log` は**個別食事ログしか持たない**。日次サマリのデータ型は
  存在しない（`nutrition` / `nutrition-summary` / `daily-nutrition` はいずれも
  400）。`nutrition.csv` は `nutrition_logs.csv` の合算で作っている
- 食事ログとカフェインの判別は `foodDisplayName` の有無で行う。
  **id の桁数では判別できない**（同じ Fitbit 由来でも11桁と19桁が混在する）
- `water` は取得元のデータ型が無い（`hydration` / `water` はいずれも400）ため
  常に空欄。0 にすると「水を摂っていない」という嘘になる
- `sodium` は grams で返るので mg に直している
- **未記録日は行を作らない。** 既存 CSV に残る「全項目0の行」は Fitbit 経路が
  書いたもので、摂取0とは限らない（実例: `2026-02-26` は Google では
  1542 kcal だが CSV では 0）
- `mealTypeId` の 1（BREAKFAST）/2（BEFORE_LUNCH）/7（ANYTIME）は実データ
  未確認の推定値。実データで一致を確認したのは 3/4/5/6 のみ
- `unitName`（「グラム」「食分」等）は `food-measurement-unit` 型の単体照会
  （`GET users/me/dataTypes/food-measurement-unit/dataPoints/<unitId>`）で
  解決している。一覧はページングが要るうえ毎回全件引くのは無駄なので、
  未知の unitId のときだけ引きモジュールレベルの dict にキャッシュする

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

## intraday（心拍数・歩数・SpO2・HRV・呼吸数の分刻み、Issue #76）

`fetch_googlehealth.py` の `heart_rate_intraday` / `steps_intraday` /
`spo2_intraday` / `hrv_intraday` / `br_intraday` エンドポイント。既存の
`data/fitbit/*_intraday.csv` と同一スキーマで出力する。daily-* 型と違い
`list` の `filter` クエリパラメータで期間を絞る
（`googlehealth_api.list_filtered_points`）。

- **`filter` のフィールド名は snake_case で完全修飾する。** camelCase は
  `INVALID_DATA_POINT_FILTER_DATA_TYPE_RESTRICTION` で 400 になる。
  **上限（`<`）を付けないと新しい順に返るだけで過去に届かない**（下限だけでは
  ページングが止まらず全履歴を延々引く）
- `physicalTime` は UTC、`civilTime` がローカル（JST, utcOffset=32400s）。
  UTC の暦日で filter を切るとローカル暦日と1日ずれるため、filter の窓は
  ±15時間広く取り（UTC オフセット -12〜+14 のどれでもローカル暦日を覆う）、
  最終的な期間の絞り込みは civilTime の日付で行う
- **steps は4系統が同居し、素で合算すると3.6倍になる。** 実測（JST
  2026-09-01）:

  | dataSource | points | 合計歩数 | 既存CSVとの一致 |
  |---|---|---|---|
  | platform=FITBIT, device.displayName="Charge 6" | 139 | 3267 | 1440/1440 完全一致 |
  | platform=FITBIT, device.displayName="MobileTrack" | 121 | 3276 | 1253/1440 |
  | platform=HEALTH_CONNECT, packageName=…healthconnect.phone… | 39 | 3456 | 1297/1440 |
  | platform=HEALTH_CONNECT, packageName=com.google.android.apps.fitness | 50 | 1863 | 1286/1440 |

  `platform == 'FITBIT'` かつ `device.displayName != 'MobileTrack'` の点だけを
  採用する（MobileTrack は同じ FITBIT platform なので platform だけでは切れない）
- steps は非0区間しか返らないため、既存CSVと同じ1440行/日にするにはゼロ埋めが
  要る。**今日より前は00:00〜23:59の1440分すべて、当日はローカル現在時刻の分
  まで**（未来の分を0で埋めると欠測の捏造になる）。**1点も返らなかった日は
  ゼロ埋めしない**: 保存はキーマージで 0 は「値がある」として既存の実測値を
  上書きするため、取得の沈黙故障（filter の誤り・同期前）が1日ぶんの歩数を
  黙って消す
- **steps は Charge 6 だけでは既存CSVと完全一致しない残差がある。** Fitbit は
  トラッカーに記録が無い分だけ MobileTrack の歩数で埋めており、Google の点から
  は「トラッカーが0を記録した」と「記録が無い」を区別できないため再現できない。
  実測（2026-09-03〜04の2,880分）で不一致は2分・計9歩で、すべて Google < CSV
  の方向。parity テストは完全一致ではなく「Google > CSV が0件（＝二重計上の
  検出）」と「取り逃しが総歩数の1%未満」で見ている
- heart-rate は生サンプル（1〜3秒粒度）を civilTime の分でバケットし、
  **切り捨て平均（`int(mean)`。`round` ではない）** で1分値にする。1日あたり
  約33,000点=約660ページ=約8分かかり、既存CSV起点（2024-12-01）まで遡ると
  約84時間になるため **`fetch_all` から除外し、バックフィルはしない**
  （`--endpoint heart_rate_intraday` で明示指定したときだけ取る）
- br（呼吸数）は1つの civil date に複数点が届くことがあり、deep/rem/full は
  同値でも light だけ揺れる。**civil date ごとに physicalTime が最も早い点を
  採る**とこの揺れが解消する
- hrv は Google 側に `rmssd` しか無く、既存CSVの `coverage`/`hf`/`lf`/
  `lf_hf_ratio` に対応するフィールドが無い。行は `datetime`/`rmssd` だけを
  持たせ、**保存はキーマージ（`merge_csv`）にする**（期間置換にすると
  この4列が丸ごと消える）
- 2021-06 に `oxygen-saturation` / `heart-rate-variability` が0件だったのは
  着用の途切れでも保持期間の限界でもなく、**filter 無しでページングしていた
  ため2021年まで届いていなかっただけの観測アーティファクト**。filter 付きで
  引き直すと2021-06にもデータが存在する
- 日次実行への影響: `--days 2` で intraday 4種（heart_rate_intraday を除く）の
  追加取得は実測で79ページ・約57秒
- parity テスト（`pytest -m net`）の比較窓は**現在時刻ではなく既存CSVの最終行
  から取る**。CSV は最後に取得を回した時点までしか無いので、現在時刻から窓を
  切ると重なりが0件になり `compared == 0` で落ちる。heart-rate は日付単位でしか
  引けず1日約8分かかるので、intraday の net テストは全体で5分以上かかる
