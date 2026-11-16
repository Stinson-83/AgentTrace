import pytest

from taskforge.handlers import DeliveryError, ImportValidationError, RenderError, UnknownJobType, deliver_webhook, handler_for, import_contacts, render_report
from taskforge.models import Job, RequestContext

CTX = RequestContext("req_1", "2025-11-10T08:00:00Z", "POST", "/v2/x", "203.0.113.1", "acct_test", {}, {}, "")


def _job(job_type, payload):
    return Job("job_t", job_type, "q", "running", payload, CTX, attempts=1)


def test_webhook_delivery_writes_file(settings):
    res = deliver_webhook(_job("webhook.deliver", {"url": "https://hooks.example/x?token=whk_test", "event": {"type": "a"}}), settings)
    assert res["delivered_to"] == "hooks.example" and (settings.output_dir / "webhooks" / "job_t.json").exists()


@pytest.mark.parametrize("payload", [{"url": "http://plain.example", "event": {"type": "a"}}, {"url": "https://x.invalid/y", "event": {"type": "a"}}, {"url": "https://ok.example", "event": {}}])
def test_webhook_delivery_errors(settings, payload):
    with pytest.raises(DeliveryError):
        deliver_webhook(_job("webhook.deliver", payload), settings)


def test_render_report(settings):
    res = render_report(_job("report.render", {"report": "monthly-usage", "period": "2025-10", "rows": [{"metric": "a", "value": 1}]}), settings)
    assert res["rows"] == 1 and "monthly-usage-acct_test-2025-10.csv" in res["path"]
    with pytest.raises(RenderError):
        render_report(_job("report.render", {"period": "2025/10"}), settings)


def test_import_contacts(settings):
    good = [{"name": "A", "email": "a@b.example"}]
    assert import_contacts(_job("contacts.import", {"rows": good}), settings)["imported"] == 1
    with pytest.raises(ImportValidationError):
        import_contacts(_job("contacts.import", {"rows": good + [{"email": "nope"}]}), settings)
    with pytest.raises(ImportValidationError):
        import_contacts(_job("contacts.import", {"rows": []}), settings)


def test_unknown_handler():
    with pytest.raises(UnknownJobType):
        handler_for("nope")

