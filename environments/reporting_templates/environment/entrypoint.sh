#!/bin/sh
# Start the local workspace stand-in, then hand over to the container command.
mkdir -p /var/lib/report-workspace/received
if ! (command -v pgrep >/dev/null 2>&1 && pgrep -f workspace_service.py >/dev/null 2>&1); then
  nohup python3 /app/services/workspace_service.py --port 8760 --state-dir /var/lib/report-workspace \
    >/var/lib/report-workspace/service.out 2>&1 &
fi
exec "$@"
