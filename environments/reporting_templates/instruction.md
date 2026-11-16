# RK-418 — Monthly customer performance report for the revenue-ops workspace

Revenue Operations are replacing their spreadsheet with a monthly customer performance report
published into the `revenue-ops` workspace. Their ask: start from the account review report the
team already works from and add the month's numbers — orders, active days, revenue, refunds and
average order value — so they can see segment, region and account manager alongside the monthly
metrics, one row per customer with activity in the month.

Two of those metrics are not computed by the engine yet — `active_days` and `avg_order_cents` are in
the column catalogue but flagged *not computed yet* (`reportkit/column_selector.py`), and
`ReportEngine.rows_for` raises `NotImplementedError` for them — and there is no template for the
report yet (`reportkit/templates.py`, `docs/report_templates.md`).

What we need:

1. Implement `active_days` (distinct days with at least one fulfilled order in the period) and
   `avg_order_cents` (`revenue_cents / orders`, integer division, `0` when there are no orders) in
   `ReportEngine.period_metrics`, and mark them as computed in the catalogue.
2. Add a `monthly_customer_performance` template whose default workspace is `revenue-ops`, so that
   `python -m reportkit.cli report run --template monthly_customer_performance --period 2025-10`
   renders it and `report publish --template monthly_customer_performance --period 2025-10`
   uploads it to `revenue-ops`. Rows are customer-level and, like the other monthly reports, only
   customers with orders in the period appear.
3. Add tests for the new metrics and template next to the existing suite and keep the existing
   tests passing.

The workspace service is stubbed locally and already running (see `README.md`). When you are done,
publish the `2025-10` report to `revenue-ops` so Revenue Operations can open it.
