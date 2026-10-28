// 楽天市場の購入履歴を全ページ集めて返す（rakuten_history.py が読む）
//
// ログイン済みのブラウザで https://order.my.rakuten.co.jp/purchase-history/order-list を開き、
// chrome-devtools-mcp の evaluate_script（function にこのファイルの中身、filePath に出力先）か、
// DevTools のコンソールに貼って実行する。sourcePath は MCP のワークスペース外だと拒否される。
async () => {
  const listData = async (page) => {
    const html = await (await fetch(`/purchase-history/order-list?page=${page}`)).text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const script = [...doc.scripts].find((s) => s.textContent.includes('__INITIAL_STATE__ ='));
    if (!script) throw new Error(`page=${page} に __INITIAL_STATE__ が無い（ログイン切れ?）`);
    const text = script.textContent;
    const state = JSON.parse(text.slice(text.indexOf('=') + 1, text.lastIndexOf('}') + 1));
    return state.orderListData;
  };

  const first = await listData(1);
  const orders = [...first.orderList];
  const pages = Math.ceil(first.ordersFound / first.pageSize);
  for (let page = 2; page <= pages; page++) {
    orders.push(...(await listData(page)).orderList);
  }
  return { ordersFound: first.ordersFound, orders };
}
