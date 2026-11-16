import json
from dataclasses import replace
from unittest.mock import patch

import pytest

from taskforge.diagnostics import report_failure
from taskforge.observability_client import ObserveError


def test_report_failure_sends_contract_event(store, settings, observe_server):
    settings = replace(settings, observe_url=observe_server.url, observe_timeout_sec=0.75)
    job = store.get("job_0001")
    job.status = "dead"
    job.attempts = job.max_attempts
    job.started_at = "2025-11-10T09:00:00Z"
    job.finished_at = "2025-11-10T09:00:01.250Z"
    message = "failure " + "x" * 600
    tb = "Traceback (most recent call last):\n" + "".join(
        f'  File "/private/worker/frame{i}.py", line {i + 10}, in step{i}\n'
        '    raise RuntimeError("source should not be sent")\n'
        for i in range(7)
    ) + f"RuntimeError: {message}\n"

    event = report_failure(job, RuntimeError(message), tb, settings)

    assert event == {
        "event_type": "job.failed",
        "service": "taskforge-test",
        "environment": "test",
        "job_id": job.job_id,
        "job_type": job.job_type,
        "queue": job.queue,
        "failed_at": job.finished_at,
        "attempt": job.max_attempts,
        "error_type": "RuntimeError",
        "error_message": message[:499] + "…",
        "stack_summary": [
            {"file": f"frame{i}.py", "line": i + 10, "function": f"step{i}"}
            for i in range(2, 7)
        ],
        "request": {
            "request_id": job.context.request_id,
            "account_id": job.context.account_id,
            "route": job.context.route,
        },
        "duration_ms": 1250,
    }
    assert len(observe_server.requests) == 1
    sent = observe_server.requests[0]
    assert sent["path"] == "/v1/events"
    assert sent["headers"]["Content-Type"] == "application/x-ndjson"
    assert sent["headers"]["X-Service"] == settings.service_name
    assert sent["body"].endswith(b"\n")
    assert [json.loads(line) for line in sent["body"].splitlines()] == [event]


def test_report_failure_handles_empty_message_and_missing_timing(store, settings, observe_server):
    job = store.get("job_0001")
    job.finished_at = "2025-11-10T09:00:00Z"
    event = report_failure(job, RuntimeError(), "", replace(settings, observe_url=observe_server.url))
    assert event["error_message"] == ""
    assert event["stack_summary"] == []
    assert event["duration_ms"] is None


def test_report_failure_configures_client(store, settings):
    with patch("taskforge.diagnostics.ObservabilityClient") as client:
        event = report_failure(store.get("job_0001"), ValueError("bad input"), "", settings)
    client.assert_called_once_with(settings.observe_url, settings.observe_timeout_sec, settings.service_name)
    client.return_value.post_events.assert_called_once_with([event])


def test_report_failure_propagates_rejection(store, settings, observe_server):
    observe_server.status = 422
    with pytest.raises(ObserveError, match=r"rejected events \(422\)"):
        report_failure(store.get("job_0001"), ValueError("bad input"), "",
                       replace(settings, observe_url=observe_server.url))


@pytest.mark.parametrize(("message", "expected"), [
    ("POST https://user:secret@hooks.invalid/receive?token=secret#fragment failed: connection refused",
     "POST https://hooks.invalid/receive?[redacted] failed: connection refused"),
    ("1 of 4 rows have an invalid e-mail; first bad row 2: {'email': 'private@example.org', 'name': 'Private Name'}",
     "1 of 4 rows have an invalid e-mail; first bad row 2: [redacted]"),
])
def test_report_failure_does_not_export_replay_details(store, settings, observe_server, message, expected):
    job = store.get("job_0001")
    exc = RuntimeError(message)
    event = report_failure(job, exc, "", replace(settings, observe_url=observe_server.url))
    assert event["error_message"] == expected
    assert str(exc) == message
    assert event["request"] == {
        "request_id": job.context.request_id,
        "account_id": job.context.account_id,
        "route": job.context.route,
    }
    encoded = json.dumps(event)
    for private in ("secret", "private@example.org", "Private Name", job.context.body_preview,
                    job.context.headers["authorization"]):
        assert private not in encoded
