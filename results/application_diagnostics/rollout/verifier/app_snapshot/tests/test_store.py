import pytest

from taskforge.models import RequestContext


def test_seed_loads(store):
    assert store.counts() == {"pending": 34}
    job = store.get("job_0001")
    assert job.status == "pending" and job.attempts == 0 and job.context.account_id.startswith("acct_")


def test_claim_order_and_attempts(store):
    first = store.claim_next()
    assert first is not None and first.status == "running" and first.attempts == 1
    assert store.claim_next("imports").queue == "imports"


def test_mark_failed_retry_vs_dead(store):
    job = store.claim_next()
    j = store.mark_failed(job.job_id, "DeliveryError", "boom", "Traceback...", final=False)
    assert j.status == "pending" and j.last_error_type == "DeliveryError"
    j = store.mark_failed(job.job_id, "DeliveryError", "boom", "Traceback...", final=True)
    assert j.status == "dead"


def test_enqueue_roundtrip(store):
    ctx = RequestContext("req_x", "2025-11-10T08:00:00Z", "POST", "/v2/x", "203.0.113.1", "acct_test", {"user-agent": "t"}, {}, "{}")
    job = store.enqueue("job_new", "report.render", "reports", {"period": "2025-10", "rows": []}, ctx)
    assert job.context == ctx and job.to_dict()["context"]["route"] == "/v2/x"
    with pytest.raises(KeyError):
        store.get("job_missing")


def test_requeue_dead_job(store):
    job = store.claim_next()
    store.mark_failed(job.job_id, "DeliveryError", "boom", "tb", final=True)
    again = store.requeue(job.job_id)
    assert again.status == "pending" and again.attempts == 0 and again.finished_at is None
    with pytest.raises(ValueError):
        store.requeue(store.claim_next().job_id)
