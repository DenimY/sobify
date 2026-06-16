const $ = id => document.getElementById(id);

let port = 8765;

function log(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'log-line' + (type ? ' ' + type : '');
  el.textContent = `[${new Date().toLocaleTimeString('ko')}] ${msg}`;
  $('log').appendChild(el);
  $('log').scrollTop = $('log').scrollHeight;
}

async function checkServer() {
  port = parseInt($('portInput').value) || 8765;
  try {
    const r = await fetch(`http://localhost:${port}/api/health`, { signal: AbortSignal.timeout(2000) });
    const ok = r.ok;
    $('serverDot').className = 'dot ' + (ok ? 'on' : 'off');
    $('serverLabel').textContent = ok ? `서버 연결됨 (포트 ${port})` : '서버 응답 오류';
    return ok;
  } catch {
    $('serverDot').className = 'dot off';
    $('serverLabel').textContent = '서버 꺼짐 — uvicorn 실행 필요';
    return false;
  }
}

async function syncSource(source) {
  const url = source === 'coupang'
    ? 'https://www.coupang.com/my/orders'
    : 'https://pay.naver.com/payments/list/pay';

  log(`${source} 탭 열기...`, 'info');

  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ action: 'scrape', source, url, port }, (resp) => {
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
    log('sobify 서버를 먼저 실행하세요: uvicorn app:app --port ' + port, 'err');
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
$('portInput').addEventListener('change', checkServer);

checkServer();
