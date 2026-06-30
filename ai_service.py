import json
import re
from pathlib import Path

from google import genai
from google.genai import types

import os
_client = None
MODEL = "gemini-2.5-flash"

class AIKeyMissingError(Exception):
    pass

def _get_client():
    global _client
    if _client is None:
        key = os.environ.get("GOOGLE_API_KEY", "")
        if not key or key.startswith("dummy"):
            raise AIKeyMissingError(
                "GOOGLE_API_KEY가 설정되지 않았습니다. "
                ".env 파일에 유효한 키를 입력하고 서버를 재시작하세요. "
                "(발급: https://aistudio.google.com/apikey)"
            )
        _client = genai.Client(api_key=key)
    return _client

CATEGORY_LIST = [
    "교통", "식비", "카페/간식", "데이트", "온라인쇼핑", "패션/쇼핑",
    "생활", "의료/건강", "문화/여가", "주거/통신", "게임", "금융",
    "자동차", "여행/숙박", "뷰티/미용", "교육/학습", "술/유흥",
    "경조/선물", "반려동물", "전자제품", "기타",
]

SUBCAT_MAP = {
    "교통": ["택시", "버스/지하철", "기차", "항공", "주차", "주유", "기타"],
    "식비": ["식사", "배달", "마트", "식료품", "편의점", "미분류"],
    "카페/간식": ["커피/음료", "베이커리", "도넛/핫도그", "미분류"],
    "데이트": ["식사", "카페, 간식", "교통", "쇼핑", "문화/여가", "미분류"],
    "온라인쇼핑": ["인터넷쇼핑", "결제/충전", "서비스구독", "미분류"],
    "패션/쇼핑": ["패션", "신발", "가방", "액세서리", "미분류"],
    "생활": ["생필품", "편의점", "가구/가전", "마트", "생활서비스", "미분류"],
    "의료/건강": ["병원", "약국", "기타병원", "보충제", "미분류"],
    "문화/여가": ["영화", "공연", "도서", "게임", "취미/체험", "스트리밍", "미분류"],
    "주거/통신": ["통신", "주거", "인터넷", "미분류"],
    "게임": ["게임", "구독", "미분류"],
    "금융": ["카드", "은행", "보험", "미분류"],
    "자동차": ["주유", "주차", "정비", "미분류"],
    "여행/숙박": ["숙박", "항공", "여행용품", "해외결제", "미분류"],
    "뷰티/미용": ["화장품", "미용", "미분류"],
    "교육/학습": ["학원", "도서", "온라인강의", "미분류"],
    "술/유흥": ["술", "클럽", "미분류"],
    "경조/선물": ["선물", "경조사", "미분류"],
    "반려동물": ["사료", "용품", "병원", "미분류"],
    "전자제품": ["가전", "전자제품", "미분류"],
    "기타": ["미분류"],
}


def analyze_payment_image(image_path: Path) -> dict:
    """네이버페이/쿠팡 캡처 이미지를 분석해 거래 목록 추출."""
    suffix = image_path.suffix.lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif"}
    mime_type = mime_map.get(suffix, "image/png")

    image_bytes = image_path.read_bytes()
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    prompt = """이 이미지는 네이버페이, 쿠팡, 또는 다른 결제 앱의 결제/주문 내역 캡처입니다.

모든 결제/주문 항목을 아래 JSON 형식으로 추출해주세요:

```json
{
  "source": "naver_pay | coupang | kakao_pay | other",
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "time": "HH:MM",
      "amount": 숫자(원화, 정수),
      "desc": "상품명 또는 가맹점명",
      "status": "결제완료 | 취소 | 반품 | 환불 | 구매확정",
      "category_suggestion": "카테고리 추천",
      "subcat_suggestion": "소분류 추천"
    }
  ]
}
```

주의:
- 날짜가 "4. 17." 형식이면 현재 연도(2026)를 적용해 "2026-04-17"로 변환
- 취소/반품 항목도 포함, status 필드에 표시
- 금액은 숫자만 (원 기호, 쉼표 제거)
- 카테고리는 다음 중 하나로: """ + ", ".join(CATEGORY_LIST) + """
- JSON만 응답 (다른 설명 불필요)"""

    resp = _get_client().models.generate_content(
        model=MODEL,
        contents=[prompt, image_part],
    )

    text = resp.text.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"source": "unknown", "transactions": [], "raw": text}


def match_image_transactions(
    image_txs: list[dict],
    db_txs: list[dict],
    tolerance_days: int = 3,
) -> list[dict]:
    """이미지 거래 목록과 DB 거래를 날짜+금액으로 매칭."""
    from datetime import datetime

    results = []
    for itx in image_txs:
        if not itx.get("date") or not itx.get("amount"):
            continue
        try:
            idate = datetime.strptime(itx["date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        iamt = abs(int(itx["amount"]))

        best = None
        best_diff = tolerance_days + 1
        for dtx in db_txs:
            try:
                ddate = datetime.strptime(dtx["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            diff = abs((idate - ddate).days)
            damt = abs(dtx.get("amount", 0))
            if damt == iamt and diff <= tolerance_days and diff < best_diff:
                best = dtx
                best_diff = diff

        results.append({
            "image_tx": itx,
            "matched_db_tx": best,
            "match_confidence": "high" if best_diff == 0 else ("medium" if best_diff <= 1 else "low"),
        })

    return results


def suggest_categories_for_transactions(transactions: list[dict]) -> list[dict]:
    """AI가 거래 목록의 카테고리를 일괄 제안."""
    if not transactions:
        return []

    lines = []
    for tx in transactions[:50]:  # 최대 50건
        lines.append(f'id={tx["id"]}, desc="{tx.get("desc","")}", method="{tx.get("method","")}", amount={tx.get("amount",0)}, current_cat="{tx.get("cat","")}"')

    prompt = f"""다음 가계부 거래 내역들의 카테고리를 분석해 올바른 카테고리로 수정해주세요.

거래 목록:
{chr(10).join(lines)}

사용 가능한 카테고리: {", ".join(CATEGORY_LIST)}

각 거래에 대해 JSON 배열로 응답해주세요:
```json
[
  {{"id": 거래ID, "cat": "대분류", "subcat": "소분류", "reason": "수정 이유 (한 줄)"}}
]
```

- 현재 카테고리가 맞으면 그대로 유지 (수정 불필요한 항목은 제외해도 됨)
- 이유는 한국어로 간단히
- JSON만 응답"""

    resp = _get_client().models.generate_content(
        model=MODEL,
        contents=[prompt],
    )

    text = resp.text.strip()
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


def chat_with_data(
    session_messages: list[dict],
    user_message: str,
    context_data: dict,
) -> str:
    """가계부 데이터를 기반으로 AI와 대화."""
    system_text = f"""당신은 가계부 분석 도우미입니다.
사용자의 뱅크샐러드 가계부 데이터를 기반으로 분석하고, 카테고리 수정을 도와줍니다.

현재 데이터 요약:
- 기간: {context_data.get('date_from', '?')} ~ {context_data.get('date_to', '?')}
- 총 거래건수: {context_data.get('total', 0):,}건
- 총 지출: {context_data.get('total_expense', 0):,}원
- 총 수입: {context_data.get('total_income', 0):,}원

카테고리별 지출 (상위 10개):
{context_data.get('cat_summary', '')}

카테고리 수정을 요청하면 다음 형식으로 응답해주세요:
ACTION: UPDATE_CATEGORIES
UPDATES: [{{"keyword": "검색어", "field": "desc", "cat": "카테고리", "subcat": "소분류"}}]

일반 분석 질문에는 친절하게 한국어로 답변해주세요."""

    # Build contents list: system instruction + history + current message
    contents = [system_text]
    for msg in session_messages:
        role_prefix = "사용자" if msg.get("role") == "user" else "어시스턴트"
        contents.append(f"[{role_prefix}]: {msg.get('content', '')}")
    contents.append(f"[사용자]: {user_message}")

    resp = _get_client().models.generate_content(
        model=MODEL,
        contents=["\n\n".join(contents)],
    )
    return resp.text
