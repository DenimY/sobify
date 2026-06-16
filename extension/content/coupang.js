// 쿠팡 주문 내역 수집 — mc.coupang.com/ssr/desktop/order/list (www.coupang.com/my/orders 리다이렉트)
//
// 쿠팡은 styled-components 해시 클래스명(sc-xxxxx-N)을 매 배포마다 바꾸므로
// 클래스명 대신 구조적 패턴(href의 vendorItemId, 텍스트의 "원"/"M/D(요일)")으로 탐색한다.
(function collectCoupang() {
  window.collectCoupang = collectCoupang;

  const results = [];
  const EXCLUDE_STATUS = /취소완료|반품완료|취소요청|반품요청|교환완료/;

  // 한 주문 행(tr) = 날짜/상태 헤더 + 상품 1개 이상
  document.querySelectorAll('tr').forEach(row => {
    const rowText = row.textContent || '';

    const dateMatch = rowText.match(/(\d{1,2})\/(\d{1,2})\([일월화수목금토]\)/);
    if (!dateMatch) return;
    if (EXCLUDE_STATUS.test(rowText)) return;

    const date = toIsoDate(dateMatch[1], dateMatch[2]);

    // 상품명 링크: vendorItemId가 포함되고 'product_title' source인 링크
    const productLinks = row.querySelectorAll('a[href*="vendorItemId="][href*="product_title"]');

    productLinks.forEach(link => {
      const name = link.querySelector('span')?.textContent?.trim();
      if (!name) return;

      const idMatch = link.href.match(/vendorItemId=(\d+)/);
      const vendorItemId = idMatch ? idMatch[1] : null;

      // 가격: 상품 링크의 다음 형제 요소들 중 "00,000 원" 패턴이 있는 곳
      let amount = 0;
      let sib = link.nextElementSibling;
      while (sib) {
        const m = sib.textContent.match(/([\d,]+)\s*원/);
        if (m) { amount = parseInt(m[1].replace(/,/g, ''), 10); break; }
        sib = sib.nextElementSibling;
      }
      if (!amount) return;

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
        // 같은 상품을 다른 날 재구매할 수 있으므로 날짜·금액까지 합쳐 고유화
        external_id: vendorItemId ? `${vendorItemId}_${date}_${amount}` : null,
      });
    });
  });

  return results;

  function toIsoDate(month, day) {
    const m = parseInt(month, 10);
    const now = new Date();
    let year = now.getFullYear();
    const curMonth = now.getMonth() + 1;
    // 연도 표시가 없으므로, 현재보다 한참 미래인 달이면 작년 주문으로 추정 (연말연시 경계 보정)
    if (m > curMonth + 2) year -= 1;
    return `${year}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }
})();
