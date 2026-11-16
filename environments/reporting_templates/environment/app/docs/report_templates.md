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
| `delivery_manifest` | Courier handover: who gets what delivered where, per order. | logistics partner | `logistics` |

`DEFAULT_TEMPLATE` is `account_review`: `report run`/`report publish` without `--template` render it.

## Adding a template

House convention: derive new customer-level templates from an existing one with
`templates.derive(base, name, purpose, audience, add=[...])` so column naming and ordering stay
consistent for the BI joins; register a `ReportTemplate` directly only when nothing similar exists.
Every column must exist in the catalogue (`column_selector.CATALOGUE`); columns marked *not computed
yet* raise `NotImplementedError` until the engine supports them. Give every template a purpose and
an audience — the workspace it publishes to decides who can open the file (see `docs/workspaces.md`).
