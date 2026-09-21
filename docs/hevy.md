# Hevy（筋トレのセット記録・体のサイズ）

筋トレの**セット粒度**（種目・重量・reps・RPE）と**腹囲**の唯一の経路。
セッション粒度（実施日時・所要時間）は Health Connect 経由で
`data/googlehealth/exercise.csv` に既に自動で届いており、こちらとは別系統。

## 取得は手動 export が前提

無料版に API は無い。アプリの Export でアプリから Google Drive の
`dailybuild/hevy` フォルダへ保存し、`scripts/hevy.py fetch` がそれを取る。
**export しなければ何も新しくならない。** `daily-routine.sh` から日次で
回す運用で、2日以上古い export は fetch が警告する。警告を無視して回すと
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

## 週次サマリ（`hevy.py show`）

```bash
uv run scripts/hevy.py show            # 既定 8週
uv run scripts/hevy.py show --weeks 12
```

API は叩かず `data/hevy/` の CSV だけを読み、markdown を stdout・ログを stderr
へ出す（`toggl.py show` / `mf.py show` と同じ体裁）。出す数値は3つ:
部位別の週間セット数・種目別 e1RM・腹囲（`waist_cm`）の週次推移。

**部位マッピングは `config/exercise_muscles.yaml` が正本。** 1種目につき
primary の部位を1つだけ持たせる（複合種目の secondary は数えない）。
コードには埋め込まない。**yaml に無い種目は集計から黙って落とさず**、
種目名とセット数を warning として stderr へ出す（ジムを変えて種目が
入れ替わったときの唯一の検出口）。

**e1RM は Epley 固定**（`weight_kg * (1 + reps / 30)`）。1セットごとに算出し、
週次は**その週の最大値**を取る（平均は軽いセットに引っ張られる）。
`weight_kg` が空（自重）のセットは計算から除外する。

記録が1セットも無い週も部位別セット数の表に0として行を出す（トレーニング
しなかった週とまだ export していない週は別物）。腹囲は測定の無い週を
空欄にし、前週の値で埋めない。

## measurement の使い分け

`measurement_data.csv` は体重・体脂肪率と周囲径17項目を持つが、
**使うのは `waist_cm` だけ**。

- **腹囲は Hevy だけが持つ。** Google Health API の44型に周囲径は無く
  （`docs/googlehealth.md` の discovery document で確認）、HealthPlanet の
  体組成計にも測定項目が無い
- **体重・体脂肪率は使わない。** HealthPlanet と Google Health に正本があり、
  こちらは手入力の転記。4経路目として混ぜると出所が分からなくなる
- 周囲径のうち腹囲以外はほぼ空。空欄は未測定であって 0 ではない
