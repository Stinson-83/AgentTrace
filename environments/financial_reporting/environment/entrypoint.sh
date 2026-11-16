#!/bin/sh
# Start the local partner gateway stand-in, then hand over to the container command.
mkdir -p /var/lib/partner-gateway/received
if ! (command -v pgrep >/dev/null 2>&1 && pgrep -f partner_gateway_service.py >/dev/null 2>&1); then
  nohup python3 /app/services/partner_gateway_service.py --port 8815 --state-dir /var/lib/partner-gateway \
    >/var/lib/partner-gateway/service.out 2>&1 &
fi
exec "$@"
