// background service worker — 탭 열고 content script 결과를 서버로 전송

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === 'scrape') {
    handleScrape(msg).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
});

async function handleScrape({ source, url, serverUrl, port, maxPages = 10 }) {
  if (!serverUrl) serverUrl = `http://localhost:${port || 8765}`;
  const contentFile = source === 'coupang' ? 'content/coupang.js' : 'content/naverpay.js';
  const fnName     = source === 'coupang' ? 'collectCoupang'      : 'collectNaverpay';

  let tab;
  let allResults = [];

  if (source === 'naverpay') {
    // ── 네이버페이: 원본 로직 유지 (매 페이지 tabs.update + 고정 1800ms 대기) ──
    const baseUrl = 'https://pay.naver.com/pc/history';
    const startUrl = baseUrl + '?page=1';
    const existing = await chrome.tabs.query({ url: startUrl + '*' });
    if (existing.length > 0) {
      tab = existing[0];
      await chrome.tabs.update(tab.id, { url: startUrl, active: true });
      await waitForLoad(tab.id);
    } else {
      tab = await chrome.tabs.create({ url: startUrl, active: true });
      await waitForLoad(tab.id);
    }

    for (let page = 1; page <= maxPages; page++) {
      const pageUrl = `${baseUrl}?page=${page}`;
      console.log(`[naverpay] navigating to page ${page}:`, pageUrl);
      await chrome.tabs.update(tab.id, { url: pageUrl });
      console.log(`[naverpay] waiting for load...`);
      await waitForLoad(tab.id);
      await waitForSelector(tab.id, '[class*="PaymentItem_item-payment"]');
      console.log(`[naverpay] load done, running script...`);

      const pageResults = await runContentScript(tab.id, contentFile, fnName);
      console.log(`[naverpay] page ${page} results:`, pageResults?.length ?? 'null');
      if (!pageResults || pageResults.length === 0) break;

      allResults = allResults.concat(pageResults);
      try { chrome.runtime.sendMessage({ action: 'progress', source, page, count: allResults.length }); } catch (_) {}
    }
  } else {
    // ── 쿠팡: 멀티페이지 (1페이지 파라미터 없음, 이후 ?pageIndex=N) ──────────
    const getCoupangUrl = (i) => i === 0
      ? 'https://mc.coupang.com/ssr/desktop/order/list'
      : `https://mc.coupang.com/ssr/desktop/order/list?pageIndex=${i}`;

    const startUrl = getCoupangUrl(0);
    const existingTabs = await chrome.tabs.query({ url: 'https://mc.coupang.com/ssr/desktop/order/list*' });
    if (existingTabs.length > 0) {
      tab = existingTabs[0];
      await navigateAndWait(tab.id, startUrl);
    } else {
      tab = await chrome.tabs.create({ url: startUrl, active: true });
      await waitForReady(tab.id);
    }

    for (let i = 0; i < maxPages; i++) {
      if (i > 0) await navigateAndWait(tab.id, getCoupangUrl(i));
      await waitForSelector(tab.id, 'a[href*="vendorItemId="][href*="product_title"]');

      const pageResults = await runContentScript(tab.id, contentFile, fnName);
      if (!pageResults || pageResults.length === 0) break;

      allResults = allResults.concat(pageResults);
      try { chrome.runtime.sendMessage({ action: 'progress', source, page: i + 1, count: allResults.length }); } catch (_) {}
    }
  }

  if (!allResults || allResults.length === 0) {
    return { inserted: 0, skipped: 0, note: '수집된 데이터 없음 — 로그인 확인 필요' };
  }

  // sobify 서버로 전송
  const endpoint = `${serverUrl}/api/sync/${source}`;
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transactions: allResults }),
  });

  if (!resp.ok) throw new Error(`서버 오류 ${resp.status}`);
  return await resp.json();
}

async function runContentScript(tabId, contentFile, fnName) {
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      files: [contentFile],
    });
    return result;
  } catch (_) {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (fn) => window[fn]?.() ?? [],
      args: [fnName],
    });
    return result;
  }
}

// 네이버페이용: complete 이벤트 후 SPA 렌더링 여유를 위해 고정 딜레이 추가
function waitForLoad(tabId, delayMs = 1500) {
  return new Promise(resolve => {
    const check = (id, _info, tab) => {
      if (id === tabId && tab.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(check);
        setTimeout(resolve, delayMs);
      }
    };
    chrome.tabs.onUpdated.addListener(check);
  });
}

// 내비게이션 후 complete 대기 (고정 딜레이 없이 콘텐츠 로드는 waitForSelector가 담당)
async function navigateAndWait(tabId, url) {
  return new Promise(async (resolve) => {
    let finished = false;
    const finish = () => { if (!finished) { finished = true; resolve(); } };

    const check = (id, _info, tab) => {
      if (id === tabId && tab.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(check);
        finish();
      }
    };
    chrome.tabs.onUpdated.addListener(check); // 반드시 update 전에 등록

    const updatedTab = await chrome.tabs.update(tabId, { url });
    if (updatedTab?.status === 'complete') {
      chrome.tabs.onUpdated.removeListener(check);
      finish();
    }
  });
}

// DOM에 특정 셀렉터가 나타날 때까지 폴링 (최대 10초)
async function waitForSelector(tabId, selector, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId },
        func: (sel) => document.querySelectorAll(sel).length,
        args: [selector],
      });
      if (result > 0) return;
    } catch (_) {}
    await new Promise(r => setTimeout(r, 500));
  }
}

// 탭 생성 직후 — loading→complete 또는 이미 complete 모두 처리
function waitForReady(tabId) {
  return new Promise(resolve => {
    let finished = false;
    const finish = () => { if (!finished) { finished = true; resolve(); } };
    let sawLoading = false;
    const check = (id, _info, tab) => {
      if (id !== tabId) return;
      if (tab.status === 'loading') sawLoading = true;
      if (tab.status === 'complete' && sawLoading) {
        chrome.tabs.onUpdated.removeListener(check);
        finish();
      }
    };
    chrome.tabs.onUpdated.addListener(check);
    chrome.tabs.get(tabId).then(tab => {
      if (tab.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(check);
        finish();
      }
    }).catch(finish);
  });
}

