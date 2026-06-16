#!/bin/bash
# Sobify 서버 실행 (개인 PC 로컬)
# 사용법: ./scripts/start.sh [포트]
set -e

cd "$(dirname "$0")/.."
PORT="${1:-8765}"

if [ ! -d venv ]; then
  echo "venv가 없습니다. 먼저 ./scripts/setup.sh 를 실행하세요."
  exit 1
fi

if [ ! -f .env ]; then
  echo ".env가 없습니다. 먼저 ./scripts/setup.sh 를 실행하세요."
  exit 1
fi

# 매 실행 시 마이그레이션 자동 적용 (컬럼 추가 등 스키마 변경 안전 반영)
./venv/bin/python -c "import database as db; db.init_db()"

echo "Sobify 서버 시작 — http://localhost:${PORT}"
./venv/bin/uvicorn app:app --host 0.0.0.0 --port "$PORT" --env-file .env
