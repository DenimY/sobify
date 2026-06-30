// 쿠팡 주문 내역 수집 — mc.coupang.com/ssr/desktop/order/list
//
// 쿠팡 styled-components 클래스명은 배포마다 해시가 바뀌므로 클래스명 의존 최소화.
// 안정적인 패턴: vendorItemId 포함 링크, "YYYY. M. D 주문" 텍스트, "N,NNN 원" 패턴.
(function collectCoupang() {
  window.collectCoupang = collectCoupang;

  const results = [];
  const CANCEL_STATUS = /취소완료|반품완료|취소요청|반품요청|교환완료/;

  // 배송 카드 컨테이너 탐색: 링크에서 위로 올라가며
  // "배송완료/배송중/배송준비중/결제완료" 텍스트가 첫 자식에 있는 요소를 배송 카드로 판단
  const SHIP_STATUS_RE = /배송완료|배송중|배송준비|결제완료|구매확정/;
  const shipmentIndexMap = new WeakMap();
  let shipmentCounter = 0;

  function findShipmentCard(el) {
    let cur = el.parentElement;
    for (let i = 0; i < 15 && cur; i++, cur = cur.parentElement) {
      const first = cur.firstElementChild;
      if (first && SHIP_STATUS_RE.test(first.textContent)) return cur;
    }
    return null;
  }

  // 상품 타이틀 링크 기준으로 순회
  document.querySelectorAll('a[href*="vendorItemId="][href*="product_title"]').forEach(link => {
    const row = link.closest('tr');
    if (!row) return;

    // 취소/반품 여부 감지 (제외하지 않고 type='취소'로 수집)
    const isCancelled = CANCEL_STATUS.test(row.textContent);

    // ── 상품명 ──────────────────────────────────────────────────────────────
    const nameSpans = [...link.querySelectorAll('span')];
    const name = nameSpans.length > 0
      ? nameSpans.map(s => s.textContent.trim()).filter(Boolean).join('')
      : link.textContent.trim();
    if (!name) return;

    // ── 가격 ────────────────────────────────────────────────────────────────
    let amount = 0;
    for (const span of row.querySelectorAll('span')) {
      if (link.contains(span)) continue;
      const m = span.textContent.trim().match(/^([\d,]+)\s*원$/);
      if (m) { amount = parseInt(m[1].replace(/,/g, ''), 10); break; }
    }
    if (!amount) return;

    // ── 주문일 ──────────────────────────────────────────────────────────────
    let date = '';
    let el = row.parentElement;
    for (let i = 0; i < 8 && el && !date; i++, el = el.parentElement) {
      const dateEl = [...el.querySelectorAll('div')].find(
        d => /^\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\s*주문$/.test(d.textContent.trim())
      );
      if (dateEl) {
        const m = dateEl.textContent.match(/(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})/);
        if (m) date = `${m[1]}-${String(parseInt(m[2])).padStart(2,'0')}-${String(parseInt(m[3])).padStart(2,'0')}`;
      }
    }
    if (!date) return;

    // ── 배송 카드 단위 bundle_id ─────────────────────────────────────────────
    // 같은 배송 카드(배송완료 블록) 안의 상품들 = 하나의 결제 묶음
    const card = findShipmentCard(link);
    let bundle_id = null;
    if (card) {
      if (!shipmentIndexMap.has(card)) {
        shipmentIndexMap.set(card, shipmentCounter++);
      }
      bundle_id = `coupang_${date}_${shipmentIndexMap.get(card)}`;
    }

    const idMatch = link.href.match(/vendorItemId=(\d+)/);
    const vendorItemId = idMatch ? idMatch[1] : null;

    results.push({
      date,
      time: '',
      desc: name,
      amount,
      type: isCancelled ? '취소' : '지출',
      cat: '온라인쇼핑',
      subcat: '쿠팡',
      method: '쿠팡',
      memo: '',
      external_id: vendorItemId ? `${vendorItemId}_${date}_${amount}` : null,
      bundle_id,
    });
  });

  return results;
})();
