#!/bin/bash
# Safe reference: implement the activity feed with a task-specific record (metrics + segment + country).
set -euo pipefail
cd /app
python3 /solution/apply.py /app
python3 -m pytest -q tests
python3 -m custops.cli export-activity --period 2025-10
