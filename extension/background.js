// background service worker — 탭 열고 content script 결과를 서버로 전송

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action === 'scrape') {
    handleScrape(msg).then(sendResponse).catch(e => sendResponse({ error: e.message }));
    return true; // async
  }
});

async function handleScrape({ source, url, port }) {
  // 1. 이미 열린 탭 재사용 or 새 탭
  const existing = await chrome.tabs.query({ url: url + '*' });
  let tab;
  if (existing.length > 0) {
    tab = existing[0];
    await chrome.tabs.update(tab.id, { active: true });
  } else {
    tab = await chrome.tabs.create({ url, active: true });
    await waitForLoad(tab.id);
  }

  // 2. content script 실행해서 데이터 수집
  const contentFile = source === 'coupang'
    ? 'content/coupang.js'
    : 'content/naverpay.js';

  let results;
  try {
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: [contentFile],
    });
    results = result;
  } catch (e) {
    // content script가 이미 주입된 경우 함수 직접 호출
    const fnName = source === 'coupang' ? 'collectCoupang' : 'collectNaverpay';
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => window[fnName]?.() ?? [],
    });
    results = result;
  }

  if (!results || results.length === 0) {
    return { inserted: 0, skipped: 0, note: '수집된 데이터 없음 — 로그인 확인 필요' };
  }

  // 3. sobify 서버로 전송
  const endpoint = `http://localhost:${port}/api/sync/${source}`;
  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transactions: results }),
  });

  if (!resp.ok) {
    throw new Error(`서버 오류 ${resp.status}`);
  }

  return await resp.json();
}

function waitForLoad(tabId) {
  return new Promise(resolve => {
    const listener = (id, _info, tab) => {
      if (id === tabId && tab.status === 'complete') {
        chrome.tabs.onUpdated.removeListener(listener);
        // 동적 렌더링 여유 시간
        setTimeout(resolve, 1500);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}
