import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from taskforge.diagnostics import build_failure_event, report_failure
from taskforge.handlers import DeliveryError
from taskforge.observability_client import ObserveError
from taskforge.runner import run_queue


class _Capture(BaseHTTPRequestHandler):
    batches = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"])).decode()
        _Capture.batches.append([json.loads(l) for l in raw.splitlines() if l.strip()])
        data = json.dumps({"ingested": 1}).encode()
        self.send_response(202); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture()
def observe(settings):
    _Capture.batches = []
    srv = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    from dataclasses import replace
    yield replace(settings, observe_url=f"http://127.0.0.1:{srv.server_port}"), _Capture.batches
    srv.shutdown()


def test_event_follows_contract(store, settings):
    job = store.claim_next("webhooks")
    job = store.mark_failed(job.job_id, "DeliveryError", "connection failed", 'Traceback (most recent call last):\n  File "/app/taskforge/handlers.py", line 50, in deliver_webhook\n    raise DeliveryError("x")\n', final=True)
    event = build_failure_event(job, DeliveryError("connection failed"), job.last_traceback, settings)
    assert event["event_type"] == "job.failed" and event["job_id"] == job.job_id and event["attempt"] == 1
    assert event["error_type"] == "DeliveryError" and event["stack_summary"][-1]["function"] == "deliver_webhook"
    assert event["error_message"] == "connection failed"
    assert set(event["request"]) == {"request_id", "account_id", "route", "params"}
    assert set(event["request"]["params"]) <= {"source", "format", "report"} and "api_key" not in event["request"]["params"]
    assert event["request"]["request_id"] == job.context.request_id


def test_report_failure_sends_and_returns(store, observe):
    settings, batches = observe
    job = store.claim_next("webhooks")
    job = store.mark_failed(job.job_id, "DeliveryError", "boom", "Traceback...", final=True)
    event = report_failure(job, DeliveryError("boom"), "Traceback...", settings)
    assert batches and batches[0][0]["job_id"] == job.job_id == event["job_id"]


def test_run_queue_counts_sent_events(store, observe):
    settings, batches = observe
    summary = run_queue(store, settings)
    assert summary.dead == 7 and summary.diagnostics_sent == 7 and summary.diagnostics_errors == []
    assert sorted(e["job_id"] for b in batches for e in b) == sorted(j.job_id for j in store.list(status="dead"))


def test_unreachable_observe_is_reported(store, settings):
    summary = run_queue(store, settings)  # settings.observe_url points at a closed port
    assert summary.dead == 7 and summary.diagnostics_sent == 0 and len(summary.diagnostics_errors) == 7
    with pytest.raises(ObserveError):
        report_failure(store.list(status="dead")[0], DeliveryError("x"), "tb", settings)


def test_handler_messages_carry_no_request_material(settings):
    from taskforge.handlers import DeliveryError, ImportValidationError, deliver_webhook, import_contacts
    from taskforge.models import Job, RequestContext
    ctx = RequestContext("req_1", "2025-11-10T08:00:00Z", "POST", "/v2/x", "203.0.113.1", "acct_test", {}, {}, "")
    with pytest.raises(DeliveryError) as e:
        deliver_webhook(Job("j", "webhook.deliver", "q", "running", {"url": "https://x.invalid/y?token=whk_secret", "event": {"type": "a"}}, ctx, attempts=1), settings)
    assert "whk_secret" not in str(e.value)
    with pytest.raises(ImportValidationError) as e:
        import_contacts(Job("j", "contacts.import", "q", "running", {"rows": [{"name": "A", "email": "a at b", "phone": "1"}]}, ctx, attempts=1), settings)
    assert "a at b" not in str(e.value)
