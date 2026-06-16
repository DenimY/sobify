#!/bin/bash
# bank.db 백업 (개인 금융 데이터 — 클라우드 미사용이므로 로컬 백업 권장)
# 사용법: ./scripts/backup.sh
set -e

cd "$(dirname "$0")/.."
mkdir -p backups
TS=$(date +%Y%m%d_%H%M%S)
cp bank.db "backups/bank_${TS}.db"
echo "백업됨: backups/bank_${TS}.db"

# 7개 초과 시 오래된 백업 정리
cd backups
ls -t bank_*.db 2>/dev/null | tail -n +8 | xargs -r rm --
cd ..
