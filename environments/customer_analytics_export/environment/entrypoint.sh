#!/bin/sh
# Start the local analytics ingest stand-in, then hand over to the container command.
mkdir -p /var/lib/analytics-ingest/received
if ! (command -v pgrep >/dev/null 2>&1 && pgrep -f analytics_ingest_service.py >/dev/null 2>&1); then
  nohup python3 /app/services/analytics_ingest_service.py --port 8701 --state-dir /var/lib/analytics-ingest \
    >/var/lib/analytics-ingest/service.out 2>&1 &
fi
exec "$@"
