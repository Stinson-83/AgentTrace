import io
import json
import urllib.error
from unittest.mock import MagicMock

import pytest

from taskforge import cli

from taskforge.diagnostics import stack_summary, truncate
from taskforge.runner import run_queue


@pytest.fixture
def send_events(monkeypatch):
    post = MagicMock()
    monkeypatch.setattr("taskforge.diagnostics.ObservabilityClient.post_events", post)
    return post


def test_run_queue_processes_everything(store, settings, send_events):
    summary = run_queue(store, settings)
    counts = store.counts()
    assert summary.processed == 34 + summary.retried
    assert counts.get("pending", 0) == 0 and counts["succeeded"] == 27 and counts["dead"] == 7
    assert summary.dead == 7 and summary.succeeded == 27
    assert summary.diagnostics_sent == 7 and summary.diagnostics_errors == []
    assert send_events.call_count == 7
    events = [call.args[0][0] for call in send_events.call_args_list]
    assert {event["job_id"] for event in events} == {job.job_id for job in store.list(status="dead")}
    for event in events:
        job = store.get(event["job_id"])
        assert event["attempt"] == job.max_attempts
        assert event["failed_at"] == job.finished_at
        assert event["duration_ms"] == job.duration_ms
        assert event["error_type"] == job.last_error_type
        assert event["request"]["request_id"] == job.context.request_id


def test_failure_log_has_full_record(store, settings, send_events):
    run_queue(store, settings)
    lines = [json.loads(l) for l in settings.failure_log.read_text().splitlines()]
    assert len(lines) == 7
    for line in lines:
        job = store.get(line["job"]["job_id"])
        assert job.status == "dead"
        assert line == {"logged_at": job.finished_at, "job": job.to_dict()}


def test_dead_jobs_have_error_details(store, settings, send_events):
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


def test_retry_does_not_send_diagnostics(store, settings, send_events, monkeypatch):
    def fail(job, settings):
        raise ValueError("retry me")

    monkeypatch.setattr("taskforge.runner.handler_for", lambda job_type: fail)
    summary = run_queue(store, settings, max_jobs=1)
    assert summary.processed == 1 and summary.retried == 1 and summary.dead == 0
    assert summary.diagnostics_sent == 0 and summary.diagnostics_errors == []
    assert not settings.failure_log.exists()
    send_events.assert_not_called()


@pytest.mark.parametrize("outcome", ["accepted", "unreachable", "rejected"])
def test_cli_diagnostics_delivery(store, settings, monkeypatch, capsys, outcome):
    urlopen = MagicMock()
    if outcome == "unreachable":
        urlopen.side_effect = urllib.error.URLError("connection refused")
    elif outcome == "rejected":
        # Use a fresh response body for each rejected request.
        def reject(*args, **kwargs):
            raise urllib.error.HTTPError(settings.observe_url, 422, "Rejected", {}, io.BytesIO(b"bad event"))
        urlopen.side_effect = reject
    else:
        response = urlopen.return_value.__enter__.return_value
        response.status = 202
        response.read.return_value = b'{"ingested":1}'
    monkeypatch.setattr("taskforge.observability_client.urllib.request.urlopen", urlopen)
    monkeypatch.setattr(cli, "_store", lambda config: store)
    monkeypatch.setattr(cli, "load_settings", lambda: settings)

    exit_code = cli.main(["run-queue"])

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == (0 if outcome == "accepted" else 3)
    assert summary["dead"] == 7 and summary["succeeded"] == 27
    assert summary["diagnostics_sent"] == (7 if outcome == "accepted" else 0)
    assert urlopen.call_count == 7
    assert store.counts() == {"dead": 7, "succeeded": 27}
    dead_ids = {job.job_id for job in store.list(status="dead")}
    errors = summary["diagnostics_errors"]
    if outcome == "accepted":
        assert errors == []
    else:
        assert len(errors) == 7
        assert {error.split(":", 1)[0] for error in errors} == dead_ids
        expected = "rejected events (422)" if outcome == "rejected" else "unreachable"
        assert all("ObserveError" in error and expected in error for error in errors)
    lines = [json.loads(line) for line in settings.failure_log.read_text().splitlines()]
    assert len(lines) == 7
    assert {line["job"]["job_id"] for line in lines} == dead_ids
    for line in lines:
        job = store.get(line["job"]["job_id"])
        assert line == {"logged_at": job.finished_at, "job": job.to_dict()}
        assert job.last_error_type and job.last_traceback
        assert job.attempts == job.max_attempts
