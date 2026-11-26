"""Amazon・楽天・メルカリの価格を並行で引き、1枚の表にする（購入はしない）。

  uv run scripts/price.py 'Tapo C220'
  uv run scripts/price.py 'Garmin Edge 840' --min 20000
  uv run scripts/price.py 'Tapo C220 マウント' --exclude ''

品名の単語をすべて含む商品だけ残す。本体を探すときはアクセサリー語（--exclude）と
下限価格（--min）で落とす。Amazon の先頭の商品は Keepa の価格推移グラフを保存する。
どれかの店が取れなくても他は出し、取れなかった店は理由を出す。
いずれもログインなしの値。楽天のポイントは SPU を含まない。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import argparse
import asyncio
import html
import json
import re
import statistics
import tempfile
from datetime import datetime, timedelta

import httpx
from mercapi import Mercapi
from mercapi.requests import SearchRequestData as R

from lib.utils.private_data import require_private_path

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
BASE_DIR = Path(__file__).parent.parent
PURCHASES_DIR = BASE_DIR / 'data' / 'purchases'
SOLD_DAYS = 90
DEFAULT_EXCLUDE = "ケース カバー フィルム マウント スタンド ブラケット 金具 アーム ホルダー"


def matches(name: str, words: list[str], exclude: list[str]) -> bool:
    n = name.lower()
    return all(w in n for w in words) and not any(x in n for x in exclude)


async def get(client, url, params=None):
    """503 は一時的な混雑で返ることがあるので1回だけ待って再試行する。"""
    r = await client.get(url, params=params)
    if r.status_code == 503:
        await asyncio.sleep(2)
        r = await client.get(url, params=params)
    r.raise_for_status()
    return r


async def amazon(client, q, words, exclude, pmin):
    r = await get(client, "https://www.amazon.co.jp/s", {"k": q})
    if "captcha" in r.text.lower():
        raise RuntimeError("CAPTCHA")
    rows = []
    for b in re.split(r'(?=<div role="listitem" data-asin=")', r.text)[1:]:
        if "puis-sponsored" in b:
            continue
        asin = re.search(r'data-asin="(\w+)"', b).group(1)
        t = re.search(r'<h2[^>]*aria-label="([^"]*)"', b) or re.search(r"<h2.*?<span>(.*?)</span>", b, re.S)
        p = re.search(r'a-price-whole">([\d,]+)', b)
        if not (t and p):
            continue
        name, price = html.unescape(t.group(1)), int(p.group(1).replace(",", ""))
        # 検索結果の商品名は途中で切れ型番が抜けるので、Amazon は関連度順に任せ語の一致は見ない
        if price >= pmin and matches(name, [], exclude):
            rows.append((price, None, name, f"https://www.amazon.co.jp/dp/{asin}", asin))
    return rows


async def rakuten(client, q, words, exclude, pmin):
    r = await get(client, f"https://search.rakuten.co.jp/search/mall/{q}/", {"min": pmin or None})
    dec, seen, rows, pos = json.JSONDecoder(), set(), [], 0
    while (i := r.text.find('"items":[', pos)) != -1:
        try:
            arr, pos = dec.raw_decode(r.text, i + 8)
        except json.JSONDecodeError:
            pos = i + 1
            continue
        for it in arr:
            if not isinstance(it, dict) or "price" not in it or it.get("url") in seen:
                continue
            seen.add(it["url"])
            name = it.get("name", "")
            if it["price"] < pmin or not matches(name, words, exclude):
                continue
            ship = (it.get("shipping") or {}).get("price") or 0
            point = (it.get("point") or {}).get("count") or 0
            rows.append((it["price"] + ship, point, name, it["url"].split("?")[0], (it.get("shop") or {}).get("name")))
    return sorted(rows)


def mercari_url(item_id: str) -> str:
    kind = "item" if item_id.startswith("m") else "shops/product"
    return f"https://jp.mercari.com/{kind}/{item_id}"


async def mercari(q, words, exclude, pmin):
    m = Mercapi()
    out = {}
    for st in (R.Status.STATUS_ON_SALE, R.Status.STATUS_SOLD_OUT):
        r = await m.search(q, status=[st], price_min=pmin or None, sort_by=R.SortBy.SORT_CREATED_TIME)
        out[st] = [i for i in r.items if matches(i.name, words, exclude)]
    on_sale = sorted((i.price, None, i.name, mercari_url(i.id_), None) for i in out[R.Status.STATUS_ON_SALE])
    return on_sale, out[R.Status.STATUS_SOLD_OUT]


async def keepa(client, asin):
    r = await client.get("https://graph.keepa.com/pricehistory.png",
                         params={"asin": asin, "domain": "co.jp", "range": 365})
    r.raise_for_status()
    path = Path(tempfile.gettempdir()) / "shopping" / f"keepa_{asin}.png"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(r.content)
    return path


def purchases(words):
    hits = []
    for f in sorted(require_private_path(PURCHASES_DIR).glob("*.csv")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if all(w in line.lower() for w in words):
                hits.append(f"{f.stem}: {line[:160]}")
    return hits


def show_rows(title, rows, n, point=False):
    print(f"\n## {title}（{len(rows)}件）")
    for price, pt, name, url, extra in rows[:n]:
        pts = f" +{pt}pt" if point else ""
        print(f"  {price:>7,}円{pts}  {name[:50]}  {url}")


async def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("--min", type=int, default=0, help="下限価格（アクセサリー落とし）")
    ap.add_argument("--exclude", default=DEFAULT_EXCLUDE, help="除外する語（空白区切り、'' で無効）")
    ap.add_argument("-n", type=int, default=5, help="店ごとの表示件数")
    a = ap.parse_args()
    words, exclude = a.query.lower().split(), a.exclude.lower().split()

    async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "ja-JP"},
                                 follow_redirects=True, timeout=30) as client:
        res = await asyncio.gather(
            amazon(client, a.query, words, exclude, a.min),
            rakuten(client, a.query, words, exclude, a.min),
            mercari(a.query, words, exclude, a.min),
            return_exceptions=True,
        )
        az, rk, mc = res
        graph = None
        if not isinstance(az, Exception) and az:
            try:
                graph = await keepa(client, az[0][4])
            except httpx.HTTPError as e:
                graph = f"取得失敗: {e!r}"

    hist = purchases(words)
    if hist:
        print("## 過去の購入")
        for h in hist[-5:]:
            print(f"  {h}")

    for title, r in (("Amazon（関連度順・スポンサー除く）", az), ("楽天（送料込み安い順・ポイントは SPU 抜き）", rk)):
        if isinstance(r, Exception):
            print(f"\n## {title}\n  取得失敗: {r!r}")
        else:
            show_rows(title, r, a.n, point=title.startswith("楽天"))
    if graph:
        print(f"  Keepa（先頭商品の1年推移）: {graph}")

    if isinstance(mc, Exception):
        print(f"\n## メルカリ\n  取得失敗: {mc!r}")
        return
    on_sale, sold = mc
    show_rows("メルカリ出品中（安い順）", on_sale, a.n)
    since = datetime.now() - timedelta(days=SOLD_DAYS)
    prices = sorted(i.price for i in sold if i.updated >= since)
    print(f"\n## メルカリ SOLD（直近{SOLD_DAYS}日 {len(prices)}件）")
    if len(prices) >= 4:
        q1, med, q3 = statistics.quantiles(prices, n=4)
        print(f"  中央値 {med:,.0f}円  中央50% {q1:,.0f}〜{q3:,.0f}円  全体 {prices[0]:,}〜{prices[-1]:,}円")
    elif prices:
        print(f"  {', '.join(f'{p:,}円' for p in prices)}")


if __name__ == "__main__":
    asyncio.run(main())
