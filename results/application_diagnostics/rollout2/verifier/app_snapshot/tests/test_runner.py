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
    assert summary.diagnostics_sent == 7 and summary.diagnostics_errors == []
    events = [json.loads(r["body"]) for r in observe_server.requests]
    dead = store.list(status="dead")
    assert {e["job_id"] for e in events} == {j.job_id for j in dead}
    for event in events:
        job = store.get(event["job_id"])
        assert event["attempt"] == job.attempts == job.max_attempts
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


@pytest.mark.parametrize("status", [202, 422, 503, "unreachable"])
def test_cli_delivery_outcome_preserves_dead_jobs_and_log(store, settings, observe_server, monkeypatch, capsys, status):
    if status == "unreachable":
        import urllib.error
        import urllib.request

        def unavailable(*args, **kwargs):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", unavailable)
    else:
        observe_server.status = status
    settings = replace(settings, observe_url=observe_server.url)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_store", lambda settings: store)
    exit_code = cli.main(["run-queue"])
    summary = json.loads(capsys.readouterr().out)
    assert store.counts() == {"dead": 7, "succeeded": 27}
    records = [json.loads(line)["job"] for line in settings.failure_log.read_text().splitlines()]
    assert {r["job_id"] for r in records} == {j.job_id for j in store.list(status="dead")}
    for record in records:
        assert record == store.get(record["job_id"]).to_dict()
        assert record["last_error_message"] and record["last_traceback"] and record["context"]
    if status == 202:
        assert exit_code == 0 and summary["diagnostics_sent"] == 7
        assert summary["diagnostics_errors"] == []
    else:
        assert exit_code == 3 and summary["diagnostics_sent"] == 0
        errors = summary["diagnostics_errors"]
        assert len(errors) == 7
        detail = "unreachable" if status == "unreachable" else f"rejected events ({status})"
        assert all("ObserveError" in error and detail in error for error in errors)
        assert all(any(r["job_id"] in error for error in errors) for r in records)


def test_diagnostics_only_sent_after_final_attempt(store, settings, observe_server):
    settings = replace(settings, observe_url=observe_server.url)
    context = store.get("job_0001").context
    store.enqueue("job_retry_test", "unknown.type", "test-retries", {}, context, max_attempts=2)
    first = run_queue(store, settings, queue="test-retries", max_jobs=1)
    assert first.retried == 1 and first.dead == first.diagnostics_sent == 0
    assert first.diagnostics_errors == [] and observe_server.requests == []
    assert not settings.failure_log.exists()
    final = run_queue(store, settings, queue="test-retries")
    assert final.dead == final.diagnostics_sent == 1 and final.diagnostics_errors == []
    assert len(observe_server.requests) == 1
    event = json.loads(observe_server.requests[0]["body"])
    assert event["job_id"] == "job_retry_test" and event["attempt"] == 2
