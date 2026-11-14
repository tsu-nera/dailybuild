#!/usr/bin/env python3
"""
Grafana の画面を headless Chromium で開き、パネルごとのテキストとスクリーンショットを出す（docs/grafana.md）

agent が画面を確かめる手段。`/api/ds/query` が通っても画面側の Infinity だけが落ちることがあるので、
クエリの確認では足りない。値・エラーは stdout のテキストで見て、画像は見た目（文字の重なり・切れ・大きさ）を
直したときだけ開く（画像は1枚 1k トークン以上かかる）。

認証は API と同じ admin の Basic 認証をヘッダーで渡す（ログイン画面には入力しない）。パスワードは環境変数
GF_SECURITY_ADMIN_PASSWORD、無ければ scripts/ops/grafana/.env（vaio にだけある）から読む。

Usage:
    GF_SECURITY_ADMIN_PASSWORD=$(ssh vaio 'grep ^GF_SECURITY_ADMIN_PASSWORD ~/repo/dailybuild/scripts/ops/grafana/.env | cut -d= -f2-') \\
        uv run scripts/ops/grafana/shot.py goals meditation [--out tmp/grafana] [--base http://vaio:3000]
    画面ごとに <out>/<uid>-phone.png（390px）と <uid>-pc.png（1440px）を書く。
    stdout にはパネルごとに「タイトル: 中身のテキスト」とエラーを出す。
"""

import argparse
import base64
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
VIEWS = {'phone': {'width': 390, 'height': 844}, 'pc': {'width': 1440, 'height': 900}}
# パネルは値が出るまで約8秒かかる。枠（タイトル）だけの段階で撮ると中身が空になる
LOAD_TIMEOUT_MS = 30000
SETTLE_MS = 1500
# 毎回出るが表示とは無関係
IGNORED = ('/public-dashboards',)


def _password() -> str:
    pw = os.environ.get('GF_SECURITY_ADMIN_PASSWORD')
    if pw:
        return pw
    env = HERE / '.env'
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith('GF_SECURITY_ADMIN_PASSWORD='):
                return line.split('=', 1)[1].strip()
    sys.exit('GF_SECURITY_ADMIN_PASSWORD が無い（Usage の ssh vaio の行を参照）')


def _collect(page, found: dict) -> None:
    """いま DOM にあるパネルのテキストを集める。グラフ（canvas）は文字を持たないので印だけ付ける"""
    for el in page.locator('[data-viz-panel-key]').all():
        lines = [t.strip() for t in el.inner_text().splitlines() if t.strip()]
        if not lines:
            continue
        body = ' | '.join(lines[1:])
        if el.locator('canvas').count():
            body = f'(グラフ) {body}'.strip()
        found.setdefault(lines[0], body)


def _load_all(page) -> dict[str, str]:
    """パネルは画面に入ってから描くので、下へ送りながら読み込みを待ってテキストを集め、最後に先頭へ戻す"""
    page.wait_for_selector('[data-viz-panel-key]', timeout=LOAD_TIMEOUT_MS)
    vp = page.viewport_size
    page.mouse.move(vp['width'] / 2, vp['height'] / 2)
    found: dict[str, str] = {}
    last = None
    for _ in range(30):
        page.wait_for_function(
            "() => !document.querySelector('[aria-label=\"Panel loading bar\"], [data-testid=\"data-testid panel content loading\"]')",
            timeout=LOAD_TIMEOUT_MS)
        page.wait_for_timeout(SETTLE_MS)
        _collect(page, found)
        page.mouse.wheel(0, vp['height'] * 0.8)
        page.wait_for_timeout(300)
        pos = page.evaluate("() => [...document.querySelectorAll('*')].reduce((a, e) => a + e.scrollTop, 0)")
        if pos == last:
            break
        last = pos
    page.mouse.wheel(0, -100000)
    page.wait_for_timeout(SETTLE_MS)
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('uids', nargs='+')
    ap.add_argument('--out', default='tmp/grafana')
    ap.add_argument('--base', default=os.environ.get('GRAFANA_URL', 'http://vaio:3000'))
    ap.add_argument('--views', default='phone,pc', help='phone,pc のどちらか・両方')
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    auth = 'Basic ' + base64.b64encode(f'admin:{_password()}'.encode()).decode()
    failed = False
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for view in args.views.split(','):
            ctx = browser.new_context(viewport=VIEWS[view], extra_http_headers={'Authorization': auth},
                                      locale='ja-JP')
            page = ctx.new_page()
            errors: list[str] = []
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('response', lambda r: errors.append(f'HTTP {r.status} {r.url}')
                    if r.status >= 400 and not any(s in r.url for s in IGNORED) else None)
            for uid in args.uids:
                errors.clear()
                page.goto(f'{args.base}/d/{uid}', wait_until='networkidle')
                panels: dict[str, str] = {}
                try:
                    panels = _load_all(page)
                except Exception as e:  # 読み込みが終わらなくても、撮れた範囲は残す
                    errors.append(f'読み込み待ちが打ち切られた: {type(e).__name__}')
                path = out / f'{uid}-{view}.png'
                page.screenshot(path=str(path), full_page=True)
                # 画面幅で中身は変わらないので、テキストは最初の幅でだけ出す
                print(f'== {uid} ({view}) {path}')
                if view == args.views.split(',')[0]:
                    for title, body in panels.items():
                        print(f'  {title}: {body[:300]}')
                errors = [e for e in errors if not e.startswith('Failed to load resource')]
                for e in errors:
                    print(f'  ERROR {e}')
                failed |= bool(errors)
            ctx.close()
        browser.close()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
