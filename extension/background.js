// background service worker — 탭 열고 content script 결과를 서버로 전송

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === 'scrape') {
    handleScrape(msg).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true;
  }
});

async function handleScrape({ source, url, port }) {
  const baseUrl = source === 'naverpay'
    ? 'https://pay.naver.com/pc/history'
    : null; // 쿠팡은 단일 페이지

  // 탭 열기 (항상 page=1 or 기본 URL)
  const startUrl = baseUrl ? baseUrl + '?page=1' : url;
  const existing = await chrome.tabs.query({ url: startUrl + '*' });
  let tab;
  if (existing.length > 0) {
    tab = existing[0];
    await chrome.tabs.update(tab.id, { url: startUrl, active: true });
    await waitForLoad(tab.id);
  } else {
    tab = await chrome.tabs.create({ url: startUrl, active: true });
    await waitForLoad(tab.id);
  }

  const contentFile = source === 'coupang'
    ? 'content/coupang.js'
    : 'content/naverpay.js';
  const fnName = source === 'coupang' ? 'collectCoupang' : 'collectNaverpay';

  let allResults = [];

  if (baseUrl) {
    // 멀티페이지: 빈 페이지가 나올 때까지 순회 (최대 30페이지)
    for (let page = 1; page <= 30; page++) {
      const pageUrl = `${baseUrl}?page=${page}`;
      await chrome.tabs.update(tab.id, { url: pageUrl });
      await waitForLoad(tab.id);

      const pageResults = await runContentScript(tab.id, contentFile, fnName);
      if (!pageResults || pageResults.length === 0) break;

      allResults = allResults.concat(pageResults);

      // popup에 진행 상황 알림
      try {
        chrome.runtime.sendMessage({ action: 'progress', source, page, count: allResults.length });
      } catch (_) {}
    }
  } else {
    // 단일 페이지 (쿠팡)
    allResults = await runContentScript(tab.id, contentFile, fnName);
  }

  if (!allResults || allResults.length === 0) {
    return { inserted: 0, skipped: 0, note: '수집된 데이터 없음 — 로그인 확인 필요' };
  }

  // sobify 서버로 전송
  const endpoint = `http://localhost:${port}/api/sync/${source}`;
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

function waitForLoad(tabId) {
  return new Promise(resolve => {
    const check = (id, _info, tab) => {
      if (id === tabId && tab.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(check);
        setTimeout(resolve, 1800); // 동적 렌더링 여유
      }
    };
    chrome.tabs.onUpdated.addListener(check);
  });
}
