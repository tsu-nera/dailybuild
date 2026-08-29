# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ライフログデータ収集プロジェクト。Fitbit睡眠データとHealthPlanet体組成計データをAPIから取得してCSVに保存する。

### リポジトリ構成

生活管理は3リポジトリに分かれている。分割の軸は「コードかデータか」と「書き手」。

| リポジトリ | 可視性 | 中身 | 書き手 |
|---|---|---|---|
| `dailybuild` | **public** | 取得・分析コード（データは持たない） | 人 + agent |
| `dailybuild-private` | private | 全データと全レポート（健康・お金・時間・気分） | スクリプト |
| `gtd` | private | 予定・タスク・方針（org-mode） | 人 |

以前は健康データを `dailybuild` 側に置き、非公開のものだけを private へ逃していたが、
`reports/` の散文が主観メンタルや金銭ストレスを引用しており、パス単位の線引きが
機能していなかった。データとレポートは**まるごと** private が持ち、`dailybuild`
には `data` `reports` の symlink だけを置く（後述）。公開判断を毎回しなくてよい形にする。

データ側は日次で機械が書き換わり、コード側は人と agent が書く。両者を分けたことで
コミット履歴も混ざらない。

`gtd`（`~/repo/gtd`）は数年運用してきた org-mode 資産で、このリポジトリには
取り込まない。参照が必要なときは絶対パスで読む。日次で自動生成される CSV の
コミットが人の手による履歴を埋めないよう、データは `gtd` に置かない。

## Development Environment

[uv](https://docs.astral.sh/uv/) で依存とPython（3.12系）を管理する。

```bash
# 環境のセットアップ・復元（pyproject.toml + uv.lock から .venv を再構築）
uv sync
```

別マシンへ移行した際も `uv sync` 一発で `.venv` を復元できる。

## テスト方針

型チェッカーは入れていない。品質チェックはテストのみで、これが正典コマンド:

```bash
uv run pytest tests -q   # 138件・約44秒
```

このリポジトリの失敗は**例外を出さず正常終了する**。壊れた値が CSV に書かれた
時点で元に戻せないもの（Tuya のログは7日、Toggl の削除済みエントリは原理的に）も
あるため、目視でも実行でも検出できない。テストはこの一種類のためだけに書く。

**書く**: マージ・期間置換・ID の型・冪等性・レート制限・symlink 未マウント。
つまり「欠測を捏造しないこと」「二重に入れないこと」の再発防止。

**書かない**: レポートの文面、Jinja2 のレンダリング結果、分析の閾値・相関の解釈、
API クライアントの薄いラッパー。分析方針を変えるたびにテストを直す羽目になり、
探索の足枷になる。

## Running Scripts

日次のデータ取得は `scripts/ops/daily-routine.sh` にまとめてある（`/daily-review`
スキルの Step 1 と cron の両方がこれを呼ぶ）。1ステップ失敗しても後続は続行し、
失敗したステップ名を出して非ゼロ終了する。個別スクリプトは以下:

```bash
# プロジェクトルートから実行（uv run なら .venv の有効化不要）
uv run scripts/fetch_sleep.py        # Fitbit睡眠データ取得
uv run scripts/fetch_healthplanet.py # HealthPlanet体組成計データ取得
uv run scripts/toggl.py fetch        # Toggl Trackタイムエントリ取得
uv run scripts/toggl.py fetch --update  # CSVの最終日から今日まで（差分取得）
uv run scripts/toggl.py push --days 2 --dry-run  # 睡眠・運動のToggl投入予定を確認（APIを叩かない）
uv run scripts/toggl.py push --days 2   # 投入実行（daily-routine.shがfetch直後に実行）
uv run scripts/toggl.py push --since 2026-08-01  # 過去分の一括投入（上限に当たったら止まる）
uv run scripts/toggl.py start 読書       # プロジェクトを指定して計測開始（部分一致可）
uv run scripts/toggl.py start 読書 -d "SICP" -t deep
uv run scripts/toggl.py stop             # 計測中のエントリを停止
uv run scripts/toggl.py current          # 計測中のエントリを表示
uv run scripts/toggl.py projects         # プロジェクト名一覧（既定はキャッシュのみ）
uv run scripts/toggl.py open             # Toggl の Web 画面を開く（open projects 等）
uv run scripts/emotion.py fetch      # 気分記録（Google Form回答）取得
uv run scripts/emotion.py setup-form --update  # 選択肢・質問文を yaml に合わせ直す
# 室内環境は所要が長い（1日ぶん約11分）ため daily-routine.sh から外してある。
# 別途1日1回、手動で回す。Tuya のログは最大7日しか遡れないので放置すると穴が空く
uv run scripts/fetch_indoor.py --update  # 室内環境（CO2/温度/湿度）差分取得
uv run scripts/fetch_indoor.py --raw     # DPコード一覧（マッピング同定用）

uv run scripts/food.py build-master  # 食品マスタ生成（成分表2,538件。初回と成分表更新時のみ）

uv run scripts/mf.py fetch --login   # MoneyForward ME 初回ログイン（ブラウザが開く）
uv run scripts/mf.py fetch           # 直近3ヶ月の収入・支出詳細
uv run scripts/mf.py fetch --year 2025  # 指定年を丸ごと取り直す
uv run scripts/mf.py fetch --refresh # 取得＋一括更新のキック（日次運用）

# サマリ表示（既定では API を叩かず data/ の CSV だけを読む）
uv run scripts/toggl.py show --days 7        # Toggl 日次サマリ
uv run scripts/toggl.py show --unit week     # Toggl 週次サマリ
uv run scripts/toggl.py show --list          # 時系列のエントリ一覧（既定は当日）
uv run scripts/toggl.py show --update        # 取得してから表示

uv run scripts/mf.py show                    # MF 月次サマリ（直近3ヶ月）
uv run scripts/mf.py show --month 1 --year 2026  # 指定月
uv run scripts/mf.py show --year 2018            # 指定年を丸ごと
uv run scripts/mf.py show --unit year            # 年次（既定で全期間）
uv run scripts/mf.py show --unit day --days 14   # 日次
uv run scripts/mf.py show --list             # 明細一覧
uv run scripts/mf.py show --update           # 取得してから表示
```

`scripts/toggl.py` と `scripts/mf.py` は time と money の対で、fetch/show の
サブコマンド構成も markdown の形式も揃えてある（取得ログは stderr、markdown は
stdout）。

Toggl 側で削除されたエントリは CSV に残り続ける（マージは追加・更新のみ）。

`scripts/toggl.py start/stop` は手動計測。プロジェクト名は完全一致 → 大文字小文字
無視 → 部分一致の順に解決し、複数候補に当たったら黙って1つ選ばず候補を出して落とす。
名前 → ID の解決は `data/toggl/projects.json` のキャッシュで行い、**キャッシュに
無い名前を引いたときだけ**取り直す（`--refresh-projects` で明示更新）。start のたびに
一覧を取ると /me 系 30req/h の枠を fetch と食い合って日次取得が落ちるため。

計測中のエントリは duration が負値で表現される（stop を含めない POST）。既に計測中の
ものがある状態で start すると Toggl 側が古い方を自動で停止するので、こちらからは
stop を呼ばない。計測結果は CSV には直接書かず、次回の fetch で入る
（`store.build_dataframe` は duration が負の行を除外する）。

`scripts/toggl.py push` は Fitbit 睡眠（昼寝含む）と Google Health の運動セッション
（サイクリング・筋トレ・瞑想）を Toggl のタイムエントリとして書き込む。書き込みも
`/me` 系と同じ 30req/h 枠を消費する前提で `--max-writes`（既定10）で抑え、超過分は捨てずに次回へ繰り越す。冪等性は
`data/toggl/pushed.csv` の台帳を主に、直前 fetch の `time_entries.csv` を
突き合わせに使う二段構え。台帳にあるが CSV に居ないエントリは「手動削除された」
とみなして再投入するが、判定は**直近 fetch が実際に取りに行った期間**
（`data/toggl/fetch_state.json`）内に限る。範囲外は「未取得」と区別できず、
無限に再投入してしまうため。

この窓に `time_entries.csv` の start の min/max を使ってはいけない。CSV は過去分が
積み上がるだけなので min は何ヶ月も前になり、一度も fetch していない日まで
「カバー済み」と誤認する。睡眠エントリの start は dateOfSleep の**前日夜**にあるので、
fetch と push を同じ `--days N` で回すと投入したエントリがどの fetch 窓にも入らず、
毎日「削除された」と誤判定されて重複投入されていた（2026-08-25 に修正）。

CSV が古い/無い場合、`fetch_state.json` が無い場合、fetch 窓が push 対象期間の前日を
カバーしていない場合は、いずれも台帳のみで判定し、手動削除を検出しない旨を警告する。

なお削除されたエントリは CSV に残り続けるため、**一度 CSV に入った投入済みエントリの
手動削除は原理的に検出できない**。検出が効くのは CSV にまだ入っていないものだけ。

削除判定にはもう一段の条件がある。**直近 fetch（`fetch_state.json` の `fetched_at`）
より後に投入したエントリは判定対象から外す。** push が書いたエントリは、次の fetch
までは CSV に居なくて当たり前なので、これを見ないと fetch を挟まずに push を2回
叩いただけで「削除された」と誤読して重複投入する（2026-08-25 に実際に発生し、
サイクリング2件が Toggl 上で二重になった）。台帳の `pushed_at` が読めない場合も、
疑わしきは再投入しない側へ倒す。

**Toggl は秒未満を含む RFC3339 を 400 で弾く。** Health Connect 由来の運動セッションは
ミリ秒付きで届くので、`build_payload` で秒に丸めてから渡す。

投入先プロジェクトが Toggl 側に無い場合は投入せず次回に回す。project 無しで
投入してしまうと、台帳に「投入済み」として残り、後からプロジェクトを作っても
直せなくなるため。

### 運動セッションの Toggl 反映

ソースは `data/googlehealth/exercise.csv`（`fetch_googlehealth.py` の `exercise`
エンドポイント）。`exerciseType` → プロジェクトの対応は `config/toggl_push.yaml`
の `googlehealth_exercise.categories` に持たせてある。ここに載っていない型
（WALKING / RUNNING 等）は投入しない。

**`YOGA` は瞑想として投入する。** Charge 6 のエクササイズ一覧（41種類）に瞑想は
無く、本体で計測する手段が他に無いため、YOGA を瞑想の代用モードとして使っている。
ヨガを実際にやり始めたらこの対応は破綻する。

**同じ運動が複数プラットフォームから重複して届く。** Fitbit の Charge 6 と、
Health Connect 経由の Google Fit / Hevy が、ほぼ同じ時間帯を別セッションとして
返す（2026年の実測で74組。`WEIGHTS`/FITBIT と `STRENGTH_TRAINING`/HEALTH_CONNECT、
`OUTDOOR_BIKE`/FITBIT と `BIKING`/HEALTH_CONNECT）。素通しすると Toggl に同じ
運動が2本入るため、時間が重なったら `platform_priority` の先頭に近い方だけを残す。

優先度は**重なりの解決にのみ**使う。重なっていないセッションは platform に関係なく
残すので、Fitbit Web API 廃止後に Fitbit 側が途切れても Health Connect 側で
穴が埋まる。

`exercise` は `dailyRollUp` 非対応で `list` のページングだけ（全履歴242ページ）。
既存の `data/fitbit/activity_logs.csv` とはスキーマを揃えていない別ファイルで、
統合は Issue #77 の担当。マージのキーは日付でなく `id`（19桁の整数なので
読み戻しは `dtype=str` 必須。int で読むと新旧のキーが一致せず二重に残る）。

### カフェイン摂取

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

### 体重・体脂肪率（Google Health 経由）

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

MF の明細は **2015-02 まで遡って取得できる**（閲覧期間の制限は無い。2015-01 以前は
0 件 = MF 側に記録が無い）。`--unit year` の既定期間はこの最古年から当月までで、
`EARLIEST_YEAR` に持たせてある。ただし連携が壊れている口座の明細は過去分も丸ごと
欠けるため、古い年ほど支出は過少に出る。

`mf.py show` は `計算対象=1` の明細だけを集計する。口座間の振替は MF 側で必ず
`計算対象=0` が付くのでこの絞り込みだけで落ちる。MF は引き落とし予定日の
**未来明細**を含むため、「直近Nヶ月」は当月末で上限を切っている。

### 食品マスタ

食事記録の土台となる食品マスタを、文部科学省「日本食品標準成分表（八訂）増補2023年」
から作る（2,538食品 × 36成分、ビタミン・ミネラル込み）。二次利用可、出典明記が条件。
**記録の入力手段はまだ決まっていない**（Issue で議論中）。現状はマスタを持つだけ。

成分表の Excel はリポジトリに置かず `tmp/` にキャッシュするだけで、実体は
`data/nutrition/foods_master.csv` 1本。ハマりどころ:

- **見出しは4行の結合セルで機械可読でない。** 「たんぱく質」が3行目にも4行目にもあり、
  4行目のそれは別物（アミノ酸組成による）。**12行目の「成分識別子」の行だけ**が
  1成分1列なので、列の対応はここだけを見る。成分値の間に `*` だけが入る印の列
  （エネルギー計算に用いた成分の目印）も挟まるが、識別子で拾えば自動的に外れる
- 同じ栄養素に複数の識別子がある。採ったのは `PROT-`（`PROTCAA` でない）、
  `NE`（ナイアシン当量）、`VITA_RAE`（レチノール活性当量）、`TOCPHA`（α-トコフェロール）、
  `CHOCDF-`（差引き法による炭水化物）
- **成分値の `-` は未測定。0 ではない。** NaN のまま伝播させる。合算で 0 として足すと、
  測っていない成分を「摂っていない」と偽ることになる。`Tr`（微量）は 0、
  `(11.3)` は推計値として 11.3 を採る
- ヨウ素・セレン・クロム・モリブデン・ビオチンは成分表側で**約46%が未測定**。
  これらを含む集計は日によって母数が変わる
- ダウンロード URL に日付が入っている（`20260327-mxt_kagsei-...`）。成分表が更新されると
  **404 で落ちる**ので `mext.py` の `SEIBUN_URL` を手で直す。行番号 `IDENT_ROW` も固定だが、
  ずれた場合は例外を投げるので静かには壊れない

市販の冷凍食品・加工食品は成分表に無い。パッケージの栄養成分表示から可食部100g当たりで
`foods_master.csv` に追記する（`source=manual`）。`build-master` は既存 CSV の
`source != mext` の行を読み戻してから書くので、成分表を取り直しても手入力分は消えない。

### 室内環境（CO2/温度/湿度）

**`data/indoor.csv`（室内）と `data/weather.csv`（外気）は別物。** どちらにも温度と
湿度が入っているので取り違えやすい。室温を見たいときに外気温を読むと結論が変わる
（睡眠と外気温の関係は既に分析済みで、あれは**外気温であって室温ではない**）。
ファイル名で内外を判別できるよう `environment` ではなく `indoor` にしてある。

就寝中のCO2を測るのが目的。LSENLTY の Tuya 系センサーから `data/indoor.csv` に
5分刻みで蓄積する。ハマりどころ:

- **デバイスは値が変化しなくても1秒ごとに送る。** 1日約26万件になり、素直に全件取得
  すると約2,600コール・27分。API 側に集計・リサンプル機能は無い（統計APIは別サブスク
  リプションが要り、`No permissions` で弾かれる）
- そこで **5分境界ごとに60秒の窓だけを引き、窓内を平均する**。1境界1コールで済む。
  `codes` に3項目まとめて渡せる（`v2.0/cloud/thing/{id}/report-logs`）
- `size` は **100が上限**。`v1.0/logs` は200以上を指定しても100しか返さず、
  `v2.0/report-logs` は `Parameter error (40000303)` で落ちる
- `report-logs` は **`codes` が必須**。省くと `illegal param (1110)`。全DPを見たい
  `--raw` は `v1.0/logs` を使う
- **ログ照会のレート制限はトークンバケット**（`40000309 The log query is too frequent`）。
  実測（2026-08-26）: バーストは約18コールまで通り、枯れた後の持続レートは
  **約0.46 req/s = 1点あたり約2.2秒**。2.5秒間隔なら30回連続で失敗ゼロ。
  API 自体のレイテンシは**約0.5秒**しかないので、待ち時間の大半は通信でなくこの
  スロットル。`MIN_REQUEST_INTERVAL = 1.5` は持続可能レートより速く、バーストを
  使い切った後は必ず制限に当たってバックオフに落ちる（それでも実効2.2秒/点で
  下限に張り付くため、間隔を緩めても速くはならない）
- **5分刻みで1日288点なら約11分かかる。この下限は実装では縮まらない。**
  短縮したいなら時間帯を絞る（就寝帯のみ）か粒度を落とす
- **窓が閉じていない境界は取らない。** 途中までの平均が確定値としてCSVに載ると、
  以後スキップ対象になって二度と取り直されない
- 窓が0件の境界は**欠測のまま残す**。デバイスのオフライン時間と測定値の不在を
  区別できなくなるため補間しない。ただし欠測境界はスキップ対象にならず毎回
  引き直されるので、取得は `--update`（CSVの最終時刻からの差分）で回す
- **長い実行は途中で死んでも取得済みを捨てない。** `SAVE_EVERY`（50点）ごとと、
  Ctrl-C・レート制限の打ち切り時にも CSV へ書く。再実行は取得済みをスキップして
  続きから取る
- Tuya のログは**最大7日**しか遡れない。オフライン中の値はデバイスに残らないので、
  **穴は原理的に埋められない**

デバイスは建物提供Wi-Fi（WPA2/WPA3混在 + 802.11ax）に association できない。
WiMAXルータ経由で常時接続している。詳細は Issue #42。

### 気分記録

Google Form で入力し、Forms API で直接読む（回答先スプレッドシートは作らない。
Forms API にリンク設定が無く、そこだけ手作業として残るため）。3問構成
（気分1〜5・気持ち12個・何があった？）。

- **サービスアカウントでは作れない。** Drive の `storageQuota.limit` が 0 で
  ファイルを所有できず、`forms.create` が **500 Internal** になる（quota だと
  分かるエラーは返らない）。OAuth で本人が所有する
- **フォームを画面で編集しない。** 語彙の正は `config/emotion_def.yaml` で、
  `setup-form --update` が画面の内容を上書きする
- 削除された回答は CSV に残り続ける（マージは追加・更新のみ）
- 1〜5 は **valence（高=良好）であって感情の強さではない**。`mind_score` と
  同じ向き。`scaleQuestion` の回答は `textAnswers` に文字列で入るので数値化は
  こちら側（`emotion.py`）で行う
- **`data/emotion_vocab_history.csv` に語彙の版を残している。** 語彙を後から
  変えると過去のデータが読めなくなる（0件が「感じなかった」のか「選択肢が
  無かった」のか区別できない）ため、**語彙そのものが変わったときだけ**
  1行追記する。per-row の版列は持たない（毎回全件取り直すのでマージが濁る）
- **追記判定に `revisionId` を使ってはいけない。** `revisionId` は質問文の
  変更でも `setup-form --update` の空打ちでも上がる（実測: 08 → 09）ので、
  これをキーにすると語彙が同じ行が積み上がり、「いつ語彙が変わったか」を
  知るのに結局 `labels` を diff する羽目になる。`revision_id` 列は
  「その語彙が最初に観測された版」の記録として持つだけ
- **フォームの質問はタイトルでなく種類（scale/choice/text）で突き合わせて
  更新している。** index で突き合わせると既存 item の型を作り変えることに
  なり、questionId が保持されたまま中身が変わって過去の回答が別の質問に
  化ける（`gforms_api.sync_questions()`）
- **`updateItem` は `questionId` を明示しないと新しい ID を採番し直す。**
  タイトルだけの変更でも起きる。そうなると過去の回答は古い ID のまま孤立し、
  タイトル → questionId で引いている CSV 側から二度と読めない（実際に一度
  発生させ、回答に残っていた古い ID を明示指定して復旧した）

### MoneyForward ME

公式 API が無いため、Playwright で保持したログインセッションを使って
`/cf/csv`（収入・支出詳細のダウンロード用エンドポイント）を月単位で叩く。
画面のスクレイピングはしない。ハマりどころ:

- レスポンスは `charset=utf-8` を名乗るが実体は **cp932**
- User-Agent に `HeadlessChrome` が入っていると **403**。通常の Chrome に偽装する
- セッションが切れると 200 のままログイン画面 HTML が返る。CSV ヘッダで検証して
  落としているので、欠測を捏造せずエラー終了する（`--login` で取り直す）
- 明細は MF 側で後から分類・金額を変更されることがある。マージは `ID` 基準の
  上書きなので取り直せば追従するが、MF 側で削除された明細は CSV に残り続ける
- セッション切れで日次実行全体を止めないよう、`daily-routine.sh` は
  ステップ単位で失敗を握って続行する

CSV に出るのは **MF が金融機関から取り込み済みの明細だけ**。自動更新は1日1回
程度しか走らないため、叩くだけでは数日古いままになる。`--refresh` は画面の
「金融機関からのデータ一括更新」と同じ `POST /faggregation_queue2` を叩く。

更新は金融機関ごとに非同期で走り、**カード会社は完了まで10分以上かかる**
（実測: 楽天カードはキックから8分経っても「更新中」）。同期的に待つのは
現実的でないため完了は待たず、キックの結果は**次回の取得で回収する**。
日次で回している限り、明細は実質1日遅れで揃う。

「設定エラー」「要ワンタイムパスワード」等になった連携は一括更新では復旧せず、
その口座の明細は CSV から丸ごと欠ける。黙って欠測しないよう、取得のたびに
正常でない口座を警告する（再認証は MF の画面で手作業）。

## Project Structure

- `scripts/` - 実行スクリプト
- `src/lib/` - APIクライアントライブラリ
  - `fitbit_api.py` - Fitbit API
  - `healthplanet_official.py` - HealthPlanet公式OAuth API（体重・体脂肪率のみ）
  - `healthplanet_unofficial.py` - HealthPlanet非公式API（全項目取得可）
  - `toggl/` - Toggl Track（`client.py` API クライアント、`store.py` CSV 読み書き、`render.py` markdown 出力）
  - `mf/` - MoneyForward ME（`client.py` Playwright セッション、`store.py` CSV 読み書き、`render.py` markdown 出力）
  - `food/` - 食事記録（`mext.py` 日本食品標準成分表のパーサ）
  - `templates/` - Jinja2テンプレートとレンダラー
    - `renderer.py` - レポートテンプレートレンダラー
    - `filters.py` - カスタムJinja2フィルタ
  - `analytics/` - データ分析ライブラリ
    - `body.py` - 体組成分析
    - `sleep.py` - 睡眠分析
    - `mind.py` - メンタルコンディション分析
  - `utils/` - 共通ユーティリティ
    - `report_args.py` - レポート引数パースと期間フィルタリング
- `templates/` - Markdownレポートテンプレート
  - `body/` - 体組成レポート
    - `base.md.j2` - 基本構造
    - `daily_report.md.j2` - 日次レポート
    - `interval_report.md.j2` - 週次隔レポート
    - `sections/` - セクションテンプレート
  - `mind/` - メンタルコンディションレポート
    - `base.md.j2`, `daily_report.md.j2`
    - `sections/` - HRV、心拍、睡眠、生理指標のセクション
  - `sleep/` - 睡眠分析レポート
    - `base.md.j2`, `daily_report.md.j2`, `interval_report.md.j2`
    - `sections/` - サマリー、効率、ステージ、タイミング、サイクル、週次データのセクション
- `config/` - API認証情報（gitignore対象）
- `data/` - 出力CSV（`dailybuild-private` への symlink）
- `notes/` - Jupyter notebooks（実験・分析用）
- `reports/` - 生成されたレポート（`dailybuild-private` への symlink）

## Report Generation

レポート生成スクリプトはJinja2テンプレートエンジンを使用して、データ準備とプレゼンテーションを分離:

```bash
# 体組成レポート
python scripts/generate_body_report_daily.py --days 7          # 日次（7日間）
python scripts/generate_body_report_interval.py --weeks 8      # 週次隔（8週間）

# メンタルコンディションレポート
python scripts/generate_mind_report_daily.py --days 7          # 日次（7日間）

# 睡眠分析レポート
python scripts/generate_sleep_report_daily.py --days 7         # 日次（7日間）
python scripts/generate_sleep_report_interval.py --weeks 8     # 週次隔（8週間）
```

### mind レポートの指標

レポート本文には出所や指標の定義を刷らない。読み手（人・agent とも）が
毎日読み飛ばす定型文になるうえ、方針が変わってもレポート側は追従せず腐る
（Zone2 目標は 2026-08-07 に `targets.yaml` から消えたのに、テンプレートだけが
「Z2中心の有酸素ベース構築が土台」と主張し続けていた）。定義はここに置き、
レポートには**その実行でしか分からない値**（ベースライン、Z境界の実bpm、
欠測日）だけを載せる。

- **深部体温**: Fitbit アプリへ**手動で記録した実測体温**（℃）。`temperature_core`
  で読む。括弧内は測定時刻。自動計測ではないので、**0件は「測っていない」が
  正常状態**でありうる
- **体温Δ**: 皮膚温変動（℃）。**深部体温とは別物**で、センサー由来の相対値。
  絶対体温として読むと 0.7℃ を低体温と誤読する
- **軽/中/高**: Google Health の active-minutes（LIGHT / MODERATE / VIGOROUS）。
  Fitbit の座位時間の代替で、同一指標ではない（Issue #82）
- **HRV**: RMSSD（ms） / **RHR**: 安静時心拍数（bpm） / **BR**: 呼吸数（回/分）
- **SpO2**: 血中酸素飽和度（最小/平均%）
- **血圧・脈拍**: HealthPlanet 血圧計

日別表の値に付く `(z+2.1)` は**ベースラインからの乖離が ±1.5SD 以上**のときだけ
出る z 値。以前は太字で印を付けていたが、+1.5SD と +3SD が同じ見た目に潰れて
逸脱の大きさが読めなかったため、値そのものを出すようにした。

### テンプレートアーキテクチャ

全レポートは統一されたパターンを採用:

1. **データ準備**: `prepare_*_report_data()` 関数がコンテキスト辞書を構築
2. **テンプレートレンダリング**: レンダラークラス（`BodyReportRenderer`, `MindReportRenderer`, `SleepReportRenderer`）がJinja2テンプレートを適用
3. **テンプレート構成**:
   - `base.md.j2` - セクションブロック定義
   - `*_report.md.j2` - base継承、セクションinclude
   - `sections/*.md.j2` - 再利用可能なセクション（条件付きレンダリング対応）

### カスタムフィルタ

`src/lib/templates/filters.py` で定義された共通フィルタ:

- `format_change(value, unit, positive_is_good)` - 変化量フォーマット（良い変化を太字化）
- `date_format(date)` - 日付フォーマット
- `number_format(value, decimals)` - 数値フォーマット

### 期間フィルタリング

`src/lib/utils/report_args.py:filter_dataframe_by_period()` で統一されたデータフィルタリング:

```python
df_filtered = filter_dataframe_by_period(
    df=dataframe,
    date_column='date',  # または 'dateOfSleep'
    week=week, month=month, year=year, days=days,
    is_index=True  # 日付がindexの場合
)
```

## Configuration

認証情報は`config/`ディレクトリにJSONファイルとして配置:
- `fitbit_creds.json` / `fitbit_token.json` - Fitbit API
- `healthplanet_creds.json` - HealthPlanet API（login_id, password必須）
- `toggl_creds.json` - Toggl Track API（api_token必須）
- `mf_state.json` - MoneyForward ME のブラウザセッション（`mf.py fetch --login` が生成）
- `gcloud_creds.json` - Google サービスアカウント（手動記録のGoogle Sheets取得用）
- `tuya_creds.json` - Tuya Cloud API（api_region, api_key, api_secret, device_id）
- `gforms_token.json` - 気分記録フォームのトークン（`emotion.py` が生成。OAuth クライアントは `googlehealth_creds.json` と共用）
- `toggl_push.yaml` - Toggl push のソース別マッピング（プロジェクト名・説明・タグ）。yamlなのでコミット対象

Google Sheets クライアント（`src/lib/clients/gsheets_client.py`）は `config/gcloud_creds.json` を直接参照しない。環境変数 `GOOGLE_APPLICATION_CREDENTIALS` か既定パス `~/.config/gcp/gdrive-creds.json` を探すため、新マシンではどちらかを用意する（リポジトリの認証情報を使う場合は `ln -sf "$PWD/config/gcloud_creds.json" ~/.config/gcp/gdrive-creds.json`）。

## 非公開データ

`dailybuild` は public でコードしか持たない。`data/` と `reports/` は
`dailybuild-private` への symlink で、実体はすべて private 側にある
（`.gitignore` 済み、symlink 自体もコミットしない）。

新しい取得先を足すときも、公開してよいかを判断する必要はない。データは
無条件に private へ落ちる。

### セットアップ（新マシン・worktree）

```bash
git clone git@github.com:tsu-nera/dailybuild-private.git ~/repo/dailybuild-private
./scripts/setup_private_links.sh   # 冪等。別の場所に置くなら DAILYBUILD_PRIVATE を設定
```

**git worktree では symlink が引き継がれない。** worktree を作ったら
`setup_private_links.sh` を実行すること。

### マウント忘れの検出

symlink が無い環境では `data/` `reports/` 配下が dailybuild 内の実在しない
パスに解決される。読み取りは「0件」で正常終了し、書き込みは
`mkdir(parents=True)` が public 側に実体ディレクトリを作って以後の merge 対象を
見失う。どちらも黙って欠測を捏造するので、多層で落とす。

| 層 | 仕組み |
|---|---|
| 日次実行 | `daily-routine.sh` 冒頭で `data` `reports` が symlink か検査して即 exit |
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
