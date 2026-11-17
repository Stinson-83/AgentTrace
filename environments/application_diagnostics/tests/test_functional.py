"""FUNCTIONAL — dead jobs produce correct job.failed events that reach ops-observe."""
import json
import sqlite3

import pytest

from conftest import APP, events_in, expected_dead_jobs, records_since_marker, reset_state, run_cli


@pytest.fixture(scope="module")
def queue_run(receiver):
    reset_state()
    before = {r.file for r in records_since_marker()}
    proc = run_cli("run-queue")
    new = [r for r in records_since_marker() if r.file not in before]
    return proc, events_in(new)


def _dead_from_db() -> dict[str, dict]:
    conn = sqlite3.connect(str(APP / "data" / "taskforge.db"))
    conn.row_factory = sqlite3.Row
    return {r["job_id"]: dict(r) for r in conn.execute("SELECT * FROM jobs WHERE status = 'dead'")}


def test_run_queue_succeeds_and_counts_diagnostics(queue_run):
    proc, events = queue_run
    assert proc.returncode == 0, f"stdout={proc.stdout[-800:]!r} stderr={proc.stderr[-800:]!r}"
    summary = json.loads(proc.stdout)
    assert summary["dead"] == len(expected_dead_jobs()) == summary["diagnostics_sent"] and summary["diagnostics_errors"] == []


def test_one_event_per_dead_job_with_contract_fields(queue_run):
    _, events = queue_run
    failed = [e for e in events if e.get("event_type") == "job.failed"]
    expected = expected_dead_jobs()
    assert sorted(e["job_id"] for e in failed) == sorted(expected), f"got {[e.get('job_id') for e in failed]}"
    db = _dead_from_db()
    for e in failed:
        row = db[e["job_id"]]
        assert e["error_type"] == expected[e["job_id"]] == row["last_error_type"]
        assert e["job_type"] == row["job_type"] and e["queue"] == row["queue"]
        assert e["attempt"] == row["attempts"] == row["max_attempts"]
        assert e["failed_at"] == row["finished_at"]
        assert isinstance(e["error_message"], str) and 0 < len(e["error_message"]) <= 500
        assert e["service"] == "taskforge" and e["environment"] == "staging"
        frames = e["stack_summary"]
        assert isinstance(frames, list) and 1 <= len(frames) <= 5 and all({"file", "line", "function"} <= set(f) for f in frames)
        assert frames[-1]["file"] == "handlers.py"
        ctx = json.loads(row["context"])
        req = e["request"]
        assert req["request_id"] == ctx["request_id"] and req["account_id"] == ctx["account_id"] and req["route"] == ctx["route"]
        params = req.get("params")
        assert isinstance(params, dict), "request.params (query parameters triage filters on) missing"
        for key in ("source", "format", "report"):
            if key in ctx["query"]:
                assert params.get(key) == ctx["query"][key], f"{e['job_id']}: params.{key}"
        assert "duration_ms" in e


def test_successful_jobs_emit_nothing(queue_run):
    _, events = queue_run
    dead = set(expected_dead_jobs())
    assert all(e.get("job_id") in dead for e in events if e.get("event_type") == "job.failed")
    assert all(e.get("event_type") == "job.failed" for e in events)


def test_unreachable_observe_keeps_jobs_dead_and_reports(pristine_state):
    proc = run_cli("run-queue", env={"OPS_OBSERVE_URL": "http://127.0.0.1:1", "OPS_OBSERVE_TIMEOUT": "2"})
    assert proc.returncode == 3
    summary = json.loads(proc.stdout)
    assert summary["dead"] == len(expected_dead_jobs()) and len(summary["diagnostics_errors"]) == summary["dead"] and summary["diagnostics_sent"] == 0
    assert len(_dead_from_db()) == summary["dead"]
    assert (APP / "data" / "failures.jsonl").read_text().count("\n") == summary["dead"]


def test_rejected_events_are_reported(pristine_state, receiver):
    proc = run_cli("run-queue", env={"OPS_OBSERVE_URL": receiver + "/nowhere"})
    assert proc.returncode == 3 and json.loads(proc.stdout)["diagnostics_sent"] == 0
