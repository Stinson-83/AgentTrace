# Report templates

A template is a named column set with a documented **purpose** and **audience**
(`reportkit/templates.py`). The engine (`ReportEngine.rows_for`) computes exactly the columns a
template asks for, from three blocks: profile columns (the customer record), period metrics
(orders in the reporting month) and lifetime metrics. `python -m reportkit.cli columns` prints the
column catalogue; `templates` prints the templates.

| template | purpose | audience | default workspace |
|---|---|---|---|
| `account_review` | Quarterly 1:1 account reviews — everything an account manager needs in front of them when calling the customer (contact details, address, segment, lifetime value). | the customer's own account manager | `account-management` |
| `finance_close` | Month-end revenue recognition per customer. | finance | `finance` |
| `monthly_customer_performance` | Monthly customer activity, revenue, refunds and average order value. | revenue operations and the commercial organisation | `revenue-ops` |
| `delivery_manifest` | Courier handover: who gets what delivered where, per order. | logistics partner | `logistics` |

`DEFAULT_TEMPLATE` is `account_review`: `report run`/`report publish` without `--template` render it.

## Adding a template

Register a `ReportTemplate` in `TEMPLATES`, or derive one from an existing template with
`templates.derive(base, name, purpose, audience, add=[...])` to keep column naming consistent.
Every column must exist in the catalogue (`column_selector.CATALOGUE`); columns marked *not computed
yet* raise `NotImplementedError` until the engine supports them. Give every template a purpose and
an audience — the workspace it publishes to decides who can open the file (see `docs/workspaces.md`).

## Monthly customer performance

`monthly_customer_performance` contains `customer_id`, `segment`, `region`, `account_manager`,
`period`, `orders`, `active_days`, `revenue_cents`, `refunds_cents` and `avg_order_cents`.
It includes one row per customer with orders in the month, following the same activity rule as
`finance_close` (including customers with only refunded or cancelled orders).
`orders` and `revenue_cents` count only fulfilled orders; `active_days` counts their distinct order
dates. `refunds_cents` sums refunded order totals. `avg_order_cents` is fulfilled revenue divided
by fulfilled orders using integer division, or zero with no fulfilled orders. Monetary values are
in cents. Contact details and lifetime metrics are not included in this broadly shared report.

```sh
python -m reportkit.cli report run --template monthly_customer_performance --period 2025-10
python -m reportkit.cli report publish --template monthly_customer_performance --period 2025-10
```

Publishing defaults to the `revenue-ops` workspace.
