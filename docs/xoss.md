# XOSS G+ Gen2（サイコン）

ロードバイクのライドの距離・時刻・軌跡の正本。`scripts/xoss.py`・`src/lib/xoss/`。

## 取得経路

- **BLE だけ。** USB はストレージとして見えない（`lsusb`・カーネルログに出ない）
- `ble_sync.py` は [ekspla/xoss_sync](https://github.com/ekspla/xoss_sync) の `xoss_sync.py`
  （commit `e2d76794d8d0ec88ccab5889034a6f9f64f5977b`、MIT）の vendoring。改変箇所はファイル冒頭に列挙してある。
  上流を更新するときは commit を差し替えて改変を当て直す
- **一覧は Gen2 だと `workouts.json`**（`[名前の時刻, サイズ, ?]` の配列）。`filelist.txt` を要求しても何も返らない。
  旧機種向けに `filelist.txt` へ戻る分岐も残してある
- 上流はサイズが合わなくても保存してしまう。`xoss.py fetch` は一覧のサイズと突き合わせ、
  不一致・取れなかった FIT は**保存せず**非ゼロ終了する（保存すると次回以降ずっと skip される）
- 日次（`daily-fetch.sh`）には入れない。サイコンは vaio の近くに無く、取り込みは iiyama で手動

## データ

| ファイル | 中身 |
|---|---|
| `data/xoss/fit/*.fit` | 生の FIT。**正本**。消さない |
| `data/xoss/rides.csv` | session の要約。FIT から作り直せる（`xoss.py import data/xoss/fit`） |

- 本体の容量は 8 MB（2026-11-13 時点で空き 6044/8104 KB）。いっぱいになると古い FIT が消えうるので、
  `rides.csv` は upsert のみで入力に無い行を消さない
- ファイル名の時刻は **JST**、FIT の時刻は **UTC**。`rides.csv` は tz-aware の JST（+09:00）で持つ
- **使えない値**: 心拍センサーが無いと `avg_heart_rate` / `max_heart_rate` は 0 が入る（実測の 0 ではない）。
  `avg_altitude` は -500.0 の無効値。どちらも要約に入れない
- 要約は session メッセージだけを読む。session が無い FIT は行を作らず警告する（0 km を捏造しない）

## Dawarich

`scripts/dawarich.py` の `ROUTE_GLOBS` に `data/xoss/fit/*.fit`、`PRECISE_SUFFIXES` に `.fit` がある。
FIT の時間帯にある GPSLogger・アプリ・Timeline の点は `import-routes` が消す。
Fitbit の TCX とサイコンの FIT は同時に記録しないので、両者の間に優先順位は無い。
Dawarich の Fit::Importer が XOSS の FIT を読めるかは実機で未確認。
