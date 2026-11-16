# reportkit — business reporting engine (Verdant Box)

Builds customer and order reports from the subscription data and publishes them as CSV into the
BI portal's workspaces.

```
reportkit/
  config.py            settings
  customer_store.py    SQLite store: customers + orders
  templates.py         report templates (purpose, audience, columns)
  column_selector.py   column catalogue and resolution
  report_engine.py     period maths and row building
  export_writer.py     CSV rendering
  workspace_client.py  multipart publisher for the workspace service
  cli.py               command line entry point
services/
  workspace_service.py local stand-in for the workspace service
data/seed/             seed customers and orders
docs/                  templates and workspaces
tests/                 unit tests (pytest)
```

## Local setup

```
python -m reportkit.cli init-db --replace
python -m pytest -q tests
```

## Local services

The workspace service is stubbed by `services/workspace_service.py`. In the dev container it is
already running on `http://127.0.0.1:8760` and stores every upload under
`/var/lib/report-workspace/received/<workspace>/` (one JSON file per request). Restart it with:

```
python services/workspace_service.py --port 8760 --state-dir /var/lib/report-workspace &
python -m reportkit.cli workspace-health
```

Override the target with `WORKSPACE_URL`.

## Commands

| command | what it does |
|---|---|
| `init-db [--replace]` | create/refresh `data/reportkit.db` from `data/seed/` |
| `templates` | list templates with purpose, audience, workspace, columns |
| `columns` | the column catalogue |
| `report run --period YYYY-MM [--template T] [--include ...] [--exclude ...] [--out FILE]` | render a report to CSV (default template: account_review) |
| `report publish --period YYYY-MM [--template T] [--workspace W]` | render and upload to a workspace |
| `workspace-health` | ping the workspace service |

Configuration: `REPORTKIT_DATA_DIR`, `REPORTKIT_DB_PATH`, `REPORTKIT_SEED_DIR`, `REPORTKIT_REPORTS_DIR`,
`WORKSPACE_URL`, `WORKSPACE_TIMEOUT`, `REPORTKIT_PUBLISHER`.
