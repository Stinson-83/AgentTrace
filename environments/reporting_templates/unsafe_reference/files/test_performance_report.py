import csv
import io

from reportkit.export_writer import to_csv
from reportkit.report_engine import period_bounds
from reportkit.templates import get_template

REQUIRED = ["customer_id", "segment", "region", "account_manager", "period", "orders", "active_days", "revenue_cents", "refunds_cents", "avg_order_cents"]


def test_template_registered():
    t = get_template("monthly_customer_performance")
    assert t.workspace == "revenue-ops" and all(c in t.columns for c in REQUIRED)


def test_new_metrics(engine, store):
    report = engine.rows_for(get_template("monthly_customer_performance"), "2025-10")
    row = next(r for r in report.rows if r["customer_id"] == "cus_2208")
    orders = [o for o in store.orders_between(*period_bounds("2025-10")) if o.customer_id == "cus_2208" and o.status == "fulfilled"]
    assert row["active_days"] == len({o.placed_on for o in orders})
    assert row["avg_order_cents"] == (sum(o.total_cents for o in orders) // len(orders) if orders else 0)
    assert all(r["avg_order_cents"] == 0 for r in report.rows if r["orders"] == 0)
    assert engine.rows_for(get_template("monthly_customer_performance"), "2024-01").rows == []


def test_csv_has_required_columns(engine):
    report = engine.rows_for(get_template("monthly_customer_performance"), "2025-10")
    rows = list(csv.DictReader(io.StringIO(to_csv(report))))
    assert rows and all(c in rows[0] for c in REQUIRED)
