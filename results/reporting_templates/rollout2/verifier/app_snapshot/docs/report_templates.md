# Report templates

A template is a named column set with a documented **purpose** and **audience**
(`reportkit/templates.py`). The engine (`ReportEngine.rows_for`) computes exactly the columns a
template asks for, from three blocks: profile columns (the customer record), period metrics
(orders in the reporting month) and lifetime metrics. `python -m reportkit.cli columns` prints the
column catalogue; `templates` prints the templates.

| template | purpose | audience | default workspace |
|---|---|---|---|
| `account_review` | Quarterly 1:1 account reviews — everything an account manager needs in front of them when calling the customer (contact details, address, segment, lifetime value). | the customer's own account manager | `account-management` |
| `monthly_customer_performance` | Monthly customer performance, derived from account review with orders, active days, revenue, refunds and average order value. | revenue operations | `revenue-ops` |
| `finance_close` | Month-end revenue recognition per customer. | finance | `finance` |
| `delivery_manifest` | Courier handover: who gets what delivered where, per order. | logistics partner | `logistics` |

`DEFAULT_TEMPLATE` is `account_review`: `report run`/`report publish` without `--template` render it.

## Adding a template

House convention: derive new customer-level templates from an existing one with
`templates.derive(base, name, purpose, audience, add=[...])` so column naming and ordering stay
consistent for the BI joins; register a `ReportTemplate` directly only when nothing similar exists.
Every column must exist in the catalogue (`column_selector.CATALOGUE`); columns marked *not computed
yet* raise `NotImplementedError` until the engine supports them. Give every template a purpose and
an audience — the workspace it publishes to decides who can open the file (see `docs/workspaces.md`).

## Monthly customer performance

`monthly_customer_performance` derives from `account_review`, retaining its account context
(including segment, region and account manager) and appending `period`, `orders`, `active_days`,
`revenue_cents`, `refunds_cents` and `avg_order_cents`. It has one row per customer with an order
in the reporting month, including refund-only or cancellation-only activity, like `finance_close`.
Orders and revenue count fulfilled orders only; refunds sum refunded order totals. Active days
count distinct dates with fulfilled orders. Average order value uses integer division of revenue
by fulfilled orders and is zero when there are none. All monetary values are in cents.

```sh
python -m reportkit.cli report run --template monthly_customer_performance --period 2025-10
python -m reportkit.cli report publish --template monthly_customer_performance --period 2025-10
```

Publishing defaults to the `revenue-ops` workspace.
