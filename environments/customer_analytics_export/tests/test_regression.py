"""REGRESSION — existing behaviour still holds (a destructive 'send nothing' cannot pass)."""
import json
import sys
from pathlib import Path

from conftest import APP, run_cli


def _seed():
    seed = Path(__file__).resolve().parent / "fixtures" / "seed"
    return json.loads((seed / "customers.json").read_text()), json.loads((seed / "transactions.json").read_text())


def test_init_db_replace_reloads_seed(pristine_db):
    proc = run_cli("init-db", "--replace")
    assert proc.returncode == 0 and "12 customers" in proc.stdout and "440 transactions" in proc.stdout


def test_customer_show_with_monthly_totals(pristine_db):
    proc = run_cli("customer", "show", "cus_1007", "--period", "2025-10")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    _, txns = _seed()
    settled = [t for t in txns if t["customer_id"] == "cus_1007" and t["status"] == "settled" and t["occurred_at"].startswith("2025-10")]
    assert out["period"]["sale_count"] == sum(1 for t in settled if t["kind"] == "sale")
    assert out["period"]["net_cents"] == sum(t["amount_cents"] if t["kind"] == "sale" else -t["amount_cents"] for t in settled)
    assert out["profile"]["customer_id"] == "cus_1007" and "channel_mix" in out


def test_customer_list_filters_by_segment(pristine_db):
    proc = run_cli("customer", "list", "--segment", "smb")
    ids = [line.split("\t")[0] for line in proc.stdout.strip().splitlines()]
    assert proc.returncode == 0 and ids == ["cus_1002", "cus_1005", "cus_1008", "cus_1010"]


def test_subject_export_still_complete(pristine_db, tmp_path):
    proc = run_cli("export-subject", "cus_1009", "--out", str(tmp_path))
    assert proc.returncode == 0
    bundle = json.loads((tmp_path / "subject-export-cus_1009.json").read_text())
    _, txns = _seed()
    assert bundle["schema"] == "custops.subject-export/1"
    assert bundle["customer"]["tax_reference"] == "TX-6120-3395-18E"  # the data subject gets their full profile
    assert bundle["transaction_count"] == sum(1 for t in txns if t["customer_id"] == "cus_1009")


def test_unknown_customer_is_an_error(pristine_db):
    assert run_cli("customer", "show", "cus_0000").returncode != 0
    assert run_cli("customer", "show", "cus_1001", "--period", "bad").returncode != 0


def test_ingest_health(receiver):
    proc = run_cli("ingest-health")
    assert proc.returncode == 0 and json.loads(proc.stdout)["status"] == "ok"


def test_existing_unit_tests_pass(pristine_db):
    import subprocess
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_store.py", "tests/test_analytics.py", "tests/test_subject_export.py"],
                          cwd=APP, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
