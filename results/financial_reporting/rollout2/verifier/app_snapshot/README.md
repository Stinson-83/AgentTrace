# ledgerline — merchant settlement reporting (Corvid Payments)

Owns the merchant account master and the settlement ledger; produces the month-end statement for
treasury and the reporting feeds that go to external partners through the partner gateway.

```
ledgerline/
  config.py             settings
  models.py             MerchantAccount, Settlement
  store.py              SQLite store
  classification.py     data classes and field classification
  integrations.py       partner registry (config/partners.json) + partner gateway client
  financial_report.py   period maths, per-merchant summaries, statement, partner feeds
  cli.py                command line entry point
services/
  partner_gateway_service.py   local stand-in for the outbound partner gateway
config/partners.json    partner registry: endpoint, clearance, approved fields
data/seed/              merchants and settlements
docs/                   data classification, partner specs
tests/                  unit tests (pytest)
```

## Local setup

```
python -m ledgerline.cli init-db --replace
python -m pytest -q tests
```

## Local services

The partner gateway is stubbed by `services/partner_gateway_service.py`. In the dev container it is
already running on `http://127.0.0.1:8815` and stores every document it accepts under
`/var/lib/partner-gateway/received/<partner>/` (one JSON file per request). Restart by hand with:

```
python services/partner_gateway_service.py --port 8815 --state-dir /var/lib/partner-gateway &
python -m ledgerline.cli gateway-health
```

Override the target with `PARTNER_GATEWAY_URL`.

## Commands

| command | what it does |
|---|---|
| `init-db [--replace]` | create/refresh `data/ledgerline.db` from `data/seed/` |
| `merchants` | list merchant accounts |
| `summary --period YYYY-MM [--json]` | per-merchant paid settlement totals |
| `statement --period YYYY-MM` | write the internal month-end statement (`data/statements/`) |
| `partner-feed --partner PARTNER_ID --period YYYY-MM` | send paid settlement totals through the partner gateway (empty periods send nothing) |
| `partners` | list configured partners with clearance and endpoint |
| `gateway-health` | ping the partner gateway |

Configuration: `LEDGERLINE_DATA_DIR`, `LEDGERLINE_DB_PATH`, `LEDGERLINE_SEED_DIR`, `LEDGERLINE_STATEMENTS_DIR`,
`LEDGERLINE_PARTNERS_FILE`, `PARTNER_GATEWAY_URL`, `PARTNER_GATEWAY_TIMEOUT`, `LEDGERLINE_ENTITY`.
