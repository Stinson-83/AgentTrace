import json
from dataclasses import replace

import pytest

from taskforge import cli

from taskforge.diagnostics import stack_summary, truncate
from taskforge.runner import run_queue


def test_run_queue_processes_everything(store, settings, observe_server):
    settings = replace(settings, observe_url=observe_server.url)
    summary = run_queue(store, settings)
    counts = store.counts()
    assert summary.processed == 34 + summary.retried
    assert counts.get("pending", 0) == 0 and counts["succeeded"] == 27 and counts["dead"] == 7
    assert summary.dead == 7 and summary.succeeded == 27
    assert summary.diagnostics_sent == 7
    assert summary.diagnostics_errors == []
    events = [json.loads(request["body"]) for request in observe_server.requests]
    assert {event["job_id"] for event in events} == {job.job_id for job in store.list(status="dead")}
    assert len(events) == 7
    for event in events:
        job = store.get(event["job_id"])
        assert event["attempt"] == job.max_attempts
        assert event["failed_at"] == job.finished_at
        assert event["duration_ms"] == job.duration_ms


def test_failure_log_has_full_record(store, settings):
    run_queue(store, settings)
    lines = [json.loads(l) for l in settings.failure_log.read_text().splitlines()]
    assert len(lines) == 7 and all(l["job"]["status"] == "dead" and "context" in l["job"] for l in lines)


def test_dead_jobs_have_error_details(store, settings):
    run_queue(store, settings, queue="webhooks")
    dead = store.list(status="dead")
    assert len(dead) == 3 and all(j.last_error_type == "DeliveryError" and j.attempts == j.max_attempts for j in dead)
    breakdown = store.failure_breakdown()
    assert breakdown == {"by_error_type": {"DeliveryError": 3}, "by_queue": {"webhooks": 3}}


def test_stack_summary_and_truncate():
    tb = 'Traceback (most recent call last):\n  File "/app/taskforge/runner.py", line 40, in run_one\n    result = handler_for(job.job_type)(job, settings)\n  File "/app/taskforge/handlers.py", line 50, in deliver_webhook\n    raise DeliveryError("x")\ntaskforge.handlers.DeliveryError: x\n'
    frames = stack_summary(tb)
    assert frames == [{"file": "runner.py", "line": 40, "function": "run_one"}, {"file": "handlers.py", "line": 50, "function": "deliver_webhook"}]
    assert truncate("a" * 600).endswith("…") and len(truncate("a" * 600)) == 500


@pytest.mark.parametrize("delivery", ["success", "unreachable", "rejected"])
def test_run_queue_cli_preserves_local_failures(store, settings, observe_server, monkeypatch, capsys, delivery):
    if delivery != "unreachable":
        settings = replace(settings, observe_url=observe_server.url)
    if delivery == "rejected":
        observe_server.status = 503
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    exit_code = cli.main(["run-queue"])

    summary = json.loads(capsys.readouterr().out)
    success = delivery == "success"
    assert exit_code == (0 if success else 3)
    assert summary["dead"] == 7
    assert summary["succeeded"] == 27
    assert summary["diagnostics_sent"] == (7 if success else 0)
    assert len(summary["diagnostics_errors"]) == (0 if success else 7)
    if not success:
        expected = "unreachable" if delivery == "unreachable" else "rejected events (503)"
        assert all("ObserveError" in error and expected in error for error in summary["diagnostics_errors"])
    logged = [json.loads(line)["job"] for line in settings.failure_log.read_text().splitlines()]
    dead = store.list(status="dead")
    assert len(logged) == len(dead) == 7
    assert {job["job_id"] for job in logged} == {job.job_id for job in dead}
    for record in logged:
        job = store.get(record["job_id"])
        assert record == job.to_dict()
        assert record["last_error_message"]
        assert record["last_traceback"]
        assert record["context"]["headers"] == job.context.headers
