# Google Sheets連携 設定ガイド

Fitbit睡眠データをGoogle Spreadsheetに自動保存する機能の設定手順。

## 概要

- **目的**: Fitbit睡眠データをGoogle Spreadsheetに自動保存
- **実行方法**: GitHub Actions（毎日自動実行）
- **保存先**:
  - `summary`シート: parse済みデータ（27カラム）
  - `raw_data`シート: 生JSON（分析用）

## ファイル構成

```
scripts/fetch_sleep_to_sheets.py   # メインスクリプト
src/lib/gsheets_client.py          # Google Sheets操作
.github/workflows/daily_sleep.yml  # 自動実行（現在disabled）
config/gcp_service_account.json    # GCP認証情報（要作成）
```

## セットアップ手順

### 1. GCP設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成
2. APIs & Services → Enable APIs:
   - Google Sheets API
   - Google Drive API
3. IAM & Admin → Service Accounts → Create Service Account
4. Keys → Add Key → Create new key → JSON
5. ダウンロードしたJSONを `config/gcp_service_account.json` に配置

### 2. スプレッドシート作成

1. Google Driveで新規スプレッドシート作成
2. URLからSpreadsheet IDを取得:
   ```
   https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit
   ```
3. 共有 → Service AccountのメールアドレスをEditorとして追加
   - メールアドレスは `gcp_service_account.json` 内の `client_email` フィールド

### 3. ローカルテスト

```bash
# gspreadインストール
pip install -r requirements.txt

# CSVのみモード
python scripts/fetch_sleep_to_sheets.py --csv-only

# Sheets書き込みテスト
SPREADSHEET_ID=xxxxx python scripts/fetch_sleep_to_sheets.py
```

### 4. GitHub Secrets設定

Repository Settings → Secrets and variables → Actions → New repository secret

| Secret名 | 内容 | 取得方法 |
|----------|------|----------|
| `FITBIT_CREDS` | Fitbit認証情報 | `cat config/fitbit_creds.json \| jq -c` |
| `FITBIT_TOKEN` | Fitbitトークン | `cat config/fitbit_token.json \| jq -c` |
| `GOOGLE_SERVICE_ACCOUNT` | GCPサービスアカウント | `cat config/gcp_service_account.json \| jq -c` |
| `SPREADSHEET_ID` | スプレッドシートID | URLから取得 |
| `REPO_ACCESS_TOKEN` | GitHub PAT | GitHub Settings → Developer settings → Personal access tokens |

**PAT作成時の権限**: `repo` スコープが必要（Secrets更新用）

### 5. GitHub Actions有効化

`.github/workflows/daily_sleep.yml` のscheduleコメントアウトを解除:

```yaml
on:
  schedule:
    - cron: '0 22 * * *'  # 毎日 07:00 JST
  workflow_dispatch:
```

## 使い方

### ローカル実行

```bash
# 過去14日分取得（デフォルト）
python scripts/fetch_sleep_to_sheets.py

# 日数指定
python scripts/fetch_sleep_to_sheets.py --days 7

# CSVのみ（Sheets書き込みスキップ）
python scripts/fetch_sleep_to_sheets.py --csv-only
```

### 手動実行（GitHub Actions）

Actions → Daily Fitbit Sleep Fetch → Run workflow

## トラブルシューティング

### 認証エラー

```
gspread.exceptions.APIError: 403 PERMISSION_DENIED
```
→ スプレッドシートがService Accountと共有されていない

### Fitbitトークン期限切れ

Fitbitトークンは8時間で期限切れ。GitHub Actionsでは自動更新されるが、ローカルでエラーが出た場合:

```bash
python scripts/fitbit_auth.py
```

## 参考

- [gspread ドキュメント](https://docs.gspread.org/)
- [Google Sheets API](https://developers.google.com/sheets/api)
- [Fitbit Web API](https://dev.fitbit.com/build/reference/web-api/)
