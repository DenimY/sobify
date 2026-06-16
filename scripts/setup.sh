#!/bin/bash
# Sobify 최초 설치 스크립트 (개인 PC 로컬 실행용)
# 사용법: ./scripts/setup.sh
set -e

cd "$(dirname "$0")/.."

PYTHON_BIN="python3.12"
if ! command -v "$PYTHON_BIN" &>/dev/null; then
  if [ -x /opt/homebrew/bin/python3.12 ]; then
    PYTHON_BIN=/opt/homebrew/bin/python3.12
  else
    echo "python3.12를 찾을 수 없습니다. 'brew install python@3.12' 로 설치하세요."
    exit 1
  fi
fi

echo "[1/4] 가상환경 생성 (venv/)"
if [ ! -d venv ]; then
  "$PYTHON_BIN" -m venv venv
else
  echo "  이미 존재함, 건너뜀"
fi

echo "[2/4] 의존성 설치"
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

echo "[3/4] .env 설정"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  .env 생성됨 — GOOGLE_API_KEY 값을 직접 입력하세요 (AI 분석 기능 사용 시 필요)"
  echo "  https://aistudio.google.com 에서 무료 발급 가능"
else
  echo "  이미 존재함, 건너뜀"
fi

echo "[4/4] DB 초기화 / 마이그레이션"
./venv/bin/python -c "import database as db; db.init_db(); print('  bank.db 준비 완료')"

echo ""
echo "설치 완료. 서버 실행: ./scripts/start.sh"
