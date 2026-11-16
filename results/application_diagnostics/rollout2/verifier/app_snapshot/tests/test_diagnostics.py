import json
from dataclasses import replace

import pytest

from taskforge.diagnostics import report_failure, truncate
from taskforge.handlers import DeliveryError
from taskforge.models import Job, RequestContext


@pytest.fixture()
def dead_job():
    context = RequestContext(
        "req_test", "2025-11-10T08:00:00Z", "POST", "/v2/webhooks", "203.0.113.1", "acct_test",
        {"authorization": "Bearer private-header"}, {"token": "private-query"}, "private-body",
    )
    return Job(
        "job_test", "webhook.deliver", "webhooks", "dead", {"url": "private-payload"}, context,
        attempts=3, max_attempts=3, started_at="2025-11-10T08:01:00Z", finished_at="2025-11-10T08:01:00.125Z",
    )


def test_report_failure_sends_contract_as_ndjson(dead_job, settings, observe_server):
    settings = replace(settings, observe_url=observe_server.url + "/", observe_timeout_sec=0.5)
    tb = 'Traceback (most recent call last):\n' + ''.join(
        f'  File "/worker/module{i}.py", line {i + 1}, in frame{i}\n    private-source\n' for i in range(7)
    ) + 'DeliveryError: private-error\n'
    event = report_failure(dead_job, DeliveryError("private-error", summary="webhook endpoint unreachable (DNS)"), tb, settings)
    assert event == {
        "event_type": "job.failed", "service": "taskforge-test", "environment": "test",
        "job_id": "job_test", "job_type": "webhook.deliver", "queue": "webhooks",
        "failed_at": "2025-11-10T08:01:00.125Z", "attempt": 3,
        "error_type": "DeliveryError", "error_message": "webhook endpoint unreachable (DNS)",
        "stack_summary": [{"file": f"module{i}.py", "line": i + 1, "function": f"frame{i}"} for i in range(2, 7)],
        "request": {"request_id": "req_test", "account_id": "acct_test", "route": "/v2/webhooks"},
        "duration_ms": 125,
    }
    assert len(observe_server.requests) == 1
    request = observe_server.requests[0]
    assert request["path"] == "/v1/events"
    assert request["headers"]["Content-Type"] == "application/x-ndjson"
    assert request["headers"]["X-Service"] == settings.service_name
    assert request["body"].endswith(b"\n") and len(request["body"].splitlines()) == 1
    assert json.loads(request["body"]) == event
    assert b"private-" not in request["body"]
    assert b"203.0.113.1" not in request["body"]


def test_report_failure_truncates_summary(dead_job, settings, observe_server):
    settings = replace(settings, observe_url=observe_server.url)
    message = "é" * 600
    event = report_failure(dead_job, DeliveryError("private-error", summary=message), "", settings)
    assert event["error_message"] == truncate(message)
    assert len(event["error_message"]) == 500
    assert event["stack_summary"] == []


def test_unexpected_exception_uses_value_free_fallback(dead_job, settings, observe_server):
    settings = replace(settings, observe_url=observe_server.url)
    dead_job.started_at = None
    event = report_failure(dead_job, ValueError("private-error"), "", settings)
    assert event["error_type"] == "ValueError"
    assert event["error_message"] == "ValueError"
    assert event["duration_ms"] is None
