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
CREDS_FILE = BASE_DIR / 'config/fitbit_creds.json'
TOKEN_FILE = BASE_DIR / 'config/fitbit_token.json'
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


def create_creds_template():
    """認証情報テンプレートを作成"""
    CREDS_FILE.parent.mkdir(exist_ok=True)
    template = {
        "client_id": "YOUR_CLIENT_ID",
        "client_secret": "YOUR_CLIENT_SECRET"
    }
    with open(CREDS_FILE, 'w') as f:
        json.dump(template, f, indent=2)
    print(f"テンプレートを作成しました: {CREDS_FILE}")
    print("client_id と client_secret を設定してから再実行してください。")


def main():
    print("=" * 50)
    print("Fitbit OAuth2 認証")
    print("=" * 50)

    # 認証情報の確認
    if not CREDS_FILE.exists():
        print(f"\n認証情報ファイルが見つかりません: {CREDS_FILE}")
        create_creds_template()
        sys.exit(1)

    with open(CREDS_FILE, 'r') as f:
        creds = json.load(f)

    if creds.get('client_id') == 'YOUR_CLIENT_ID':
        print(f"\n{CREDS_FILE} に正しい認証情報を設定してください。")
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

    # 認証URL生成
    url, _ = server.client.authorize_token_url()
    print(f"\nブラウザで認証ページを開きます...")
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
    with open(TOKEN_FILE, 'w') as f:
        json.dump(token, f, indent=2)

    print(f"\n認証完了!")
    print(f"トークンを保存しました: {TOKEN_FILE}")
    print("\n以下のコマンドで睡眠データを取得できます:")
    print("  python scripts/fetch_sleep.py")


if __name__ == '__main__':
    main()
