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


def make_order(order_id, placed_on, status="fulfilled", total_cents=100, customer_id="cus_2208"):
    from reportkit.customer_store import Order
    return Order(order_id, customer_id, placed_on, status, total_cents, 0, total_cents)


def test_period_metrics_active_days_and_average(engine):
    orders = [
        make_order("one", "2025-10-01", total_cents=100),
        make_order("two", "2025-10-01", total_cents=101),
        make_order("three", "2025-10-31", total_cents=103),
        make_order("refund", "2025-10-02", "refunded", 500),
        make_order("cancel", "2025-10-03", "cancelled", 900),
    ]
    assert engine.period_metrics(orders, "2025-10") == {
        "period": "2025-10", "orders": 3, "active_days": 2,
        "revenue_cents": 304, "refunds_cents": 500, "avg_order_cents": 101,
    }


@pytest.mark.parametrize("statuses", [[], ["refunded"], ["cancelled"], ["refunded", "cancelled"]])
def test_period_metrics_without_fulfilled_orders(engine, statuses):
    orders = [make_order(str(i), "2025-10-01", status) for i, status in enumerate(statuses)]
    metrics = engine.period_metrics(orders, "2025-10")
    assert metrics["orders"] == metrics["active_days"] == metrics["avg_order_cents"] == metrics["revenue_cents"] == 0
    assert metrics["refunds_cents"] == 100 * statuses.count("refunded")


def test_monthly_customer_performance_rows(engine, store, tmp_path):
    import json
    from dataclasses import asdict

    customers = store.customers()[:5]
    ids = [c.customer_id for c in customers]
    orders = [
        make_order("before", "2025-09-30", total_cents=9999, customer_id=ids[0]),
        make_order("first", "2025-10-01", total_cents=100, customer_id=ids[0]),
        make_order("same-day", "2025-10-01", total_cents=101, customer_id=ids[0]),
        make_order("last", "2025-10-31", total_cents=103, customer_id=ids[0]),
        make_order("after", "2025-11-01", total_cents=9999, customer_id=ids[0]),
        make_order("refund", "2025-10-15", "refunded", 500, ids[1]),
        make_order("cancel", "2025-10-16", "cancelled", 900, ids[2]),
        make_order("outside", "2025-09-30", customer_id=ids[3]),
    ]
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "customers.json").write_text(json.dumps([asdict(c) for c in customers]))
    (seed / "orders.json").write_text(json.dumps([asdict(o) for o in orders]))
    store.load_seed(seed, replace=True)

    template = get_template("monthly_customer_performance")
    report = engine.rows_for(template, "2025-10")
    assert [r["customer_id"] for r in report.rows] == ids[:3]
    row = report.rows[0]
    assert (row["orders"], row["active_days"], row["revenue_cents"], row["avg_order_cents"]) == (3, 2, 304, 101)
    assert row["refunds_cents"] == 0
    for row, customer in zip(report.rows, customers):
        assert row["period"] == "2025-10"
        for dimension in ("segment", "region", "account_manager"):
            assert row[dimension] == getattr(customer, dimension)
    for row in report.rows[1:]:
        assert row["orders"] == row["active_days"] == row["avg_order_cents"] == row["revenue_cents"] == 0
    assert report.rows[1]["refunds_cents"] == 500
    assert report.rows[2]["refunds_cents"] == 0
    assert engine.rows_for(template, "2024-01").rows == []


def test_new_metrics_can_be_included_in_existing_template(engine):
    report = engine.rows_for(get_template("finance_close"), "2025-10", include=["active_days", "avg_order_cents"])
    assert report.rows
    assert all(isinstance(row["active_days"], int) and isinstance(row["avg_order_cents"], int) for row in report.rows)
