// 쿠팡 주문 내역 수집 — mc.coupang.com/ssr/desktop/order/list
//
// 쿠팡 styled-components 클래스명은 배포마다 해시가 바뀌므로 클래스명 의존 최소화.
// 안정적인 패턴: vendorItemId 포함 링크, "YYYY. M. D 주문" 텍스트, "N,NNN 원" 패턴.
(function collectCoupang() {
  window.collectCoupang = collectCoupang;

  const results = [];
  const EXCLUDE_STATUS = /취소완료|반품완료|취소요청|반품요청|교환완료/;

  // 상품 타이틀 링크 기준으로 순회
  document.querySelectorAll('a[href*="vendorItemId="][href*="product_title"]').forEach(link => {
    const row = link.closest('tr');
    if (!row) return;

    // 취소/반품 행 제외 (row 전체 텍스트 기준)
    if (EXCLUDE_STATUS.test(row.textContent)) return;

    // ── 상품명: 링크 내 모든 span 텍스트를 합산 ──────────────────────────────
    // [반품-상] 같은 태그가 첫 span에 들어오는 경우를 포함해 전체를 이어붙임
    const nameSpans = [...link.querySelectorAll('span')];
    const name = nameSpans.length > 0
      ? nameSpans.map(s => s.textContent.trim()).filter(Boolean).join('')
      : link.textContent.trim();
    if (!name) return;

    // ── 가격: 링크 바깥 row에서 "N,NNN 원" 패턴 첫 번째 ─────────────────────
    let amount = 0;
    for (const span of row.querySelectorAll('span')) {
      if (link.contains(span)) continue; // 상품명 span 제외
      const m = span.textContent.trim().match(/^([\d,]+)\s*원$/);
      if (m) { amount = parseInt(m[1].replace(/,/g, ''), 10); break; }
    }
    if (!amount) return;

    // ── 주문일: 조상 중에서 "YYYY. M. D 주문" 텍스트를 가진 div 탐색 ─────────
    // 최대 8단계 위까지 올라가며 해당 div를 찾음 (너무 높이 올라가면 다른 주문 날짜 잡힐 수 있음)
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

    const idMatch = link.href.match(/vendorItemId=(\d+)/);
    const vendorItemId = idMatch ? idMatch[1] : null;

    results.push({
      date,
      time: '',
      desc: name,
      amount,
      type: '지출',
      cat: '온라인쇼핑',
      subcat: '쿠팡',
      method: '쿠팡',
      memo: '',
      external_id: vendorItemId ? `${vendorItemId}_${date}_${amount}` : null,
    });
  });

  return results;
})();
