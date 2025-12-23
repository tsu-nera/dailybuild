# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ライフログデータ収集プロジェクト。Fitbit睡眠データとHealthPlanet体組成計データをAPIから取得してCSVに保存する。

## Development Environment

```bash
# venv環境のセットアップ
python3 -m venv .venv
source .venv/bin/activate

# 依存パッケージのインストール
pip install -r requirements.txt
```

## Running Scripts

```bash
# プロジェクトルートから実行
python scripts/fetch_sleep.py        # Fitbit睡眠データ取得
python scripts/fetch_healthplanet.py # HealthPlanet体組成計データ取得
```

## Project Structure

- `scripts/` - 実行スクリプト
- `src/lib/` - APIクライアントライブラリ
  - `fitbit_api.py` - Fitbit API
  - `healthplanet_official.py` - HealthPlanet公式OAuth API（体重・体脂肪率のみ）
  - `healthplanet_unofficial.py` - HealthPlanet非公式API（全項目取得可）
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
    - `base.md.j2`, `daily_report.md.j2`
    - `sections/` - サマリー、効率、ステージ、タイミング、サイクルのセクション
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
