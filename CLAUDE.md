# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ライフログデータ収集プロジェクト。Fitbit睡眠データとHealthPlanet体組成計データをAPIから取得してCSVに保存する。

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
には `data` `reports` の symlink だけを置く（後述）。公開判断を毎回しなくてよい形にする。

データ側は日次で機械が書き換わり、コード側は人と agent が書く。両者を分けたことで
コミット履歴も混ざらない。

`gtd`（`~/repo/gtd`）は数年運用してきた org-mode 資産で、このリポジトリには
取り込まない。参照が必要なときは絶対パスで読む。日次で自動生成される CSV の
コミットが人の手による履歴を埋めないよう、データは `gtd` に置かない。

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

型チェッカーは入れていない。品質チェックはテストのみで、これが正典コマンド:

```bash
uv run pytest tests -q   # 234件・約87秒
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
スキルの Step 1 がこれを呼ぶ）。1ステップ失敗しても後続は続行し、
失敗したステップ名を出して非ゼロ終了する。個別スクリプトは以下:

最後のステップだけは取得ではなく書き込みで、`journal_skeleton.py` がその日の
数値・7日平均の変化・欠測を `reports/journal/YYYY-Wxx.md` へ追記する。
`/journal` は対話の記録が主目的なので、レビューを回さないと1行も残らず、
実際 2026-08-07 から3週間（うつエピソードで HRV が 25.9→44.7 まで動いた期間）が
丸ごと空いた。**記録が最も必要な状態が、記録が最も途切れやすい状態と一致する**ため、
数値だけは対話に依存せず機械が書く。

骨組みは `<!-- skeleton:start -->` 〜 `<!-- skeleton:end -->` に囲まれ、再実行では
この区間だけを差し替える。区間外の考察は保持し、**マーカーを持たない既存エントリ
（移行前に人と agent が書いたもの）には一切触れない**。

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
uv run scripts/emotion.py show       # 気分記録のサマリ（既定は直近7日）
uv run scripts/emotion.py setup-form --update  # 選択肢・質問文を yaml に合わせ直す
uv run scripts/bowel.py fetch        # 排便記録（Bristol、Google Form回答）取得
uv run scripts/bowel.py show         # 排便記録のサマリ（既定は直近7日）
uv run scripts/bowel.py setup-form --update  # 選択肢・質問文を yaml に合わせ直す
uv run scripts/phq9.py fetch         # PHQ-9（週次、Google Form回答）取得
uv run scripts/phq9.py url           # 回答用URLを表示（/weekly-review が使う）
uv run scripts/phq9.py setup-form    # フォーム初回作成（config/phq9_def.yaml が必須）
uv run scripts/habitica.py cron      # Habitica の日付処理を確定（daily-routine.sh が実行）
uv run scripts/habitica.py status    # 現在の Dailies と HP を表示（変更しない）
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

uv run scripts/mf.py show                    # MF 月次サマリ（当月）
uv run scripts/mf.py show --months 3         # 直近3ヶ月
uv run scripts/mf.py show --month 1 --year 2026  # 指定月
uv run scripts/mf.py show --year 2018            # 指定年を丸ごと
uv run scripts/mf.py show --unit year            # 年次（既定で全期間）
uv run scripts/mf.py show --unit day --days 14   # 日次
uv run scripts/mf.py show --sections all    # 中項目別・店舗別・金融機関別も出す
uv run scripts/mf.py show --sections +change    # 既定に前月比の増減を足す
uv run scripts/mf.py show --sections +merchant  # 既定に店舗別だけ足す
uv run scripts/mf.py show --list             # 明細一覧
uv run scripts/mf.py show --update           # 取得してから表示
```

`scripts/toggl.py` と `scripts/mf.py` は time と money の対で、fetch/show の
サブコマンド構成も markdown の形式も揃えてある（取得ログは stderr、markdown は
stdout）。

## データソース別の詳細

以下は**そのデータソースを触るときだけ**読む。落とし穴（欠測の捏造・二重投入・
著作権）が書いてあるので、該当スクリプトを変更する前に必ず開くこと。

| 読むタイミング | ドキュメント |
|---|---|
| `scripts/toggl.py` の push / start / stop を変更するとき | [docs/toggl.md](docs/toggl.md) — 冪等性判定の条件を外すと Toggl に二重投入する |
| `fetch_googlehealth.py` の caffeine / heart_rate / spo2 / weight / body_fat を変更するとき | [docs/googlehealth.md](docs/googlehealth.md) — spo2 の日付は「夜が始まった暦日」。安静時心拍は2系統届く |
| `scripts/mf.py` を変更するとき | [docs/moneyforward.md](docs/moneyforward.md) — セッション切れが 200 で返る |
| `scripts/food.py` / 成分表を扱うとき | [docs/nutrition.md](docs/nutrition.md) — `-` は未測定であって 0 ではない |
| `fetch_indoor.py` / Tuya を扱うとき | [docs/indoor.md](docs/indoor.md) — レート制限と7日の遡り限界 |
| `emotion.py` / `phq9.py` / `bowel.py` / Google Forms を変更するとき | [docs/forms.md](docs/forms.md) — **PHQ-9 日本語版は転載禁止**。questionId の再採番で過去回答が孤立する |
| `scripts/habitica.py` / Habitica を扱うとき | [docs/habitica.md](docs/habitica.md) — 達成率の分母は history の長さではない |
| レポートの数値を解釈する / テンプレートを変更するとき | [docs/reports.md](docs/reports.md) — 指標の定義と母集団の違い |
| `src/lib/` の構成・Jinja2 テンプレートを触るとき | [docs/architecture.md](docs/architecture.md) |

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

指標の定義・睡眠負債の計算条件・週次テーブルの母集団は [docs/reports.md](docs/reports.md)。

## Configuration

認証情報は`config/`ディレクトリにJSONファイルとして配置:
- `fitbit_creds.json` / `fitbit_token.json` - Fitbit API
- `healthplanet_creds.json` - HealthPlanet API（login_id, password必須）
- `toggl_creds.json` - Toggl Track API（api_token必須）
- `mf_state.json` - MoneyForward ME のブラウザセッション（`mf.py fetch --login` が生成）
- `gcloud_creds.json` - Google サービスアカウント（手動記録のGoogle Sheets取得用）
- `tuya_creds.json` - Tuya Cloud API（api_region, api_key, api_secret, device_id）
- `gforms_token.json` - Google Forms のトークン（`emotion.py` が生成し `bowel.py` / `phq9.py` とも共用。OAuth クライアントは `googlehealth_creds.json` と共用）
- `toggl_push.yaml` - Toggl push のソース別マッピング（プロジェクト名・説明・タグ）。yamlなのでコミット対象
- `phq9_def.yaml` - PHQ-9 の設問文・選択肢の実体。**著作権の都合で `.gitignore` 済み**（`phq9_def.yaml.sample` から作る。詳細は「PHQ-9（週次）」節）

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
