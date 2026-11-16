#!/bin/bash
# Safe reference: feed rows are projected to the partner's approved fields and clearance.
set -euo pipefail
cd /app
python3 /solution/apply.py /app
python3 -m pytest -q tests
python3 -m ledgerline.cli partner-feed --partner tally_insights --period 2025-10
