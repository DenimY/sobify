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
    const dateMatch = (timeEl?.textContent || '').match(/(\d{1,2})\.\s*(\d{1,2})\./);
    if (!dateMatch) return;
    const date = toIsoDate(dateMatch[2], dateMatch[1]); // 페이지 형식: DD.MM. → month=group2, day=group1

    const detailLink = item.querySelector('a[href*="orders.pay.naver.com/order/status/"]');
    const idMatch = detailLink?.href.match(/order\/status\/(\d+)/);
    const orderId = idMatch ? idMatch[1] : null;

    const isCancelled = status === '취소완료';
    results.push({
      date,
      time: '',
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

  function toIsoDate(month, day) {
    const m = parseInt(month, 10);
    const now = new Date();
    let year = now.getFullYear();
    const curMonth = now.getMonth() + 1;
    if (m > curMonth + 2) year -= 1;
    return `${year}-${String(m).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }
})();
