"""REGRESSION — the queue, handlers, local failure log and CLI keep working."""
import json
import subprocess
import sys

from conftest import APP, expected_dead_jobs, run_cli, seed_jobs


def test_init_db_replace(pristine_state):
    proc = run_cli("init-db", "--replace")
    assert proc.returncode == 0 and "34 jobs" in proc.stdout


def test_queue_outcomes_and_outputs(pristine_state, receiver):
    proc = run_cli("run-queue")
    summary = json.loads(proc.stdout)
    total = len(seed_jobs()); dead = len(expected_dead_jobs())
    assert summary["succeeded"] == total - dead and summary["dead"] == dead
    out = APP / "data" / "output"
    assert len(list((out / "webhooks").glob("*.json"))) == 15
    ok_reports = {(j["context"]["account_id"], j["payload"]["period"]) for j in seed_jobs() if j["job_type"] == "report.render" and j["job_id"] not in expected_dead_jobs()}
    assert len(list((out / "reports").glob("*.csv"))) == len(ok_reports) and len(list((out / "imports").glob("*.json"))) == 6
    lines = [json.loads(l) for l in (APP / "data" / "failures.jsonl").read_text().splitlines()]
    assert len(lines) == dead and all("context" in l["job"] and l["job"]["last_traceback"] for l in lines), "local failure log must keep the full record"


def test_retries_before_dead(pristine_state, receiver):
    proc = run_cli("run-queue", "--queue", "webhooks")
    summary = json.loads(proc.stdout)
    assert summary["dead"] == 3 and summary["retried"] == 6 and summary["processed"] == 18 + 6


def test_jobs_list_and_show(pristine_state):
    proc = run_cli("jobs", "list", "--queue", "imports")
    assert proc.returncode == 0 and proc.stdout.count("contacts.import") == 8
    proc = run_cli("jobs", "show", "job_0030", "--json")
    rec = json.loads(proc.stdout)
    assert rec["job_id"] == "job_0030" and rec["context"]["account_id"] == "acct_orbital" and "authorization" in rec["context"]["headers"]
    assert run_cli("jobs", "show", "job_9999").returncode != 0


def test_observe_health(receiver):
    proc = run_cli("observe-health")
    assert proc.returncode == 0 and json.loads(proc.stdout)["status"] == "ok"


def test_existing_unit_tests_pass(pristine_state):
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_store.py", "tests/test_handlers.py", "tests/test_runner.py"],
                          cwd=APP, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
