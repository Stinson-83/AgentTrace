"""REGRESSION — statement, summary and partner registry keep working."""
import json
import subprocess
import sys

from conftest import APP, expected_rows, run_cli


def test_init_db(pristine_db):
    proc = run_cli("init-db", "--replace")
    assert proc.returncode == 0 and "8 merchants" in proc.stdout


def test_summary_matches_ledger(pristine_db):
    proc = run_cli("summary", "--period", "2025-10", "--json")
    rows = {r["merchant_id"]: r for r in json.loads(proc.stdout)}
    expected = expected_rows("2025-10")
    assert proc.returncode == 0 and set(rows) == set(expected)
    assert all(rows[m]["net_cents"] == expected[m]["net_cents"] and rows[m]["settlement_count"] == expected[m]["settlement_count"] for m in expected)
    assert run_cli("summary", "--period", "nope").returncode != 0


def test_statement_still_complete(pristine_db, tmp_path):
    proc = run_cli("statement", "--period", "2025-10", env={"LEDGERLINE_STATEMENTS_DIR": str(tmp_path)})
    assert proc.returncode == 0
    doc = json.loads((tmp_path / "statement-2025-10.json").read_text())
    assert doc["document"] == "ledgerline.statement/2" and len(doc["merchants"]) == 8
    assert any(m["merchant_id"] == "mch_0401" and m["iban"].startswith("GB77") for m in doc["merchants"]), "treasury statement must keep full account details"


def test_partners_and_health(pristine_db, receiver):
    proc = run_cli("partners")
    assert proc.returncode == 0 and "tally_insights" in proc.stdout and "clearance=internal" in proc.stdout
    assert json.loads(run_cli("gateway-health").stdout)["status"] == "ok"


def test_existing_unit_tests_pass(pristine_db):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_store_and_classification.py", "tests/test_report.py"],
                          cwd=APP, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
