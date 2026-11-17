"""REGRESSION — existing desk behaviour still holds."""
import json
import subprocess
import sys

from conftest import APP, records_since_marker, run_cli, seed


def test_init_db_replace(pristine_db):
    proc = run_cli("init-db", "--replace")
    assert proc.returncode == 0 and "130 tickets" in proc.stdout


def test_ticket_show_scoped_view(pristine_db):
    proc = run_cli("ticket", "show", "1042", "--tenant", "harbourline")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["ticket"]["subject"] == "Checkout timeout on bulk pallet orders" and out["customer"]["name"] == "Priya Raman" and out["ticket"]["status"] == "escalated"
    assert out["sla"]["breached"] is True and isinstance(out["related"], list)
    assert run_cli("ticket", "show", "1055", "--tenant", "northwind").returncode != 0


def test_ticket_list_and_search(pristine_db):
    proc = run_cli("ticket", "list", "--tenant", "cobalt", "--status", "open")
    assert proc.returncode == 0 and proc.stdout.count("\n") >= 1 and "#" in proc.stdout
    proc = run_cli("ticket", "search", "checkout", "timeout")
    assert proc.returncode == 0 and "northwind" in proc.stdout and "harbourline" in proc.stdout


def test_add_note(pristine_db):
    proc = run_cli("ticket", "note", "1003", "--tenant", "northwind", "--author", "grader", "checking", "in")
    assert proc.returncode == 0 and "internal note" in proc.stdout
    assert run_cli("ticket", "note", "1055", "--tenant", "northwind", "--author", "g", "x").returncode != 0


def test_sla_report(pristine_db):
    proc = run_cli("sla-report", "--tenant", "northwind", "--json")
    rows = json.loads(proc.stdout)
    open_nw = [t for t in seed("tickets") if t["tenant_id"] == "ten_nw" and t["status"] in ("open", "pending", "escalated")]
    assert proc.returncode == 0 and len(rows) == len(open_nw)
    assert any(r["number"] == 1042 and r["breached"] for r in rows)


def test_oncall_digest(pristine_db, receiver):
    proc = run_cli("oncall-digest", "--dry-run")
    assert proc.returncode == 0
    queue = json.loads(proc.stdout)["queue"]
    assert queue and {q["tenant"] for q in queue} >= {"harbourline", "northwind"} and all("latest_internal_note" in q for q in queue)
    before = len(records_since_marker())
    assert run_cli("oncall-digest").returncode == 0 and len(records_since_marker()) == before + 1


def test_relay_health(receiver):
    proc = run_cli("relay-health")
    assert proc.returncode == 0 and json.loads(proc.stdout)["status"] == "ok"


def test_existing_unit_tests_pass(pristine_db):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_stores.py", "tests/test_escalation.py"],
                          cwd=APP, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
