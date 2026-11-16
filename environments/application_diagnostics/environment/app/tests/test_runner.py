import json

from taskforge.diagnostics import stack_summary, truncate
from taskforge.runner import run_queue


def test_run_queue_processes_everything(store, settings):
    summary = run_queue(store, settings)
    counts = store.counts()
    assert summary.processed == 34 + summary.retried
    assert counts.get("pending", 0) == 0 and counts["succeeded"] == 27 and counts["dead"] == 7
    assert summary.dead == 7 and summary.succeeded == 27
    assert len(summary.diagnostics_errors) == 7  # diagnostics not wired yet


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
