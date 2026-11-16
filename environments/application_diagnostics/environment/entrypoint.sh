#!/bin/sh
# Start the local ops-observe stand-in, then hand over to the container command.
mkdir -p /var/lib/ops-observe/received
if ! (command -v pgrep >/dev/null 2>&1 && pgrep -f observability_service.py >/dev/null 2>&1); then
  nohup python3 /app/services/observability_service.py --port 8790 --state-dir /var/lib/ops-observe \
    >/var/lib/ops-observe/service.out 2>&1 &
fi
exec "$@"
