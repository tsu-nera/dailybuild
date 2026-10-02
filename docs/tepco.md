# くらしTEPCO web（電力使用量）

`scripts/tepco.py fetch` が 30分ごとの使用量を `data/tepco/usage_30min.csv`
（`date, time, kwh` の縦持ち）に蓄積する。認証と API の仕組みは
`src/lib/tepco/client.py` の docstring を参照。

## 運用

**取得は mouse で週1回、`/weekly-review`（Step 2.9）が手動で走らせる。** 日次取得は vaio
だけが走らせるが、TEPCO はその唯一の例外: セッションが1時間もたたず無人取得できず、
ログイン方式も 2026-11 に変わる。30分値は約2年残るので週1回で足りる。vaio は
`data/tepco` を書かないので書き手は mouse のみで、2台書きの衝突は起きない。

`fetch` の既定窓は **CSV の最終日から今日まで**（最終日は部分日かもしれないので取り直す。
CSV が無い・空なら直近7日）。`--days` / `--since` は明示指定が優先。重複範囲を取り直しても
`store.save` は新データにある (date, time) だけを置換し、他の行は消さない。

## 落とし穴

- **欠測は行を作らない。** 値の無いコマは API が `billingStatus: 00` で
  `usedInfo` ごと落として返す。0kWh で埋めると未計量が実測ゼロに化ける。
  TEPCO 側で単発のコマが欠けることもある（2026-09-30 12:30/13:00）
- **30分値は約2年で消える。** 2026-10 時点で 2024-10 は取れて 2024-06 は
  取れない。fetch が落ち続けると取り直せなくなる
- **引越しで契約番号が変わる。** 取得対象は画面で選択中の契約（SPA が最初に
  叩く billing の `contractNum`）。旧居の契約（2026-04 以前）は取得していない
- **既定の headless では動かない。** SPA が白画面で止まり silent auth が
  走らない。`channel='chromium'`（new headless）が必須
- **2026-11 上旬にログイン方式が変わる**（パスキー、またはパスワード＋
  認証コード）。保存済みセッションで silent auth が通り続けるかは未確認。
  `NotLoggedInError` が出たら `fetch --login` で取り直す
