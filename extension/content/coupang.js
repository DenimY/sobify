// 쿠팡 주문 내역 수집 — www.coupang.com/my/orders
(function collectCoupang() {
  window.collectCoupang = collectCoupang;

  const results = [];

  // 주문 카드 선택 — 쿠팡 DOM 구조 기준
  const orderCards = document.querySelectorAll(
    '.order-history-unit, .order-items, [class*="order-unit"], [class*="orderUnit"]'
  );

  orderCards.forEach(card => {
    // 주문 번호 (중복 방지용)
    const orderNoEl = card.querySelector(
      '[class*="order-number"], [class*="orderNumber"], .order-num'
    );
    const externalId = orderNoEl?.textContent?.replace(/[^0-9]/g, '') || null;

    // 주문 날짜
    const dateEl = card.querySelector(
      '[class*="order-date"], [class*="orderDate"], .date'
    );
    const rawDate = dateEl?.textContent?.trim() || '';
    const date = parseKoreanDate(rawDate);
    if (!date) return;

    // 상품 항목들 (한 주문에 여러 상품 가능)
    const itemEls = card.querySelectorAll(
      '[class*="product-item"], [class*="productItem"], [class*="item-product"], li.product'
    );

    if (itemEls.length === 0) {
      // 단일 상품 카드인 경우
      const nameEl = card.querySelector(
        '[class*="product-name"], [class*="productName"], .name, .goods-name'
      );
      const priceEl = card.querySelector(
        '[class*="total-price"], [class*="totalPrice"], [class*="pay-price"], .price strong'
      );
      const name = nameEl?.textContent?.trim();
      const amount = parsePrice(priceEl?.textContent);
      if (name && amount > 0) {
        results.push(makeRow({ date, name, amount, externalId }));
      }
      return;
    }

    itemEls.forEach((item, idx) => {
      const nameEl = item.querySelector(
        '[class*="name"], [class*="title"], a[class*="product"]'
      );
      const priceEl = item.querySelector(
        '[class*="price"], [class*="amount"]'
      );
      const name = nameEl?.textContent?.trim();
      const amount = parsePrice(priceEl?.textContent);
      if (name && amount > 0) {
        results.push(makeRow({
          date,
          name,
          amount,
          externalId: externalId ? `${externalId}_${idx}` : null,
        }));
      }
    });
  });

  return results;

  function makeRow({ date, name, amount, externalId }) {
    return {
      date,
      time: '',
      desc: name,
      amount,
      type: '지출',
      cat: '온라인쇼핑',
      subcat: '쿠팡',
      method: '쿠팡',
      memo: '',
      external_id: externalId,
    };
  }

  function parseKoreanDate(str) {
    // "2025.06.15", "2025-06-15", "25.06.15", "2025년 6월 15일" 등 처리
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
