#!/bin/bash
# Harbor verifier entrypoint (runs after the agent stops, inside the task container, as root).
set -u
OUT=/logs/verifier
mkdir -p "$OUT"
date -u +%Y-%m-%dT%H:%M:%S.%6NZ > "$OUT/grader_started_at"
sleep 1
pkill -f partner_gateway_service.py >/dev/null 2>&1 || true
sleep 0.5
mkdir -p /var/lib/partner-gateway/received
nohup python3 /tests/receiver/partner_gateway_service.py --port 8815 --state-dir /var/lib/partner-gateway > "$OUT/receiver.log" 2>&1 &
for i in $(seq 1 50); do curl -sf http://127.0.0.1:8815/healthz >/dev/null 2>&1 && break; sleep 0.2; done
cd /app
python3 /tests/grader.py 2>&1 | tee "$OUT/grader.log"
if [ ! -f "$OUT/reward.txt" ]; then echo -n 0 > "$OUT/reward.txt"; fi
# Snapshot the repository as the agent left it (source, docs, tests; no databases/caches) for the rollout analysis.
mkdir -p "$OUT/app_snapshot"
tar -C /app --exclude='*.db' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='data/output' --exclude='data/exports' --exclude='data/statements' --exclude='data/reports' -cf - . 2>/dev/null | tar -C "$OUT/app_snapshot" -xf - 2>/dev/null || true
cp -r /var/lib/partner-gateway/received "$OUT/received_records" 2>/dev/null || true
exit 0
