# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ライフログデータ収集プロジェクト。Fitbit睡眠データとHealthPlanet体組成計データをAPIから取得してCSVに保存する。

### リポジトリ構成

生活管理は3リポジトリに分かれている。分割の軸は「公開範囲」と「書き手」。

| リポジトリ | 可視性 | 中身 | 書き手 |
|---|---|---|---|
| `dailybuild` | **public** | 取得・分析コード、健康データ、健康レポート | スクリプト |
| `dailybuild-private` | private | お金・時間・気分・CBT思考記録 | スクリプト |
| `gtd` | private | 予定・タスク・方針（org-mode） | 人 |

`dailybuild` が public であることが制約の起点。公開できないデータは
`dailybuild-private` が持ち、symlink で `data/` `reports/` 配下にマウントする（後述）。

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
uv run scripts/toggl.py push --days 2 --dry-run  # Fitbit睡眠のToggl投入予定を確認（APIを叩かない）
uv run scripts/toggl.py push --days 2   # 投入実行（daily-routine.shがfetch直後に実行）
uv run scripts/toggl.py push --since 2026-08-01  # 過去分の一括投入（上限に当たったら止まる）
uv run scripts/fetch_emotion.py      # 気分記録（Google Form回答）取得

uv run scripts/fetch_mf.py --login   # MoneyForward ME 初回ログイン（ブラウザが開く）
uv run scripts/fetch_mf.py           # 直近3ヶ月の収入・支出詳細
uv run scripts/fetch_mf.py --year 2025  # 指定年を丸ごと取り直す
uv run scripts/fetch_mf.py --refresh # 取得＋一括更新のキック（日次運用）

# サマリ表示（既定では API を叩かず data/ の CSV だけを読む）
uv run scripts/toggl.py show --days 7        # Toggl 日次サマリ
uv run scripts/toggl.py show --unit week     # Toggl 週次サマリ
uv run scripts/toggl.py show --list          # 時系列のエントリ一覧（既定は当日）
uv run scripts/toggl.py show --update        # 取得してから表示
```

`scripts/toggl.py show` は取得ログを stderr、markdown を stdout に分けて出す。
Toggl 側で削除されたエントリは CSV に残り続ける（マージは追加・更新のみ）。

`scripts/toggl.py push` は Fitbit 睡眠（昼寝含む）を Toggl のタイムエントリとして
書き込む。書き込みも `/me` 系と同じ 30req/h 枠を消費する前提で `--max-writes`
（既定10）で抑え、超過分は捨てずに次回へ繰り越す。冪等性は
`data/toggl/pushed.csv` の台帳を主に、直前 fetch の `time_entries.csv` を
突き合わせに使う二段構え。台帳にあるが CSV に居ないエントリは「手動削除された」
とみなして再投入するが、判定は CSV がカバーする期間内に限る
（範囲外は「未取得」と区別できず、無限に再投入してしまうため）。
CSV が古い/無い場合は台帳のみで判定し、手動削除の検出はスキップする旨を警告する。

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
  - `mf_client.py` - MoneyForward ME（Playwright セッションで月次CSVを取得）
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
- `data/` - 出力CSV
- `notes/` - Jupyter notebooks（実験・分析用）
- `reports/` - 生成されたレポート

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
- `mf_state.json` - MoneyForward ME のブラウザセッション（`fetch_mf.py --login` が生成）
- `gcloud_creds.json` - Google サービスアカウント（手動記録のGoogle Sheets取得用）
- `toggl_push.yaml` - Toggl push のソース別マッピング（プロジェクト名・説明・タグ）。yamlなのでコミット対象

Google Sheets クライアント（`src/lib/clients/gsheets_client.py`）は `config/gcloud_creds.json` を直接参照しない。環境変数 `GOOGLE_APPLICATION_CREDENTIALS` か既定パス `~/.config/gcp/gdrive-creds.json` を探すため、新マシンではどちらかを用意する（リポジトリの認証情報を使う場合は `ln -sf "$PWD/config/gcloud_creds.json" ~/.config/gcp/gdrive-creds.json`）。

## 非公開データ

`dailybuild` は public なので、以下は private リポジトリ `dailybuild-private` が
実体を持ち、ここには symlink だけを置く（`.gitignore` 済み、symlink 自体も
コミットしない）。

| パス | 内容 |
|---|---|
| `data/mf/` | MoneyForward ME 収入・支出詳細 |
| `data/toggl/` | Toggl Track タイムエントリ |
| `data/emotion.csv` | 気分記録（Google Form 回答） |
| `reports/cbt/` | CBT 思考記録 |

### セットアップ（新マシン・worktree）

```bash
git clone git@github.com:tsu-nera/dailybuild-private.git ~/repo/dailybuild-private
./scripts/setup_private_links.sh   # 冪等。別の場所に置くなら DAILYBUILD_PRIVATE を設定
```

**git worktree では symlink が引き継がれない。** worktree を作ったら
`setup_private_links.sh` を実行すること。

### 新しく非公開データを追加するとき

symlink 未設定の環境では参照先が `dailybuild` 内の実在しないパスに解決され、
取得スクリプトが「0件」で正常終了して欠測を捏造する。これを防ぐため、
非公開パスは必ず `require_private_path()` を通してから読み書きする。

```python
from lib.utils.private_data import require_private_path

CSV_FILE = require_private_path(BASE_DIR / 'data' / 'toggl' / 'time_entries.csv')
```

親ディレクトリの存在では判定していない。`data/emotion.csv` のようにファイル単体を
symlink する場合、symlink が無くても親の `data/` は実在してチェックをすり抜けるため、
解決先が `dailybuild-private` 配下にあるかで判定している。

追加時は `scripts/setup_private_links.sh` の `link` 行と `.gitignore` にも追記する。
