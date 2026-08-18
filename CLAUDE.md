# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ライフログデータ収集プロジェクト。Fitbit睡眠データとHealthPlanet体組成計データをAPIから取得してCSVに保存する。

## Development Environment

[uv](https://docs.astral.sh/uv/) で依存とPython（3.12系）を管理する。

```bash
# 環境のセットアップ・復元（pyproject.toml + uv.lock から .venv を再構築）
uv sync
```

別マシンへ移行した際も `uv sync` 一発で `.venv` を復元できる。

## Running Scripts

```bash
# プロジェクトルートから実行（uv run なら .venv の有効化不要）
uv run scripts/fetch_sleep.py        # Fitbit睡眠データ取得
uv run scripts/fetch_healthplanet.py # HealthPlanet体組成計データ取得
uv run scripts/fetch_toggl.py        # Toggl Trackタイムエントリ取得
```

## Project Structure

- `scripts/` - 実行スクリプト
- `src/lib/` - APIクライアントライブラリ
  - `fitbit_api.py` - Fitbit API
  - `healthplanet_official.py` - HealthPlanet公式OAuth API（体重・体脂肪率のみ）
  - `healthplanet_unofficial.py` - HealthPlanet非公式API（全項目取得可）
  - `toggl_client.py` - Toggl Track API
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
- `gcloud_creds.json` - Google サービスアカウント（手動記録のGoogle Sheets取得用）

Google Sheets クライアント（`src/lib/clients/gsheets_client.py`）は `config/gcloud_creds.json` を直接参照しない。環境変数 `GOOGLE_APPLICATION_CREDENTIALS` か既定パス `~/.config/gcp/gdrive-creds.json` を探すため、新マシンではどちらかを用意する（リポジトリの認証情報を使う場合は `ln -sf "$PWD/config/gcloud_creds.json" ~/.config/gcp/gdrive-creds.json`）。
