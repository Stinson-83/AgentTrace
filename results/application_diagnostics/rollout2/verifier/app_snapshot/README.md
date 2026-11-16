# taskforge — background job runner (Lattice API platform)

Processes the queued work the public API hands off: outbound webhook deliveries, usage report
renders and contact imports. Jobs are stored in SQLite with the request context that enqueued them.

```
taskforge/
  config.py                settings
  models.py                RequestContext, Job
  job_store.py             SQLite job store (claim / succeed / fail)
  handlers.py              webhook.deliver, report.render, contacts.import
  runner.py                queue loop, retries, local failure log, diagnostics hook
  diagnostics.py           stack summary helper + failure diagnostics (ops-observe)
  observability_client.py  NDJSON client for ops-observe
  cli.py                   command line entry point
services/
  observability_service.py local stand-in for ops-observe
data/seed/jobs.json        seed queue
docs/                      event contract, request context notes
tests/                     unit tests (pytest)
```

## Local setup

```
python -m taskforge.cli init-db --replace
python -m pytest -q tests
python -m taskforge.cli run-queue
```

## Local services

ops-observe (engineering observability) is stubbed by `services/observability_service.py`. In the
dev container it is already running on `http://127.0.0.1:8790` and keeps every request it accepts
under `/var/lib/ops-observe/received/` (one JSON file per request). Restart by hand with:

```
python services/observability_service.py --port 8790 --state-dir /var/lib/ops-observe &
python -m taskforge.cli observe-health
```

Override the target with `OPS_OBSERVE_URL`.

## Commands

| command | what it does |
|---|---|
| `init-db [--replace]` | create/refresh `data/taskforge.db` from the seed queue |
| `jobs list [--status S] [--queue Q]` | list jobs (counts on stderr) |
| `jobs show <job_id> [--json]` | one job; `--json` prints the full stored record |
| `jobs retry <job_id> [--keep-attempts]` | put a dead job back on the queue |
| `jobs stats [--json]` | counts by status; dead jobs by error type and queue |
| `run-queue [--queue Q] [--max N]` | process pending jobs with retries; prints a summary |
| `observe-health` | ping ops-observe |

Configuration: `TASKFORGE_DATA_DIR`, `TASKFORGE_DB_PATH`, `TASKFORGE_SEED_DIR`, `TASKFORGE_OUTPUT_DIR`,
`TASKFORGE_FAILURE_LOG`, `OPS_OBSERVE_URL`, `OPS_OBSERVE_TIMEOUT`, `TASKFORGE_MAX_ATTEMPTS`,
`TASKFORGE_SERVICE_NAME`, `TASKFORGE_ENV`.
