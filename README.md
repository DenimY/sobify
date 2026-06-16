# Sobify

뱅크샐러드 Excel 데이터를 분석하는 AI 기반 가계부 앱입니다.

## 기능

- **대시보드** — 월별 수입/지출 차트, 카테고리 도넛, 결제수단, 순지출 추이
- **거래내역** — 월/타입/카테고리/검색 필터, 인라인 카테고리 수정
- **사용처 분석** — 사용처별 지출 합계 및 비율
- **Excel 업로드** — 뱅크샐러드 내보내기 파일 업로드 및 관리
- **AI 분석**
  - 네이버페이/쿠팡 결제 캡처 이미지 → 거래 자동 추출 및 카테고리 제안
  - AI 채팅으로 데이터 분석 및 카테고리 일괄 수정
  - 온라인쇼핑 항목 AI 재분류
- **카테고리 규칙** — 키워드 기반 자동 분류 규칙 저장/적용

## 기술 스택

- **Backend** FastAPI + SQLite
- **Frontend** Vanilla JS SPA (Chart.js)
- **AI** Google Gemini 3 Flash API

## 시작하기

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일에 GOOGLE_API_KEY 입력
```

### 3. 서버 실행

```bash
uvicorn app:app --host 0.0.0.0 --port 8765 --reload
```

브라우저에서 http://localhost:8765 접속

### 4. Excel 업로드

뱅크샐러드 앱 → 마이페이지 → 데이터 내보내기 → Excel 파일을 업로드 페이지에서 업로드

## 프로젝트 구조

```
├── app.py            # FastAPI 메인 앱 및 API 라우터
├── database.py       # SQLite DB 초기화 및 쿼리
├── excel_parser.py   # 뱅크샐러드 Excel 파싱
├── ai_service.py     # Claude AI 연동 (이미지 분석, 카테고리 제안, 채팅)
├── requirements.txt
├── .env.example      # 환경변수 템플릿
├── static/
│   └── index.html    # 프론트엔드 SPA
└── uploads/          # 업로드 파일 임시 저장 (gitignore)
```

## 주의사항

- `bank.db` (거래 데이터)와 `uploads/` 폴더는 개인정보 보호를 위해 `.gitignore`에 포함되어 있습니다.
- AI 기능 사용을 위해 `GOOGLE_API_KEY` 환경변수가 필요합니다.
