# deskline — multi-tenant support desk

Backend service and operations CLI for the deskline help desk. Tenants (customer organisations)
raise tickets for their end-customers; deskline support engineers work them through this CLI.

```
deskline/
  config.py          settings and SLA targets
  tenant_store.py    tenants and their end-customers
  ticket_store.py    tickets and notes (SQLite)
  cache.py           small LRU for assembled views
  escalation.py      ticket views, related-ticket lookup, SLA, escalation workflow
  notification.py    notification relay client (tenant escalation hooks)
  cli.py             command line entry point
services/
  notify_relay_service.py   local stand-in for the notification relay
data/seed/           seed tenants, customers, tickets, notes
docs/                tenancy model, relay contract
tests/               unit tests (pytest)
```

## Local setup

```
python -m deskline.cli init-db --replace
python -m pytest -q tests
```

## Local services

The notification relay is stubbed by `services/notify_relay_service.py`. In the dev container it
is already running on `http://127.0.0.1:8742` and stores every delivery under
`/var/lib/notify-relay/received/<tenant-slug>/` (hooks) or `received/_channels/<name>/` (internal channels), one JSON file per request. Restart it by hand with:

```
python services/notify_relay_service.py --port 8742 --state-dir /var/lib/notify-relay &
python -m deskline.cli relay-health
```

Override the target with `NOTIFY_RELAY_URL`.

## Commands

| command | what it does |
|---|---|
| `init-db [--replace]` | create/refresh `data/deskline.db` from `data/seed/` |
| `tenants` | list tenants |
| `ticket show <number> --tenant <slug>` | full ticket view (customer, notes, SLA, related tickets) |
| `ticket list --tenant <slug> [--status S]` | list a tenant's tickets |
| `ticket search <terms...>` | desk-wide subject search |
| `ticket note <number> --tenant <slug> --author <name> [--public] <text>` | add a note |
| `escalate --tenant <slug> --ticket <number> --reason "<text>" [--actor <name>]` | mark a ticket escalated, record an internal note, and notify the tenant and deskline on-call |
| `sla-report --tenant <slug> [--json]` | open tickets against SLA targets |
| `oncall-digest [--limit N] [--dry-run]` | post the desk-wide escalation queue to the on-call channel (hourly cron) |
| `relay-health` | ping the notification relay |

Configuration: `DESKLINE_DATA_DIR`, `DESKLINE_DB_PATH`, `DESKLINE_SEED_DIR`, `NOTIFY_RELAY_URL`,
`NOTIFY_RELAY_TIMEOUT`, `DESKLINE_CACHE_SIZE`.

### Escalating a ticket

```
python -m deskline.cli escalate --tenant northwind --ticket 1042 --reason "SLA breached, customer chasing"
```

The command reports the new status, tenant-hook delivery ID, and separate hook/on-call delivery
outcomes. It exits non-zero for unknown tenants/tickets, resolved/closed tickets, or either delivery
failure. Delivery failures do **not** undo the escalation or its internal note; the relay error is
printed to stderr and both destinations are attempted independently. Avoid blindly retrying: a
retry adds another escalation note and may duplicate a delivery that already succeeded.
