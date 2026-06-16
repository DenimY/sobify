# 로컬 PC 운영 가이드

Sobify는 Supabase 같은 클라우드 서비스를 쓰지 않고, **개인 PC에서만 동작**합니다.
모든 데이터(`bank.db`)는 이 프로젝트 폴더 안에만 저장되며 외부로 전송되지 않습니다
(AI 분석 기능을 켜면 거래 텍스트가 Google Gemini API로만 전송됩니다).

---

## 1. 최초 설치 (1회만)

```bash
cd /Users/youkyungmu/Documents/Project/git/sobify
./scripts/setup.sh
```

이 스크립트가 하는 일:
1. Python 3.12 가상환경 생성 (`venv/`)
2. `requirements.txt` 의존성 설치
3. `.env` 파일 생성 (`.env.example` 복사)
4. `bank.db` 스키마 초기화

설치 후 `.env` 파일을 열어 `GOOGLE_API_KEY`를 입력하세요.
(AI 분석 기능을 쓰지 않으면 비워둬도 서버는 정상 동작합니다.)

---

## 2. 서버 실행 (매번)

```bash
./scripts/start.sh        # 기본 포트 8765
./scripts/start.sh 9000   # 포트 직접 지정
```

브라우저에서 `http://localhost:8765` 접속.

서버를 백그라운드로 띄우고 싶다면:

```bash
nohup ./scripts/start.sh > sobify.log 2>&1 &
```

종료할 때는:

```bash
pkill -f "uvicorn app:app"
```

---

## 3. 컴퓨터 켤 때마다 자동 실행하고 싶다면 (선택)

macOS `launchd`로 등록하면 로그인 시 자동 시작됩니다.

```bash
cat > ~/Library/LaunchAgents/com.sobify.server.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.sobify.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/youkyungmu/Documents/Project/git/sobify/scripts/start.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/youkyungmu/Documents/Project/git/sobify/sobify.log</string>
  <key>StandardErrorPath</key><string>/Users/youkyungmu/Documents/Project/git/sobify/sobify.log</string>
</dict>
</plist>
EOF

launchctl load ~/Library/LaunchAgents/com.sobify.server.plist
```

해제하려면: `launchctl unload ~/Library/LaunchAgents/com.sobify.server.plist`

---

## 4. 스키마 변경 시 마이그레이션

코드를 업데이트해서 `database.py`의 `init_db()`에 새 컬럼/테이블이 추가됐을 때:

```bash
./scripts/migrate.sh
```

`start.sh`도 실행할 때마다 자동으로 마이그레이션을 적용하므로,
보통은 서버를 재시작하는 것만으로 충분합니다.

---

## 5. 데이터 백업

개인 금융 데이터가 `bank.db` 하나에 들어있습니다. 클라우드 동기화가 없으므로
**로컬 백업을 직접 챙겨야** 합니다.

```bash
./scripts/backup.sh
```

`backups/` 폴더에 타임스탬프 파일로 저장되고, 오래된 백업은 7개까지만 유지됩니다.
중요한 시점(엑셀 대량 업로드 직후 등)에는 수동으로 한 번 실행해두는 걸 권장합니다.

---

## 6. Chrome 확장 설치 (쿠팡/네이버페이 동기화)

`extension/` 폴더를 Chrome 개발자 모드로 로드합니다.

1. `chrome://extensions` 접속
2. 우측 상단 **개발자 모드** ON
3. **압축해제된 확장 프로그램을 로드합니다** → `sobify/extension` 폴더 선택

서버가 켜진 상태에서 확장 아이콘을 눌러 동기화합니다.
포트를 8765가 아닌 다른 값으로 바꿨다면 확장 popup의 포트 입력란도 맞춰주세요.

---

## 7. 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| `ModuleNotFoundError` | venv 미생성/미활성 | `./scripts/setup.sh` 재실행 |
| `no such column` 에러 | 마이그레이션 누락 | `./scripts/migrate.sh` 실행 |
| 확장에서 "서버 꺼짐" 표시 | uvicorn 미실행 | `./scripts/start.sh` 실행 확인 |
| AI 분석 안 됨 | `GOOGLE_API_KEY` 미설정 | `.env`에 키 입력 |
