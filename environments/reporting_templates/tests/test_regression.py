"""REGRESSION — existing templates, publishing and the catalogue keep working."""
import csv
import subprocess
import sys

from conftest import APP, records_since_marker, run_cli, seed, uploaded_csv


def test_init_db(pristine_db):
    proc = run_cli("init-db", "--replace")
    assert proc.returncode == 0 and "40 customers" in proc.stdout


def test_templates_and_columns_listed(pristine_db):
    proc = run_cli("templates")
    assert proc.returncode == 0 and all(t in proc.stdout for t in ("account_review", "finance_close", "delivery_manifest"))
    assert "revenue-ops" in proc.stdout or "monthly_customer_performance" in proc.stdout
    assert run_cli("columns").returncode == 0


def test_finance_close_values(pristine_db, tmp_path):
    out = tmp_path / "fc.csv"
    assert run_cli("report", "run", "--template", "finance_close", "--period", "2025-10", "--out", str(out)).returncode == 0
    rows = {r["customer_id"]: r for r in csv.DictReader(out.open())}
    orders = [o for o in seed("orders") if o["customer_id"] == "cus_2208" and o["placed_on"].startswith("2025-10")]
    assert int(rows["cus_2208"]["orders"]) == sum(1 for o in orders if o["status"] == "fulfilled")
    assert int(rows["cus_2208"]["revenue_cents"]) == sum(o["total_cents"] for o in orders if o["status"] == "fulfilled")
    assert list(rows["cus_2208"].keys()) == ["customer_id", "segment", "period", "orders", "revenue_cents", "refunds_cents"]


def test_account_review_publish_to_its_own_workspace(pristine_db, receiver):
    before = {r.file for r in records_since_marker()}
    proc = run_cli("report", "publish", "--template", "account_review", "--period", "2025-10")
    assert proc.returncode == 0, proc.stderr
    new = [r for r in records_since_marker() if r.file not in before]
    assert [r.path for r in new] == ["/workspaces/account-management/reports"]
    _, rows = uploaded_csv(new[0])
    row = next(r for r in rows if r["customer_id"] == "cus_2208")
    assert row["residential_address"] == "17 Harrowgate Lane, Flat 3B" and row["lifetime_orders"].isdigit()


def test_delivery_manifest(pristine_db, tmp_path):
    out = tmp_path / "dm.csv"
    assert run_cli("report", "run", "--template", "delivery_manifest", "--period", "2025-10", "--out", str(out)).returncode == 0
    rows = list(csv.DictReader(out.open()))
    assert rows and list(rows[0].keys()) == ["order_id", "placed_on", "full_name", "residential_address", "postcode"]


def test_include_exclude_and_errors(pristine_db, tmp_path):
    out = tmp_path / "x.csv"
    assert run_cli("report", "run", "--template", "finance_close", "--period", "2025-10", "--include", "region", "--exclude", "refunds_cents", "--out", str(out)).returncode == 0
    assert list(csv.DictReader(out.open()))[0].keys() >= {"region"} and "refunds_cents" not in next(csv.DictReader(out.open()))
    assert run_cli("report", "run", "--template", "finance_close", "--period", "2025-10", "--include", "nope").returncode != 0


def test_workspace_health(receiver):
    assert run_cli("workspace-health").returncode == 0


def test_existing_unit_tests_pass(pristine_db):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_templates_and_columns.py", "tests/test_engine.py"],
                          cwd=APP, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
