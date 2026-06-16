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

> Supabase 등 클라우드 서비스를 쓰지 않고 **개인 PC에서만** 동작합니다.
> 설치/실행/백업/마이그레이션 전체 가이드는 [SETUP_LOCAL.md](SETUP_LOCAL.md) 참고.

```bash
./scripts/setup.sh   # 최초 1회: venv + 의존성 + .env + DB 초기화
./scripts/start.sh    # 서버 실행 (기본 포트 8765)
```

브라우저에서 http://localhost:8765 접속

### Excel 업로드

뱅크샐러드 앱 → 마이페이지 → 데이터 내보내기 → Excel 파일을 업로드 페이지에서 업로드

## 프로젝트 구조

```
├── app.py            # FastAPI 메인 앱 및 API 라우터
├── database.py       # SQLite DB 초기화 및 쿼리
├── excel_parser.py   # 뱅크샐러드 Excel 파싱
├── ai_service.py     # Claude AI 연동 (이미지 분석, 카테고리 제안, 채팅)
├── requirements.txt
├── .env.example      # 환경변수 템플릿
├── scripts/
│   ├── setup.sh      # 최초 설치 (venv, 의존성, .env, DB 초기화)
│   ├── start.sh      # 서버 실행 (마이그레이션 자동 적용)
│   ├── migrate.sh    # DB 마이그레이션만 단독 실행
│   └── backup.sh      # bank.db 백업
├── extension/         # Chrome 확장 (쿠팡/네이버페이 동기화)
├── static/
│   └── index.html    # 프론트엔드 SPA
└── uploads/          # 업로드 파일 임시 저장 (gitignore)
```

## 주의사항

- `bank.db` (거래 데이터)와 `uploads/` 폴더는 개인정보 보호를 위해 `.gitignore`에 포함되어 있습니다.
- AI 기능 사용을 위해 `GOOGLE_API_KEY` 환경변수가 필요합니다.
