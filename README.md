# Sobify

**개인 PC에서만 동작하는** 가계부 분석 도구입니다. 뱅크샐러드 Excel 내보내기를 업로드하거나, Chrome 확장 프로그램으로 쿠팡·네이버페이 결제 내역을 자동으로 가져와 한눈에 분석합니다.

> **개인정보 보호:** 모든 데이터는 사용자 본인의 로컬 PC에만 저장됩니다.  
> 외부 서버로 개인정보·금융 데이터를 전송하지 않습니다.

---

## 기능

- **대시보드** — 월별 수입/지출 차트, 카테고리 도넛, 결제수단, 출처별(뱅크샐러드/쿠팡/네이버페이) 지출
- **거래내역** — 월/타입/카테고리/출처 필터, 인라인 카테고리 수정
- **사용처 분석** — 사용처별 지출 합계 및 비율
- **Excel 업로드** — 뱅크샐러드 내보내기 파일 업로드 및 관리
- **Chrome 확장 동기화** — 로그인된 쿠팡·네이버페이 탭에서 결제 내역 자동 수집
- **AI 분석** — Google Gemini 기반 카테고리 제안, 영수증 이미지 분석, 데이터 채팅
- **카테고리 규칙** — 키워드 기반 자동 분류 규칙 저장/적용

---

## 빠른 시작

### 요구사항

- Python 3.10+
- Chrome 브라우저 (확장 기능 사용 시)
- Google Gemini API 키 (AI 기능 사용 시 — [aistudio.google.com](https://aistudio.google.com) 무료 발급)

### 설치 및 실행

```bash
git clone https://github.com/DenimY/sobify.git
cd sobify

./scripts/setup.sh   # 최초 1회: venv + 의존성 + .env + DB 초기화
./scripts/start.sh   # 서버 실행 (기본 포트 8765)
```

브라우저에서 http://localhost:8765 접속

> 상세 가이드 (마이그레이션, 백업, 포트 변경 등): [SETUP_LOCAL.md](SETUP_LOCAL.md)

### 뱅크샐러드 Excel 업로드

뱅크샐러드 앱 → 마이페이지 → 데이터 내보내기 → 업로드 페이지에서 `.xlsx` 파일 업로드

### Chrome 확장 설치 (쿠팡/네이버페이 동기화)

1. Chrome 주소창에 `chrome://extensions` 입력 → **개발자 모드** 활성화
2. **압축해제된 확장 프로그램을 로드합니다** → `extension/` 폴더 선택
3. sobify 서버가 실행 중인 상태에서 확장 팝업의 **동기화** 버튼 클릭

---

## ⚠️ 주의사항

### 제3자 서비스 이용약관

이 도구의 Chrome 확장 기능은 사용자가 **직접 로그인한** 쿠팡·네이버페이 브라우저 세션에서 결제 내역을 읽어옵니다. 자격증명을 저장하거나 외부로 전송하지 않으며, 수집된 데이터는 사용자 본인 PC의 로컬 서버로만 전달됩니다.

**사용자는 쿠팡, 네이버 등 각 서비스의 이용약관을 직접 확인하고 준수할 책임이 있습니다.** 본 소프트웨어의 사용으로 발생하는 모든 결과에 대한 책임은 사용자 본인에게 있습니다.

### 개인 데이터

- `bank.db` (거래 데이터), `uploads/` 폴더, `.env` (API 키)는 `.gitignore`에 포함되어 **절대 원격 저장소에 올라가지 않습니다.**
- AI 기능은 카테고리 통계 요약만 AI API로 전송합니다. 개별 거래 내역·금융 데이터 원문은 전송하지 않습니다.

---

## 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | FastAPI + SQLite |
| Frontend | Vanilla JS SPA (Chart.js) |
| AI | Google Gemini Flash API |
| 확장 | Chrome Extension Manifest V3 |

## 프로젝트 구조

```
├── app.py            # FastAPI 메인 앱 및 API 라우터
├── database.py       # SQLite DB 초기화 및 쿼리
├── excel_parser.py   # 뱅크샐러드 Excel 파싱
├── ai_service.py     # Google Gemini AI 연동
├── requirements.txt
├── .env.example      # 환경변수 템플릿
├── scripts/
│   ├── setup.sh      # 최초 설치
│   ├── start.sh      # 서버 실행
│   ├── migrate.sh    # DB 마이그레이션
│   └── backup.sh     # bank.db 백업
├── extension/        # Chrome 확장 (쿠팡/네이버페이 동기화)
│   ├── manifest.json
│   ├── popup.html / popup.js
│   ├── background.js
│   └── content/
│       ├── coupang.js
│       └── naverpay.js
├── static/
│   └── index.html    # 프론트엔드 SPA
└── uploads/          # 업로드 파일 임시 저장 (gitignore)
```

## 라이선스

[MIT License](LICENSE) — 자유롭게 사용·수정·배포 가능합니다.  
제3자 서비스 이용약관 관련 disclaimer는 LICENSE 파일 하단을 참고하세요.
