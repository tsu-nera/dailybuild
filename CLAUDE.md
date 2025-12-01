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
- `config/` - API認証情報（gitignore対象）
- `data/` - 出力CSV
- `notes/` - Jupyter notebooks（実験・分析用）

## Configuration

認証情報は`config/`ディレクトリにJSONファイルとして配置:
- `fitbit_creds.json` / `fitbit_token.json` - Fitbit API
- `healthplanet_creds.json` - HealthPlanet API（login_id, password必須）
