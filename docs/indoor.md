# 室内環境

**室内（`data/homeassistant/`）と外気（`data/weather.csv`）は別物。** どちらにも温度と
湿度が入っているので取り違えやすい。室温を見たいときに外気温を読むと結論が変わる
（睡眠と外気温の関係は既に分析済みで、あれは**外気温であって室温ではない**）。

## Home Assistant（現行）

自宅 HA（vaio 上の Docker）の statistics を5分値で取る。`scripts/fetch_homeassistant.py`
が `daily-fetch.sh` から日次で走る（取得は vaio だけ）。

- 取得対象: `config/homeassistant.yaml` の `statistic_ids`（Nature Remo の室温・湿度・照度、CO2 モニターの CO2・温度・湿度ほか）
- 保存先: `data/homeassistant/statistics_5min/YYYY-MM.csv`（JST の月で分割）
- 列: `start,entity_id,mean,min,max`。縦持ちなのでセンサーが増減しても列は動かない。
  `start` は JST の tz-naive。HA が返した行だけを書き、補間も0埋めもしない
- マージは `(start, entity_id)` で行置換。新データに含まれる月のファイルだけ触り、
  過去の月は書き換えない。取得開始は保存済みの最終 `start` の1時間前
  （保存済みが無ければ `--days`、既定30日）
- **照度は単位が空。** Remo のセンサー相対値であって lux ではない。lux と書かない
- 1 entity が1時間以上の窓で0行なら故障とみなして exit 1（取れた分は保存する）
- 認証: リポジトリ直下の `.env`（`HA_TOKEN` 必須、`HA_URL` 省略時 `http://localhost:8123`。
  環境変数があればそちらを優先）。HA のプロフィール → セキュリティ → 長期アクセストークンを
  dailybuild 用に発行し、iiyama（開発）と vaio（日次取得）に同じ `.env` を置く。`HA_URL` は両機から
  届く tailnet 名（`localhost` だと iiyama から繋がらない）。`.env.example` からは `cp` で作る
  （`git mv` すると追跡対象になり `.gitignore` が効かず token を commit しうる）。
  sqlite は直接読まない（DB 構造は HA 内部のもの）
- HA の recorder は `purge_keep_days: 400` で保持する。取得と保持は HA の仕事
- **抽象化は HA に置く。** センサーを増やすときは HA に入れて `config/homeassistant.yaml`
  に1行足すだけ。取得元ごとの fetcher は作らない。statistics を持たない state 型
  （on/off・文字列・device_tracker の位置）も下の state 履歴で同じく1行で済む

### state 履歴

同じ `fetch_homeassistant.py` が statistics に続けて取る（`daily-fetch.sh` のステップは1つのまま）。
WebSocket の `history/history_during_period`。

- 取得対象: `config/homeassistant.yaml` の `entities`。要素は entity_id の文字列か
  `{entity_id: ..., attributes: [保存するキー]}`。attributes の指定が無ければ保存しない
- 保存先: `data/homeassistant/states/YYYY-MM.csv`（JST の月で分割）
- 列: `time,entity_id,state,attributes`。縦持ち
  - `time` は HA の `last_updated` を JST の tz-naive にしたもの。**マイクロ秒まで残す**
    （同じ entity で秒まで同一の更新が実在する）。`last_changed` でなく `last_updated` なのは
    attributes だけの更新（座標の変化）を落とさないため。同じ理由で significant changes 限定にしない
  - `state` は HA の文字列そのまま。**`unavailable` / `unknown` も捨てない**（端末が止まっていた
    唯一の記録）。自由文字列なので読むときは `dtype=str, keep_default_na=False`
    （既定だと `None` `NA` や空欄が NaN に化ける）
  - `attributes` は指定キーだけの JSON（キー順は yaml の順）。指定外のキーは入らない
- マージは `(time, entity_id)` で行置換。取得開始は state 側 CSV の最終 `time` の1時間前
  （statistics の最終時刻とは共有しない）。長い窓は7日ごとに区切る
- **窓の開始時点の state は保存しない。** 開始時点の state も含めて取るが、HA はその行の
  `last_updated` を実際の更新時刻ではなく要求した start に丸めて返す。保存すると日次実行の
  たびに存在しない更新が1行ずつ増える。この行は存在確認だけに使う
- 存在する entity は開始時点の state で必ず1行返る。**1行も返らない entity は entity_id の誤り
  として exit 1**（取れた分は保存する）。変化0回は失敗にしない（家から出なかった日の
  device_tracker は正常に変化0）
- 更新はイベント駆動で疎ら。行が無い区間は直前の行の state が続いている（0埋め・補間はしない）。
  HA の state 履歴は 2026-10-01 21:15 JST 以降しか無い

## Tuya（2026-09-05 に運用停止・コード削除済み）

凍結ファイル `data/indoor_tuya_2026-08.csv`（2026-08-24〜26、読むコードは無い）は、
Tuya Cloud API から CO2・温度・湿度を5分境界ごとに60秒窓で平均した値。窓が0件の境界は
行が無い（欠測を補間していない）。

取得コード（`fetch_indoor.py` / `tuya_client.py`）は #196 で削除した。同じセンサー
（LSENLTY PTH-9CW）は HA 経由で上の5分値に入っている。Tuya Cloud を直接叩き直す前に
`git log -- scripts/fetch_indoor.py` で旧実装を読む（ログは最大7日しか遡れない・
ログ照会は約2.2秒/点のトークンバケットで1日288点に約11分かかる、が要点）。
