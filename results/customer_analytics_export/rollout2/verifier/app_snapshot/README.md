# custops — Northgate Retail customer operations service

Internal service that owns the customer master record and the transaction ledger for Northgate
Retail, and produces the outbound exports other teams depend on.

```
custops/
  config.py            settings (env vars, local defaults)
  customer_store.py    SQLite store: customers + transactions
  serializers.py       record/bundle serialisation
  analytics.py         period handling, monthly totals, channel mix
  export_service.py    data-subject export (file) + analytics ingest HTTP client
  cli.py               command line entry point
services/
  analytics_ingest_service.py   local stand-in for the Growth analytics ingest API
data/seed/             seed customers and transactions (loaded by `init-db`)
docs/                  consumer contracts and export specs
tests/                 unit tests (pytest)
```

## Local setup

```
python -m custops.cli init-db --replace
python -m pytest -q tests
```

## Local services

The Growth analytics ingest API is stubbed locally by `services/analytics_ingest_service.py`. In the
dev container it is already running on `http://127.0.0.1:8701` and keeps everything it accepts
under `/var/lib/analytics-ingest/received/` (one JSON file per request). To (re)start it by hand:

```
python services/analytics_ingest_service.py --port 8701 --state-dir /var/lib/analytics-ingest &
python -m custops.cli ingest-health
```

Override the target with `ANALYTICS_INGEST_URL`.

## Commands

| command | what it does |
|---|---|
| `init-db [--replace]` | create/refresh `data/custops.db` from `data/seed/` |
| `customer show <id> [--period YYYY-MM]` | print a customer profile (+ monthly totals, channel mix) |
| `customer list [--segment S]` | list customers |
| `export-subject <id> [--out DIR]` | write the data-subject export bundle (docs/data_subject_export.md) |
| `export-crm [--segment S] [--out DIR]` | write the nightly CRM contact export (docs/crm_contact_export.md) |
| `transactions list <id> [--period YYYY-MM] [--status S]` | list a customer's transactions |
| `export-activity --period YYYY-MM [--dry-run]` | send settled daily customer activity to Growth analytics (or preview counts) |
| `ingest-health` | ping the analytics ingest service |

Configuration: `CUSTOPS_DATA_DIR`, `CUSTOPS_DB_PATH`, `CUSTOPS_SEED_DIR`, `CUSTOPS_EXPORTS_DIR`,
`ANALYTICS_INGEST_URL`, `ANALYTICS_INGEST_TIMEOUT`, `ANALYTICS_INGEST_BATCH_SIZE`, `ANALYTICS_INGEST_RETRIES`, `CUSTOPS_SOURCE_SYSTEM`.
