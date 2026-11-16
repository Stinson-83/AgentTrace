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
