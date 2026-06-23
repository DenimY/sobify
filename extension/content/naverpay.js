// 네이버페이 결제 내역 수집 — pay.naver.com 결제 내역 페이지
//
// 네이버페이는 CSS Modules 클래스명(PaymentItem_xxx__hash)을 쓰는데,
// 해시 접미사는 배포마다 바뀌지만 의미있는 접두사(PaymentItem_price, OrderStatus_value 등)는
// 비교적 안정적이므로 [class*="..."] 부분 일치로 탐색한다.
(function collectNaverpay() {
  window.collectNaverpay = collectNaverpay;

  const results = [];
  const EXCLUDE_STATUS = /결제취소|반품완료|취소접수|환불완료|교환완료/;

  document.querySelectorAll('[class*="PaymentItem_item-payment"]').forEach(item => {
    const statusEl = item.querySelector('[class*="OrderStatus_value"]');
    const status = statusEl?.textContent?.trim() || '';
    if (EXCLUDE_STATUS.test(status)) return;

    const nameEl = item.querySelector('[class*="ProductName_name"]');
    const name = nameEl?.textContent?.trim();
    if (!name) return;

    const priceEl = item.querySelector('[class*="PaymentItem_price"]');
    const amount = parseInt((priceEl?.textContent || '').replace(/[^0-9]/g, ''), 10) || 0;
    if (!amount) return;

    const timeEl = item.querySelector('[class*="PaymentItem_time"]');
    const rawDate = timeEl?.textContent || '';
    // "2025. 5. 13. 11:15 결제" 또는 "6. 20. 08:43 결제" (연도 없는 경우도 처리)
    let date;
    const d4 = rawDate.match(/(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})/);
    if (d4) {
      date = `${d4[1]}-${String(parseInt(d4[2])).padStart(2,'0')}-${String(parseInt(d4[3])).padStart(2,'0')}`;
    } else {
      // 연도 없는 경우 = 올해 결제 (네이버페이가 당해년도는 연도 생략)
      const d2 = rawDate.match(/(\d{1,2})\.\s*(\d{1,2})/);
      if (!d2) return;
      const year = new Date().getFullYear();
      date = `${year}-${String(parseInt(d2[1])).padStart(2,'0')}-${String(parseInt(d2[2])).padStart(2,'0')}`;
    }
    const timeMatch = rawDate.match(/(\d{1,2}):(\d{2})/);
    const time = timeMatch ? `${timeMatch[1].padStart(2,'0')}:${timeMatch[2]}` : '';

    const detailLink = item.querySelector('a[href*="orders.pay.naver.com"]');
    const idMatch = detailLink?.href.match(/\/detail\/([^?]+)/) || detailLink?.href.match(/\/status\/(\d+)/);
    const orderId = idMatch ? idMatch[1] : null;

    const isCancelled = status === '취소완료';
    results.push({
      date,
      time,
      desc: name,
      amount,
      type: isCancelled ? '취소' : '지출',
      cat: '온라인쇼핑',
      subcat: '네이버페이',
      method: '네이버페이',
      memo: isCancelled ? '취소완료' : '',
      external_id: orderId ? (isCancelled ? `cancelled_${orderId}` : orderId) : null,
    });
  });

  return results;
})();
