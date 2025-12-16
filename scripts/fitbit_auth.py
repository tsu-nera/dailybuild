#!/usr/bin/env python
# coding: utf-8
"""
Fitbit OAuth2 認証スクリプト

使い方:
1. config/fitbit_creds.json に client_id と client_secret を設定
2. このスクリプトを実行: python scripts/fitbit_auth.py
3. ブラウザで認証を完了
4. config/fitbit_token.json が生成される
"""

import json
import sys
import webbrowser
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import fitbit

BASE_DIR = Path(__file__).parent.parent
CREDS_FILE_DEV = BASE_DIR / 'config/fitbit_creds_dev.json'
TOKEN_FILE_DEV = BASE_DIR / 'config/fitbit_token_dev.json'
CREDS_FILE_PROD = BASE_DIR / 'config/fitbit_creds.json'
TOKEN_FILE_PROD = BASE_DIR / 'config/fitbit_token.json'
REDIRECT_URI = 'http://127.0.0.1:8080/'


class OAuthHandler(BaseHTTPRequestHandler):
    """OAuth2コールバックを受け取るハンドラ"""

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()

        query = parse_qs(urlparse(self.path).query)

        if 'code' in query:
            self.server.auth_code = query['code'][0]
            message = '<h1>認証成功!</h1><p>このウィンドウを閉じてください。</p>'
        else:
            self.server.auth_code = None
            message = '<h1>認証失敗</h1><p>もう一度試してください。</p>'

        self.wfile.write(message.encode('utf-8'))

    def log_message(self, format, *args):
        pass  # ログを抑制


def create_creds_template(creds_file):
    """認証情報テンプレートを作成"""
    creds_file.parent.mkdir(exist_ok=True)
    template = {
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    with open(creds_file, 'w') as f:
        json.dump(template, f, indent=2)
    print(f"テンプレートを作成しました: {creds_file}")
    print("client_id と client_secret を設定してから再実行してください。")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Fitbit OAuth2認証')
    parser.add_argument('--env', choices=['dev', 'prod'], default='dev',
                       help='環境選択: dev (開発用) または prod (GitHub Actions用)')
    args = parser.parse_args()

    # 環境に応じたファイルを選択
    if args.env == 'prod':
        creds_file = CREDS_FILE_PROD
        token_file = TOKEN_FILE_PROD
        env_name = "本番（GitHub Actions用）"
    else:
        creds_file = CREDS_FILE_DEV
        token_file = TOKEN_FILE_DEV
        env_name = "開発（ローカル用）"

    print("=" * 60)
    print(f"Fitbit OAuth2 認証 - {env_name}")
    print("=" * 60)

    # 認証情報の確認
    if not creds_file.exists():
        print(f"\n認証情報ファイルが見つかりません: {creds_file}")
        create_creds_template(creds_file)
        sys.exit(1)

    with open(creds_file, 'r') as f:
        creds = json.load(f)

    if creds.get('client_id') == 'YOUR_CLIENT_ID':
        print(f"\n{creds_file} に正しい認証情報を設定してください。")
        print("\nFitbit Developer Portal (https://dev.fitbit.com/) で:")
        print("  1. アプリを登録")
        print("  2. OAuth 2.0 Client ID と Client Secret を取得")
        print(f"  3. Callback URL に {REDIRECT_URI} を設定")
        sys.exit(1)

    # OAuth2クライアント作成
    server = fitbit.Fitbit(
        creds['client_id'],
        creds['client_secret'],
        redirect_uri=REDIRECT_URI,
        timeout=10
    )

    # 認証URL生成（必要な全スコープを指定）
    scopes = [
        'activity',
        'cardio_fitness',                    # VO2 Max
        'electrocardiogram',                 # ECG（心電図）※ Charge 6対応
        'heartrate',
        'irregular_rhythm_notifications',    # 不整脈通知 ※ Charge 6対応
        'location',
        'nutrition',
        'oxygen_saturation',                 # SpO2（血中酸素濃度）
        'profile',
        'respiratory_rate',                  # 呼吸数
        'settings',
        'sleep',
        'social',
        'temperature',                       # 体温データ
        'weight',
    ]
    url, _ = server.client.authorize_token_url(scope=scopes)
    print(f"\nブラウザで認証ページを開きます...")
    print(f"スコープ: {', '.join(scopes)}")
    print(f"URL: {url}\n")
    webbrowser.open(url)

    # コールバック待機
    print("認証完了を待機中... (Ctrl+C でキャンセル)")
    httpd = HTTPServer(('127.0.0.1', 8080), OAuthHandler)
    httpd.auth_code = None

    try:
        httpd.handle_request()
    except KeyboardInterrupt:
        print("\nキャンセルされました。")
        sys.exit(1)

    if not httpd.auth_code:
        print("認証コードを取得できませんでした。")
        sys.exit(1)

    # トークン取得
    print("トークンを取得中...")
    try:
        token = server.client.fetch_access_token(httpd.auth_code)
    except Exception as e:
        print(f"トークン取得エラー: {e}")
        sys.exit(1)

    # トークン保存
    with open(token_file, 'w') as f:
        json.dump(token, f, indent=2)

    print(f"\n認証完了!")
    print(f"トークンを保存しました: {token_file}")

    if args.env == 'prod':
        print("\n次のステップ:")
        print("  1. 以下のトークン内容をコピー:")
        print(f"     cat {token_file}")
        print("  2. GitHub → Settings → Secrets → FITBIT_TOKEN を更新")
    else:
        print("\n以下のコマンドでデータを取得できます:")
        print("  python scripts/fetch_fitbit.py --all")


if __name__ == '__main__':
    main()
