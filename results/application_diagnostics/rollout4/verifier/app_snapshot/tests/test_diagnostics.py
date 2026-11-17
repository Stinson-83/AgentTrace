import io
import json
import urllib.error
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from taskforge.diagnostics import report_failure
from taskforge.models import Job, RequestContext
from taskforge.observability_client import ObserveError


@pytest.fixture
def dead_job():
    context = RequestContext(
        request_id="req_failed", received_at="2025-11-10T08:00:00Z", method="POST",
        route="/v2/reports", client_ip="203.0.113.1", account_id="acct_test",
        headers={"Authorization": "Bearer header-secret"},
        query={"source": "sdk", "format": "csv", "report": "usage", "period": "2025-10",
               "future_filter": "keep me", "api_key": "query-secret", "API_KEY": "mixed-case-secret"},
        body_preview="private body",
    )
    return Job(
        job_id="job_failed", job_type="report.render", queue="reports", status="dead",
        payload={"private": "payload"}, context=context, attempts=3, max_attempts=3,
        started_at="2025-11-10T08:00:01.000Z", finished_at="2025-11-10T08:00:01.125Z",
    )


def test_report_failure_sends_contract_as_ndjson(dead_job, settings, monkeypatch):
    urlopen = MagicMock()
    response = urlopen.return_value.__enter__.return_value
    response.status = 202
    response.read.return_value = b'{"ingested":1,"batch_id":"ob_test"}'
    monkeypatch.setattr("taskforge.observability_client.urllib.request.urlopen", urlopen)
    settings = replace(settings, observe_url="http://observe.example/", observe_timeout_sec=2.5)
    traceback_text = "Traceback (most recent call last):\n" + "".join(
        f'  File "/private/path/frame{i}.py", line {i + 1}, in call{i}\n    secret_source()\n'
        for i in range(7)
    ) + "ValueError: private traceback message\n"

    event = report_failure(dead_job, ValueError("x" * 600), traceback_text, settings)

    assert event == {
        "event_type": "job.failed", "service": "taskforge-test", "environment": "test",
        "job_id": "job_failed", "job_type": "report.render", "queue": "reports",
        "failed_at": dead_job.finished_at, "attempt": 3, "error_type": "ValueError",
        "error_message": "x" * 499 + "…",
        "stack_summary": [
            {"file": f"frame{i}.py", "line": i + 1, "function": f"call{i}"} for i in range(2, 7)
        ],
        "request": {
            "request_id": "req_failed", "account_id": "acct_test", "route": "/v2/reports",
            "params": {**dead_job.context.query, "api_key": "[REDACTED]", "API_KEY": "[REDACTED]"},
        },
        "duration_ms": 125,
    }
    urlopen.assert_called_once()
    (request,), kwargs = urlopen.call_args
    assert kwargs == {"timeout": 2.5}
    assert request.full_url == "http://observe.example/v1/events"
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/x-ndjson"
    assert request.get_header("X-service") == settings.service_name
    assert request.data.endswith(b"\n")
    assert len(request.data.splitlines()) == 1
    assert json.loads(request.data) == event
    assert dead_job.context.query["api_key"] == "query-secret"
    assert dead_job.context.query["API_KEY"] == "mixed-case-secret"
    for private in ("query-secret", "mixed-case-secret", "header-secret", "private body", "payload", "secret_source"):
        assert private.encode() not in request.data


def test_report_failure_empty_details(dead_job, settings, monkeypatch):
    post = MagicMock()
    monkeypatch.setattr("taskforge.diagnostics.ObservabilityClient.post_events", post)
    dead_job.started_at = None
    dead_job.context = replace(dead_job.context, query={})
    event = report_failure(dead_job, RuntimeError(), "", settings)
    assert event["error_message"] == ""
    assert event["stack_summary"] == []
    assert event["duration_ms"] is None
    assert event["request"]["params"] == {}
    post.assert_called_once_with([event])


@pytest.mark.parametrize("rejected", [False, True], ids=["unreachable", "rejected"])
def test_report_failure_propagates_delivery_error(dead_job, settings, monkeypatch, rejected):
    error = (
        urllib.error.HTTPError(settings.observe_url, 422, "Rejected", {}, io.BytesIO(b'{"error":"bad event"}'))
        if rejected else urllib.error.URLError("connection refused")
    )
    monkeypatch.setattr("taskforge.observability_client.urllib.request.urlopen", MagicMock(side_effect=error))
    with pytest.raises(ObserveError, match="rejected events \\(422\\)" if rejected else "unreachable"):
        report_failure(dead_job, ValueError("boom"), "", settings)
