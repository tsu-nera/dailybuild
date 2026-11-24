# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ライフログデータ収集プロジェクト。Google HealthとHealthPlanet体組成計データをAPIから取得してCSVに保存する。

### リポジトリ構成

生活管理は4リポジトリに分かれている。分割の軸は「コードかデータか」と「書き手」。

| リポジトリ | 可視性 | 中身 | 書き手 |
|---|---|---|---|
| `dailybuild` | **public** | 取得・分析コード（データは持たない） | 人 + agent |
| `dailybuild-private` | private | 全データと全レポート（健康・お金・時間・気分） | スクリプト |
| `gtd` | private | 予定・タスク・方針（org-mode） | 人 |
| `keido` | private | 日記・ナレッジベース（org-roam） | 人 |

以前は健康データを `dailybuild` 側に置き、非公開のものだけを private へ逃していたが、
`reports/` の散文が主観メンタルや金銭ストレスを引用しており、パス単位の線引きが
機能していなかった。データとレポートは**まるごと** private が持ち、`dailybuild`
には `data` `reports` `config/private` の symlink だけを置く（後述）。公開判断を毎回しなくてよい形にする。

データ側は日次で機械が書き換わり、コード側は人と agent が書く。両者を分けたことで
コミット履歴も混ざらない。

`gtd`（`~/repo/gtd`）は数年運用してきた org-mode 資産で、このリポジトリには
取り込まない。参照が必要なときは絶対パスで読む。日次で自動生成される CSV の
コミットが人の手による履歴を埋めないよう、データは `gtd` に置かない。
上の表はコードとデータの分け方の説明で、生活のリポジトリ全体の分担は gtd の地図（`~/repo/gtd/summary/README.md`）が正本。

健康レビュー（日次・週次・月次）とジャーナルへの記録の手順は gtd の `reviewing-health` スキルにあり、
このリポジトリには無い。このセッションで「日次レビュー」などを頼まれたら、gtd で `/reviewing-health` を起動し直すよう本人に伝える。

`keido`（`~/repo/keido`）も同じく取り込まない。週次日記が
`~/repo/keido/notes/zk/YYYY-wNN.org` にあり（小文字 `w`、ISO week）、
`reports/journal/YYYY-Wxx.md` と**同じ週キー**で対応する。パスは週から直に
組み立てられるので検索は要らない。ただし見出し名は年をまたいで揺れている
（`まなんだこと`/`学んだこと`、`Tweets`/`🐦Tweets`/`つぶやき`）ため、見出しに
依存したパーサを書かない。日付の粒度が要るときは本文中の org timestamp
（`<2026-07-20 Mon 07:38>`）を使う。

`keido` の散文は金銭・希死念慮をそのまま含む。**public 側へ引用・symlink・
生成物のいずれの形でも持ち込まない**（`reports/` を private へ移したのと同じ理由）。

## Development Environment

[uv](https://docs.astral.sh/uv/) で依存とPython（3.12系）を管理する。

```bash
# 環境のセットアップ・復元（pyproject.toml + uv.lock から .venv を再構築）
uv sync
```

別マシンへ移行した際も `uv sync` 一発で `.venv` を復元できる。

## テスト方針

判断の根拠は [ADR-002](docs/adr/002-quality-gate-tests-not-types.md)。
**型チェッカーを入れるか / テストをどこまで書くかを再検討する前に読むこと**
（同じ検討を2回している）。以下はそこから導かれる運用。

型チェッカーは入れていない。品質チェックはテストのみで、これが正典コマンド:

```bash
uv run pytest tests -q
```

**実 API を叩くテストは書かない。** 期間フィルタのようにこちらのコードを
検査したい場合もフェイクにする（`test_googlehealth_date_range.py`）。実 API では
Google が返すデータ次第で境界を1度も踏まないことがあるが、フェイクなら範囲外の点が
必ず含まれることを保証できる。

このリポジトリの失敗は**例外を出さず正常終了する**。壊れた値が CSV に書かれた
時点で元に戻せないもの（Tuya のログは7日、Toggl の削除済みエントリは原理的に）も
あるため、目視でも実行でも検出できない。テストはこの一種類のためだけに書く。

**書く**: マージ・期間置換・ID の型・冪等性・レート制限・symlink 未マウント。
つまり「欠測を捏造しないこと」「二重に入れないこと」の再発防止。人の目を通さず
agent が判断に使う派生物（STATE.md・metrics_daily.csv・events.jsonl）も書く。

**書かない**: レポートの文面、Jinja2 のレンダリング結果、分析の閾値・相関の解釈、
API クライアントの薄いラッパー。分析方針を変えるたびにテストを直す羽目になり、
探索の足枷になる。Grafana の画面と画面用の計算・CSV（`reports/dashboard/`）も
書かない。毎日全上書きで、人が画面で見るので壊れても翌日には戻り、目で気づける。

## Running Scripts

日次のデータ取得は2層に分かれている。入口は `scripts/ops/daily-routine.sh`
（flock → `dailybuild-private` を pull → 取得 → commit・push）、中身は
`scripts/ops/daily-fetch.sh`（ソースごとの取得リスト＋ジャーナル骨組み）。
1ステップ失敗しても後続は続行し、失敗したステップ名を出して非ゼロ終了する。

**取得は自宅サーバ vaio だけが走らせる。** iiyama（対話マシン）は `daily-routine.sh` も
`daily-fetch.sh` も自分では走らせない（取得元が2台になると同じ CSV を両側で書き換えて
merge が壊れる）。TEPCO は無人取得できないので日次から外してあり、取得自体を停止中
（[docs/tepco.md](docs/tepco.md)）。vaio の起動は2系統:

- `/reviewing-health daily` Step 1 が ssh で起動する（起床後にスマホが同期した睡眠・HRV を取るため）
- vaio の systemd user timer が毎日 12:00 に起動する（review を開かない日の安全網）

どちらも `daily-routine.sh` を呼ぶ。`daily-fetch.sh` が失敗しても取れたぶんは
commit・push し、終了コードは `daily-fetch.sh` のものを返す。rebase が
衝突したら abort して非ゼロで止まる（強制 push はしない）。手動で起動するとき:

```bash
ssh vaio 'bash -lc "~/repo/dailybuild/scripts/ops/daily-routine.sh --days 2"'
```

週次も同じ2層で、入口 `scripts/ops/weekly-routine.sh`・中身 `scripts/ops/weekly-fetch.sh`
（共通処理は `scripts/ops/lib/routine.sh`。lock は日次と共有）。起動は gtd の
`/reviewing-health weekly` が `daily-routine.sh` の後に ssh で呼ぶだけで、timer は無い
（Dawarich の動く mouse のように寝る機械が起きている保証が無いため）。週次へ置いてよいのは
**遅れても次回に追いつき、データが消えないもの**だけ。取得元の保持期間が短いもの（Toggl、Tuya の7日など）や
review の判断材料になるものは日次に残す。

```bash
ssh vaio 'bash -lc "~/repo/dailybuild/scripts/ops/weekly-routine.sh"'
```

個別スクリプトの使い方は、各スクリプトの module docstring（`Usage:`）を正本とする。
ここにはコマンドを列挙しない（一覧を二重に持つと片方が古くなる）。スクリプトや
サブコマンドを足したときは docstring に書く。日次に入っているかは `daily-fetch.sh` を見る。

新しい CLI は fetch / show のサブコマンド構成と、取得ログは stderr・markdown は stdout
という分け方を `scripts/toggl.py` と `scripts/mf.py` に揃える。

### 日次で生成する派生データ

`daily-fetch.sh` の最後のステップが `reports/` 配下（`journal/STATE.md`・`metrics_daily.csv`・`weight_daily.csv`・
`events.jsonl`・`habits_daily.csv`・`dashboard/*.csv`）を毎日**全上書き**で生成する。**派生物は `data/` に置かない**
（`data/` は取得の正本）。どれを読むか・列・落とし穴は [docs/derived-data.md](docs/derived-data.md)。

## データソース別の詳細

以下は**そのデータソースを触るときだけ**読む。落とし穴（欠測の捏造・二重投入・
著作権）が書いてあるので、該当スクリプトを変更する前に必ず開くこと。

| 読むタイミング | ドキュメント |
|---|---|
| `scripts/toggl.py` の push / start / stop を変更するとき | [docs/toggl.md](docs/toggl.md) — 冪等性判定の条件を外すと Toggl に二重投入する |
| `fetch_googlehealth.py` の caffeine / nutrition / heart_rate / spo2 / weight / body_fat / exercise / activity / intraday を変更するとき | [docs/googlehealth.md](docs/googlehealth.md) — spo2 の日付は「夜が始まった暦日」。安静時心拍は2系統届く。exercise は platform 重複あり。intraday の steps は4系統同居で素の合算は3.6倍。activity の Fitbit→Google 段差は caloriesOut だけ（steps/distance/*ActiveMinutesは折れ目なし） |
| `src/lib/exercise_source.py` / 運動系レポート（body / mind）を変更するとき | `data/googlehealth/exercise.csv` が正本。`data/wearable/activity_logs.csv`（Fitbit Web API 廃止で更新停止）はアーカイブとして凍結し統合しない（id空間・distance単位・activeZoneMinutes構造が別物）。platform 重複解決（優先度・閾値）は `exercise_source.py` のモジュール定数を push とレポートで共有する |
| `scripts/mf.py` を変更するとき | [docs/moneyforward.md](docs/moneyforward.md) — セッション切れが 200 で返る。口座別残高（balances.csv）は変わった行だけで、取れなかったページの口座を gone にしない |
| `scripts/tepco.py` を変更するとき | [docs/tepco.md](docs/tepco.md) — 欠測コマは0でなく行を作らない。30分値は約2年で消える。既定 headless では動かない |
| `scripts/food.py` / 成分表・食事記録シートを扱うとき | [docs/nutrition.md](docs/nutrition.md) — `-` は未測定であって 0 ではない。`daily.csv` は Cronometer 由来の過去記録を含むのでシート由来だけで全上書きしない |
| 検査の結果票（健診・献血・歯科検診）を CSV に書く・読むとき | [docs/checkups.md](docs/checkups.md) — 正本は CSV。空欄を推定で埋めない。血算を比べるときは2つの CSV の名前と単位をそろえる |
| 服・靴・メガネのための体のサイズ（`data/body_sizes.csv`）を扱うとき | [docs/body-sizes.md](docs/body-sizes.md) — 身長・腹囲は checkup.csv にあるので写さない |
| `emotion.py` / `phq9.py` / `bowel.py` / `daily.py` / Google Forms を変更するとき | [docs/forms.md](docs/forms.md) — **PHQ-9 日本語版は転載禁止**。questionId の再採番で過去回答が孤立する |
| `scripts/fetch_homeassistant.py` / 室内環境（HA の5分値）・HA の state 履歴を扱うとき | [docs/indoor.md](docs/indoor.md) — 照度は lux ではない相対値。室内と外気（weather.csv）は別物。state 履歴の開始時点の行は時刻が丸められているので保存しない |
| `scripts/dashboard.py` / `scripts/ops/grafana/` を変更するとき | [docs/grafana.md](docs/grafana.md) — 計算は dashboard.py に1本。Grafana 側で集計・判定しない。欠測は空セル |
| 持ち物（`scripts/homebox.py` / `data/inventory/items.csv`）を扱うとき | [docs/homebox.md](docs/homebox.md) — 正本は Homebox で items.csv は日次の写し。一覧は `includeArchived` を付けないと手放した物が消える。PUT は全欄置き換え |
| `scripts/hevy.py` / 筋トレのセット記録・腹囲を扱うとき | [docs/hevy.md](docs/hevy.md) — 取得は手動 export 頼み。月名はアプリの表示言語で変わる。腹囲は Hevy だけが持つ |
| `scripts/timeline.py` / 場所ごとの訪問（Google マップ Timeline の export）を扱うとき | [docs/timeline.md](docs/timeline.md) — 同じ訪問が hierarchyLevel 違いで重複する。座標は度記号付きの文字列。取得は手動 export 頼み。名前は places.csv の辞書（Places API）|
| `scripts/dawarich.py` / `scripts/gpslogger.py` / 位置の履歴（Dawarich）を扱うとき | [docs/dawarich.md](docs/dawarich.md) — 正本は data/ で DB は派生物。mouse で動き寝る。import 名で二重投入を判定。Visit は Timeline の重複と自前判定が重なる |
| `scripts/xoss.py` / XOSS サイコンの FIT・ロードバイクのライドを扱うとき | [docs/xoss.md](docs/xoss.md) — BLE のみで一覧は `workouts.json`。サイズ不一致でも上流は保存する。心拍 0・標高 -500 は無効値。FIT が正本で rides.csv は消さない |
| `scripts/habitica.py` / Habitica を扱うとき | [docs/habitica.md](docs/habitica.md) — 達成率の分母は history の長さではない |
| 習慣の phase / 目標値 / 移行判断を扱うとき | [docs/habits.md](docs/habits.md) — 達成率の分母は `target_per_week` であって `is_due` ではない |
| レポートの数値を解釈する / テンプレートを変更するとき | [docs/reports.md](docs/reports.md) — 指標の定義と母集団の違い |
| 行動活性化（BATD-R）を再開・再設計するとき | [docs/batdr.md](docs/batdr.md) — 日次帳票の実装は2026-09-07に廃止済み。同じ形を作り直す前に廃案の節を読む |
| 観察日記（`scripts/observation.py` / `reports/observation/`）を扱うとき | [docs/observation.md](docs/observation.md) — 材料が欠けた区切りは別の材料で埋めない。判定を変えたら `eval` で答え合わせとのズレを比べる |
| `src/lib/` の構成・Jinja2 テンプレートを触るとき | [docs/architecture.md](docs/architecture.md) |

## Report Generation

`scripts/generate_{body,mind,sleep}_report_{daily,interval}.py` は Jinja2 テンプレートでデータ準備と表示を分けている。
**`*_daily.py` は名前に反して `/reviewing-health daily` からは読まれない。** `/reviewing-health weekly` が `--week`、`/reviewing-health monthly` が
`--month` で呼ぶ期間レポートで、`*_interval.py` は `/reviewing-health monthly` だけが読む。`/reviewing-health daily` は STATE.md
（エージェント）と Grafana（人、[docs/grafana.md](docs/grafana.md)）を読む。
指標の定義・睡眠負債の計算条件・週次テーブルの母集団は [docs/reports.md](docs/reports.md)。

## Configuration

認証情報（`config/*.json`）の一覧と新マシンでの用意は [docs/setup.md](docs/setup.md)。

**新しい API キー・token は `config/*.json` でなくリポジトリ直下の `.env` に置く**（他プロジェクトと同じ
python-dotenv 方式。`.env.example` を `cp` して作る）。読み込みは `lib.utils.env` の
`get_env` / `require_env` に統一し、client ごとに読み込み処理を書かない。キーは `.env.example` が一覧
（Home Assistant / Toggl / HealthPlanet / Habitica / Last.fm / Foursquare）。`tuya_creds.json` は Tuya 削除（#196）まで残す。OAuth の token・ブラウザ
セッション・Google 配布の JSON は機械が書く状態なのでファイルのまま `config/` に置く。

Google 上（Drive・Sheets・Forms・Apps Script）に何かを作る・変えるときは先に [docs/google.md](docs/google.md)
（作成 API は親を省くとマイドライブ直下に作る。サービスアカウントはファイルを所有できない）。

## 非公開データ

`dailybuild` は public でコードしか持たない。`data/` `reports/` `config/private/` は
`dailybuild-private` への symlink で、実体はすべて private 側にある
（`.gitignore` 済み、symlink 自体もコミットしない）。

| リポジトリ内 | private 側 | 中身 |
|---|---|---|
| `data/` | `data/` | 取得の正本 |
| `reports/` | `reports/` | レポート・ジャーナル |
| `config/private/` | `config/` | 中身自体が非公開な設定 |

新しい取得先を足すときも、公開してよいかを判断する必要はない。データは
無条件に private へ落ちる。

**設定はデータと違い、既定は public 側（`config/` 直下）。** private へ回すのは
`config/private/habits.yaml` のように**設定の中身そのものが非公開**なとき
（習慣名は本人の生活と信条をそのまま含む）。認証情報は `.env` と `config/*.json` として
`.gitignore` 済みなので、private へ移す必要はない。

### セットアップ（新マシン・worktree・vaio）

手順は [docs/setup.md](docs/setup.md)。**git worktree では symlink が引き継がれない**ので、worktree を作ったら
`./scripts/setup_private_links.sh` を実行する。

### マウント忘れの検出

symlink が無い環境では `data/` `reports/` 配下が dailybuild 内の実在しない
パスに解決される。読み取りは「0件」で正常終了し、書き込みは
`mkdir(parents=True)` が public 側に実体ディレクトリを作って以後の merge 対象を
見失う。どちらも黙って欠測を捏造するので、多層で落とす。

| 層 | 仕組み |
|---|---|
| 日次実行 | `daily-fetch.sh` 冒頭で `data` `reports` が symlink か検査して即 exit |
| ディレクトリ作成 | `ensure_dir()` 経由にする（素の `mkdir(parents=True)` を書かない） |
| 個別パス | `require_private_path()` で明示検証（fetch スクリプトの出力先など） |

```python
from lib.utils.private_data import ensure_dir, require_private_path

CSV_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'time_entries.csv')
ensure_dir(CSV_FILE.parent)
```

判定は「解決先が `dailybuild-private` 配下か」で行う。親ディレクトリの存在では
判定しない（symlink が無くても public 側のディレクトリは実在しうるため）。
リポジトリ外のパス（tmp など）は対象外で、テストの一時ファイルは素通りする。
