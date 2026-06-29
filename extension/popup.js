const $ = id => document.getElementById(id);

let serverUrl = 'http://localhost:8765';
let maxPages = 10;

function log(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'log-line' + (type ? ' ' + type : '');
  el.textContent = `[${new Date().toLocaleTimeString('ko')}] ${msg}`;
  $('log').appendChild(el);
  $('log').scrollTop = $('log').scrollHeight;
}

function normalizeUrl(raw) {
  let url = raw.trim().replace(/\/+$/, '');
  if (!/^https?:\/\//i.test(url)) url = 'http://' + url;
  return url;
}

async function checkServer() {
  serverUrl = normalizeUrl($('serverUrlInput').value || 'http://localhost:8765');
  $('serverUrlInput').value = serverUrl;
  maxPages = parseInt($('maxPagesInput').value) || 10;

  // 설정 저장
  chrome.storage.sync.set({ serverUrl, maxPages });

  try {
    const r = await fetch(`${serverUrl}/api/health`, { signal: AbortSignal.timeout(3000) });
    const ok = r.ok;
    $('serverDot').className = 'dot ' + (ok ? 'on' : 'off');
    $('serverLabel').textContent = ok ? `서버 연결됨` : '서버 응답 오류';
    return ok;
  } catch {
    $('serverDot').className = 'dot off';
    $('serverLabel').textContent = '서버 꺼짐 — 주소 확인 필요';
    return false;
  }
}

// 페이지 진행 상황 수신
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === 'progress') {
    log(`${msg.source} 페이지 ${msg.page} 수집 중... (누적 ${msg.count}건)`, 'info');
  }
});

async function syncSource(source) {
  const url = source === 'coupang'
    ? 'https://mc.coupang.com/ssr/desktop/order/list'
    : 'https://pay.naver.com/pc/history?page=1';

  log(`${source} 동기화 시작 (전 페이지 순회)...`, 'info');

  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ action: 'scrape', source, url, serverUrl, maxPages }, (resp) => {
      if (chrome.runtime.lastError) {
        log('확장 오류: ' + chrome.runtime.lastError.message, 'err');
        resolve(false);
        return;
      }
      if (resp?.error) {
        log(resp.error, 'err');
        resolve(false);
      } else {
        log(`${source}: ${resp.inserted}건 추가, ${resp.skipped}건 중복 건너뜀`, 'ok');
        resolve(true);
      }
    });
  });
}

function setLoading(loading) {
  ['btnAll', 'btnCoupang', 'btnNaver'].forEach(id => {
    $(id).disabled = loading;
  });
}

async function runSync(sources) {
  const ok = await checkServer();
  if (!ok) {
    log('sobify 서버를 먼저 실행하고 주소를 확인하세요: ' + serverUrl, 'err');
    return;
  }
  setLoading(true);
  for (const src of sources) {
    await syncSource(src);
  }
  setLoading(false);
  log('동기화 완료. sobify 새로고침 하세요.', 'ok');
}

$('btnAll').addEventListener('click', () => runSync(['coupang', 'naverpay']));
$('btnCoupang').addEventListener('click', () => runSync(['coupang']));
$('btnNaver').addEventListener('click', () => runSync(['naverpay']));
$('serverUrlInput').addEventListener('change', checkServer);
$('maxPagesInput').addEventListener('change', checkServer);

// 저장된 설정 불러오기
chrome.storage.sync.get(['serverUrl', 'maxPages'], (data) => {
  if (data.serverUrl) {
    serverUrl = data.serverUrl;
    $('serverUrlInput').value = serverUrl;
  }
  if (data.maxPages) {
    maxPages = data.maxPages;
    $('maxPagesInput').value = maxPages;
  }
  checkServer();
});
