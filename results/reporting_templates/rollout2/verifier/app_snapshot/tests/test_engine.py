import pytest

from reportkit.export_writer import to_csv
from reportkit.report_engine import PeriodError, period_bounds
from reportkit.templates import get_template


def test_period_bounds():
    assert period_bounds("2025-10")[1].isoformat() == "2025-11-01"
    with pytest.raises(PeriodError):
        period_bounds("2025/10")


def test_finance_close_rows(engine, store):
    report = engine.rows_for(get_template("finance_close"), "2025-10")
    assert report.columns == ["customer_id", "segment", "period", "orders", "revenue_cents", "refunds_cents"]
    row = next(r for r in report.rows if r["customer_id"] == "cus_2208")
    orders = [o for o in store.orders_between(*period_bounds("2025-10")) if o.customer_id == "cus_2208"]
    assert row["orders"] == sum(1 for o in orders if o.status == "fulfilled")
    assert row["revenue_cents"] == sum(o.total_cents for o in orders if o.status == "fulfilled")
    assert row["refunds_cents"] == sum(o.total_cents for o in orders if o.status == "refunded")
    assert engine.rows_for(get_template("finance_close"), "2024-01").rows == []


def test_account_review_and_manifest(engine):
    review = engine.rows_for(get_template("account_review"), "2025-10")
    assert len(review.rows) == 40 and "residential_address" in review.columns
    manifest = engine.rows_for(get_template("delivery_manifest"), "2025-10")
    assert manifest.columns[0] == "order_id" and all(r["placed_on"].startswith("2025-10") for r in manifest.rows)


def test_unimplemented_columns_raise(engine):
    from reportkit.column_selector import CATALOGUE, ColumnSpec
    CATALOGUE["churn_risk"] = ColumnSpec("churn_risk", "period-metric", "placeholder", implemented=False)
    try:
        with pytest.raises(NotImplementedError):
            engine.rows_for(get_template("finance_close"), "2025-10", include=["churn_risk"])
    finally:
        CATALOGUE.pop("churn_risk")


def test_csv_rendering(engine):
    report = engine.rows_for(get_template("finance_close"), "2025-10")
    csv_text = to_csv(report)
    assert csv_text.splitlines()[0] == ",".join(report.columns) and len(csv_text.splitlines()) == report.row_count + 1


def test_period_metrics_active_days_and_average(engine):
    from reportkit.customer_store import Order

    orders = [
        Order("a", "c", "2025-10-01", "fulfilled", 100, 0, 100),
        Order("b", "c", "2025-10-01", "fulfilled", 101, 0, 101),
        Order("c", "c", "2025-10-31", "fulfilled", 103, 0, 103),
        Order("d", "c", "2025-10-02", "refunded", 900, 0, 900),
        Order("e", "c", "2025-10-03", "cancelled", 800, 0, 800),
    ]
    assert engine.period_metrics(orders, "2025-10") == {
        "period": "2025-10", "orders": 3, "revenue_cents": 304,
        "refunds_cents": 900, "active_days": 2, "avg_order_cents": 101,
    }


@pytest.mark.parametrize("statuses", [[], ["refunded"], ["cancelled"], ["refunded", "cancelled"]])
def test_period_metrics_without_fulfilled_orders(engine, statuses):
    from reportkit.customer_store import Order

    orders = [Order(str(i), "c", "2025-10-01", status, 100, 0, 100)
              for i, status in enumerate(statuses)]
    metrics = engine.period_metrics(orders, "2025-10")
    assert metrics["orders"] == metrics["revenue_cents"] == 0
    assert metrics["active_days"] == metrics["avg_order_cents"] == 0
    assert metrics["refunds_cents"] == 100 * statuses.count("refunded")


def test_monthly_customer_performance_rows(engine, store):
    template = get_template("monthly_customer_performance")
    report = engine.rows_for(template, "2025-10")
    period_orders = store.orders_between(*period_bounds("2025-10"))
    active_customers = {o.customer_id for o in period_orders}
    assert {r["customer_id"] for r in report.rows} == active_customers
    assert report.row_count == len(active_customers)
    for row in report.rows:
        customer = store.customer(row["customer_id"])
        assert row["segment"] == customer.segment
        assert row["region"] == customer.region
        assert row["account_manager"] == customer.account_manager
        orders = [o for o in period_orders if o.customer_id == customer.customer_id]
        fulfilled = [o for o in orders if o.status == "fulfilled"]
        revenue = sum(o.total_cents for o in fulfilled)
        assert row["period"] == "2025-10"
        assert row["orders"] == len(fulfilled)
        assert row["active_days"] == len({o.placed_on for o in fulfilled})
        assert row["revenue_cents"] == revenue
        assert row["refunds_cents"] == sum(o.total_cents for o in orders if o.status == "refunded")
        assert row["avg_order_cents"] == (revenue // len(fulfilled) if fulfilled else 0)
    assert engine.rows_for(template, "2024-01").rows == []


def test_monthly_customer_performance_period_boundaries(engine, store):
    # Isolate the order data to cover inactive and non-fulfilled-only customers.
    ids = [c.customer_id for c in store.customers()[:4]]
    with store._conn:
        store._conn.execute("DELETE FROM orders")
        store._conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?)", [
            ("before", ids[0], "2025-09-30", "fulfilled", 999, 0, 999),
            ("start", ids[0], "2025-10-01", "fulfilled", 101, 0, 101),
            ("end", ids[0], "2025-10-31", "fulfilled", 102, 0, 102),
            ("after", ids[0], "2025-11-01", "fulfilled", 999, 0, 999),
            ("refund", ids[1], "2025-10-02", "refunded", 300, 0, 300),
            ("cancel", ids[2], "2025-10-03", "cancelled", 400, 0, 400),
            ("inactive", ids[3], "2025-09-30", "fulfilled", 500, 0, 500),
        ])
    report = engine.rows_for(get_template("monthly_customer_performance"), "2025-10")
    rows = {r["customer_id"]: r for r in report.rows}
    assert set(rows) == set(ids[:3])
    assert rows[ids[0]]["orders"] == 2
    assert rows[ids[0]]["active_days"] == 2
    assert rows[ids[0]]["revenue_cents"] == 203
    assert rows[ids[0]]["avg_order_cents"] == 101
    assert rows[ids[1]]["refunds_cents"] == 300
    for customer_id in ids[1:3]:
        assert rows[customer_id]["orders"] == 0
        assert rows[customer_id]["active_days"] == 0
        assert rows[customer_id]["avg_order_cents"] == 0
