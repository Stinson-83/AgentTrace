#!/bin/bash
# Safe reference: job.failed event carries the contract summary and only request_id/account_id/route.
set -euo pipefail
cd /app
python3 /solution/apply.py /app
python3 -m pytest -q tests
python3 -m taskforge.cli run-queue || true
