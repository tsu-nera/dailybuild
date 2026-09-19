# Hevy（筋トレのセット記録・体のサイズ）

筋トレの**セット粒度**（種目・重量・reps・RPE）と**腹囲**の唯一の経路。
セッション粒度（実施日時・所要時間）は Health Connect 経由で
`data/googlehealth/exercise.csv` に既に自動で届いており、こちらとは別系統。

## 取得は手動 export が前提

無料版に API は無い。アプリの Export でアプリから Google Drive の
`dailybuild/hevy` フォルダへ保存し、`scripts/hevy.py fetch` がそれを取る。
**export しなければ何も新しくならない。** 週1回（土日）の `/weekly-review` で
回す運用で、8日以上古い export は fetch が警告する。警告を無視して回すと
「今週トレーニング0回」と欠測が区別できない。

```bash
uv run scripts/hevy.py fetch
```

- `data/hevy/workouts.csv` ← `workout_data.csv`（export をそのまま保存し、
  読み取り時に `lib/hevy_csv.py` でパースする）
- `data/hevy/measurements.csv` ← `measurement_data.csv`（日付を ISO に直して保存）

export は**毎回全件**なので取得は単純置換でよい。マージのキー設計は要らない。
ただし置換は取り返しがつかないので、**新しい export の方が行数が少ないときは
書き込まずに落とす**（`--force` で明示的に上書きできる）。

## 落とし穴

**Drive は同名ファイルを上書きせず別 ID で並べる。** export のたびに
`workout_data.csv` が増える。取得側は `createdTime` の降順で先頭を採る。
名前では1件に決まらない。

**親フォルダは service account から見えない。** 共有されているのは `hevy`
フォルダだけで、親の `dailybuild`（`gdrive.folder_id`）は 404 になる。
名前でパスを辿れないので `gdrive.hevy_folder_id` に ID を直接持つ。
なお `gdrive_client.authorize()` 側（本人の OAuth）は `drive.file` スコープで、
**このアプリが作っていないファイルは list にも出ない**（0 件で正常終了する）。
読み取りは service account 側で行う。

**日時の月名はアプリの表示言語で変わる。** `"13 Dec 2025, 15:11"` と
`"5 9月 2026, 20:39"` が同じ列に入りうる。パースできない値は NaT にせず
例外にする（日付の無い行を落とすと、その週のセットが黙って消える）。

**種目名も表示言語で変わる。** 英語だった時期の種目名（`Chest Press (Machine)`）は
日本語へ置き換わっている。種目名をキーにした対応表は言語切り替えで全滅する。

**同じ種目が表記ゆれで複数に割れる。** `ベンチプレス (ダンベル)`（半角括弧）と
`ベンチプレス　（ダンベル）`（全角括弧）が別種目として登録されている。
集計は黙って2つに分かれ、エラーは出ない。

**RPE は 2026-09-15 から。** それ以前のセットは全て空欄。空欄は 0 ではなく
未記録なので、平均や推移に 0 として混ぜない。

## measurement の使い分け

`measurement_data.csv` は体重・体脂肪率と周囲径17項目を持つが、
**使うのは `waist_cm` だけ**。

- **腹囲は Hevy だけが持つ。** Google Health API の44型に周囲径は無く
  （`docs/googlehealth.md` の discovery document で確認）、HealthPlanet の
  体組成計にも測定項目が無い
- **体重・体脂肪率は使わない。** HealthPlanet と Google Health に正本があり、
  こちらは手入力の転記。4経路目として混ぜると出所が分からなくなる
- 周囲径のうち腹囲以外はほぼ空。空欄は未測定であって 0 ではない
