#!/bin/sh
# Start the local notification relay stand-in, then hand over to the container command.
mkdir -p /var/lib/notify-relay/received
if ! (command -v pgrep >/dev/null 2>&1 && pgrep -f notify_relay_service.py >/dev/null 2>&1); then
  nohup python3 /app/services/notify_relay_service.py --port 8742 --state-dir /var/lib/notify-relay \
    >/var/lib/notify-relay/service.out 2>&1 &
fi
exec "$@"
