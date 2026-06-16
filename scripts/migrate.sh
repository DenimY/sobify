#!/bin/bash
# bank.db 스키마 마이그레이션만 단독 실행 (서버 재시작 없이)
# 사용법: ./scripts/migrate.sh
set -e

cd "$(dirname "$0")/.."

if [ ! -d venv ]; then
  echo "venv가 없습니다. 먼저 ./scripts/setup.sh 를 실행하세요."
  exit 1
fi

echo "bank.db 마이그레이션 적용 중..."
./venv/bin/python -c "import database as db; db.init_db(); print('완료')"
