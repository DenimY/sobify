// 네이버페이 결제 내역 수집
// 대상: pay.naver.com/payments/list/pay (PC)
//       new-m.pay.naver.com/histories/ (모바일)
(function collectNaverpay() {
  window.collectNaverpay = collectNaverpay;

  const results = [];
  const isMobile = location.hostname.includes('new-m');

  if (isMobile) {
    collectMobile();
  } else {
    collectDesktop();
  }

  return results;

  function collectDesktop() {
    // PC: .payment_list_wrap 안에 .payment_item들
    const items = document.querySelectorAll(
      '.payment_item, [class*="payment-item"], [class*="paymentItem"], ' +
      '.pay_history_item, [class*="pay-history"]'
    );

    items.forEach(item => {
      const dateEl = item.querySelector(
        '[class*="date"], [class*="Date"], time'
      );
      const nameEl = item.querySelector(
        '[class*="product"], [class*="merchant"], [class*="store"], .merchant_name, .store_name'
      );
      const amountEl = item.querySelector(
        '[class*="amount"], [class*="price"], [class*="pay_amount"]'
      );
      const idEl = item.querySelector('[data-payment-id], [data-order-id]');

      const date = parseKoreanDate(dateEl?.textContent || dateEl?.getAttribute('datetime') || '');
      const name = nameEl?.textContent?.trim();
      const amount = parsePrice(amountEl?.textContent);
      const externalId = idEl?.dataset?.paymentId || idEl?.dataset?.orderId || null;

      if (date && name && amount > 0) {
        results.push(makeRow({ date, name, amount, externalId }));
      }
    });
  }

  function collectMobile() {
    // 모바일: .list_history 안에 .item_history들
    const items = document.querySelectorAll(
      '.item_history, [class*="history-item"], [class*="historyItem"], ' +
      '.list_payment > li, [class*="list-pay"] > li'
    );

    items.forEach(item => {
      const dateEl = item.querySelector('[class*="date"], time');
      const nameEl = item.querySelector(
        '[class*="store"], [class*="merchant"], [class*="name"], .tit_store'
      );
      const amountEl = item.querySelector('[class*="amount"], [class*="price"], .txt_price');
      const idEl = item.querySelector('[data-id], [data-payment]');

      const date = parseKoreanDate(dateEl?.textContent || '');
      const name = nameEl?.textContent?.trim();
      const amount = parsePrice(amountEl?.textContent);
      const externalId = idEl?.dataset?.id || idEl?.dataset?.payment || null;

      if (date && name && amount > 0) {
        results.push(makeRow({ date, name, amount, externalId }));
      }
    });
  }

  function makeRow({ date, name, amount, externalId }) {
    return {
      date,
      time: '',
      desc: name,
      amount,
      type: '지출',
      cat: '온라인쇼핑',
      subcat: '네이버페이',
      method: '네이버페이',
      memo: '',
      external_id: externalId,
    };
  }

  function parseKoreanDate(str) {
    const m =
      str.match(/(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})/) ||
      str.match(/(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일/) ||
      str.match(/(\d{2})[.\-](\d{1,2})[.\-](\d{1,2})/);
    if (!m) return null;
    const y = m[1].length === 2 ? '20' + m[1] : m[1];
    return `${y}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`;
  }

  function parsePrice(str) {
    if (!str) return 0;
    return parseInt(str.replace(/[^0-9]/g, '')) || 0;
  }
})();
