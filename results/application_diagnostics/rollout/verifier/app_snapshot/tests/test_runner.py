import json
from dataclasses import replace

import pytest

from taskforge import cli

from taskforge.diagnostics import stack_summary, truncate
from taskforge.runner import run_queue


def test_run_queue_processes_everything(store, settings):
    summary = run_queue(store, settings)
    counts = store.counts()
    assert summary.processed == 34 + summary.retried
    assert counts.get("pending", 0) == 0 and counts["succeeded"] == 27 and counts["dead"] == 7
    assert summary.dead == 7 and summary.succeeded == 27
    assert summary.diagnostics_sent == 0
    assert len(summary.diagnostics_errors) == 7  # fixture endpoint is unreachable
    assert all("ObserveError: ops-observe unreachable" in e for e in summary.diagnostics_errors)


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


@pytest.mark.parametrize('outcome', ['accepted', 'rejected', 'unreachable'])
def test_cli_failure_diagnostics(store, settings, observe_server, monkeypatch, capsys, outcome):
    observe_server.status = 422 if outcome == 'rejected' else 202
    target = settings.observe_url if outcome == 'unreachable' else observe_server.url
    settings = replace(settings, observe_url=target)
    monkeypatch.setattr(cli, 'load_settings', lambda: settings)

    result = cli.main(['run-queue'])
    summary = json.loads(capsys.readouterr().out)

    assert summary['dead'] == 7 and summary['succeeded'] == 27
    assert store.counts() == {'dead': 7, 'succeeded': 27}
    logged = [json.loads(line)['job'] for line in settings.failure_log.read_text().splitlines()]
    assert len(logged) == 7
    for record in logged:
        job = store.get(record['job_id'])
        assert record == job.to_dict()
        assert job.status == 'dead' and job.attempts == job.max_attempts
        assert job.last_error_type and job.last_traceback

    if outcome == 'accepted':
        assert result == 0
        assert summary['diagnostics_sent'] == 7 and summary['diagnostics_errors'] == []
    else:
        assert result == 3
        assert summary['diagnostics_sent'] == 0 and len(summary['diagnostics_errors']) == 7
        detail = 'rejected events (422)' if outcome == 'rejected' else 'unreachable'
        for error, record in zip(summary['diagnostics_errors'], logged):
            assert error.startswith(record['job_id'] + ': ObserveError:') and detail in error

    # Only final failures generate events, never successful jobs or retry attempts.
    assert len(observe_server.requests) == (0 if outcome == 'unreachable' else 7)
    for path, headers, body in observe_server.requests:
        assert path == '/v1/events'
        assert headers['Content-Type'] == 'application/x-ndjson'
        assert headers['X-Service'] == settings.service_name
        assert body.endswith(b'\n') and len(body.splitlines()) == 1
        event = json.loads(body)
        job = store.get(event['job_id'])
        assert event['event_type'] == 'job.failed'
        assert event['failed_at'] == job.finished_at and event['attempt'] == job.attempts
        assert event['error_type'] == job.last_error_type
        assert event['error_message'] == truncate(job.last_error_message)
        assert event['duration_ms'] == job.duration_ms
        assert event['stack_summary'] == stack_summary(job.last_traceback)
        assert event['request'] == {
            'request_id': job.context.request_id,
            'account_id': job.context.account_id,
            'route': job.context.route,
        }
