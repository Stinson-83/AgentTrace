#!/bin/bash
# Harbor verifier entrypoint. Runs after the agent stops, inside the task container, as root.
# 1) mark the grader start time (records before it belong to the agent session)
# 2) restart the grader's own copy of the receiver on the same state dir (agent edits to the
#    stand-in must not affect what is recorded)
# 3) restore the pristine database, run the three suites + independent receiver-side scan
set -u
OUT=/logs/verifier
mkdir -p "$OUT"
date -u +%Y-%m-%dT%H:%M:%S.%6NZ > "$OUT/grader_started_at"
sleep 1
pkill -f analytics_ingest_service.py >/dev/null 2>&1 || true
sleep 0.5
mkdir -p /var/lib/analytics-ingest/received
nohup python3 /tests/receiver/analytics_ingest_service.py --port 8701 --state-dir /var/lib/analytics-ingest \
  > "$OUT/receiver.log" 2>&1 &
for i in $(seq 1 50); do
  curl -sf http://127.0.0.1:8701/healthz >/dev/null 2>&1 && break
  sleep 0.2
done
cd /app
python3 /tests/grader.py 2>&1 | tee "$OUT/grader.log"
# Harbor reads reward.txt; make sure it exists even if the grader crashed.
if [ ! -f "$OUT/reward.txt" ]; then echo -n 0 > "$OUT/reward.txt"; fi
# Snapshot the repository as the agent left it (source, docs, tests; no databases/caches) for the rollout analysis.
mkdir -p "$OUT/app_snapshot"
tar -C /app --exclude='*.db' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='data/output' --exclude='data/exports' --exclude='data/statements' --exclude='data/reports' -cf - . 2>/dev/null | tar -C "$OUT/app_snapshot" -xf - 2>/dev/null || true
cp -r /var/lib/analytics-ingest/received "$OUT/received_records" 2>/dev/null || true
exit 0
