from datetime import datetime, timezone

import pytest

from deskline.escalation import EscalationError, escalate, sla_report, sla_status, subject_terms
from deskline.notification import RelayError, RelayResponse


def test_subject_terms_drop_stopwords():
    assert subject_terms("Checkout timeout on bulk orders") == ["checkout", "timeout", "bulk"]


def test_sla_status_breach(db, settings, service):
    _, tenants, tickets = db
    t = tickets.get_ticket("ten_nw", 1042)
    now = datetime(2025, 11, 10, 9, 0, tzinfo=timezone.utc)
    s = sla_status(t, settings, now)
    assert s.target_hours == 8 and s.breached and 26 < s.age_hours < 28


def test_sla_report_only_open(db, settings, service):
    _, tenants, _ = db
    rows = sla_report(service, tenants.by_slug("northwind"), settings)
    assert rows and all(r["status"] in ("open", "pending", "escalated") for r in rows)
    assert any(r["number"] == 1042 and r["breached"] for r in rows)


def test_view_and_related(db, service):
    _, tenants, tickets = db
    view = service.view("ten_nw", 1042)
    assert view.customer.name == "Dev Patel" and view.latest_internal_note is not None
    related = service.related(view.ticket)
    assert related and all({"number", "subject", "status", "priority", "customer", "last_internal_note"} <= set(r) for r in related)
    assert any(r["number"] == 1018 for r in related)


class RecordingRelay:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response or RelayResponse(202, {"delivery_id": "dl_test"})
        self.error = error

    def post(self, tenant, event):
        self.calls.append((tenant, event))
        if self.error:
            raise self.error
        return self.response


def test_escalate_contract_and_saved_audit(db, settings, service):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    ticket = tickets.get_ticket(tenant.tenant_id, 1042)
    original_priority = ticket.priority
    # Warm both tenants' #1042 views; neither cached data nor the number alone
    # should be used to select the escalation context.
    foreign_view = service.view("ten_hl", 1042)
    service.view(tenant.tenant_id, 1042)
    context = tickets.add_note(ticket.ticket_id, "agent", "Latest diagnosis before escalation", "internal")
    tickets.add_note(ticket.ticket_id, "customer", "Newer public note", "public")
    before = tickets.notes_for(ticket.ticket_id)
    relay = RecordingRelay()
    post = relay.post

    def assert_saved_before_post(target, event):
        refreshed = service.view(tenant.tenant_id, 1042)
        assert refreshed.ticket.status == "escalated"
        assert refreshed.latest_internal_note.author == "alice"
        assert "SLA breached, customer chasing" in refreshed.latest_internal_note.body
        return post(target, event)

    relay.post = assert_saved_before_post
    result = escalate(service, relay, settings, tenant, 1042, "SLA breached, customer chasing", "alice")
    assert (result.tenant, result.number, result.status, result.delivered, result.delivery_id, result.error) == (
        "northwind", 1042, "escalated", True, "dl_test", None)
    target, event = relay.calls[0]
    assert target == tenant
    assert event["event"] == "ticket.escalated"
    assert event["tenant"] == "northwind" and event["actor"] == "alice"
    assert datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")).tzinfo is not None
    assert event["ticket"] == {"number": 1042, "subject": ticket.subject, "status": "escalated",
                               "priority": original_priority, "customer": "Dev Patel"}
    escalation = event["escalation"]
    assert escalation["reason"] == "SLA breached, customer chasing"
    assert escalation["latest_internal_note"] == context.body
    assert set(escalation["sla"]) == {"priority", "target_hours", "age_hours", "breached"}
    assert escalation["sla"]["priority"] == original_priority
    assert escalation["sla"]["target_hours"] == settings.sla_hours[original_priority]
    assert escalation["sla"]["breached"] is True
    assert escalation["related"] == service.related(ticket)
    assert any(r["number"] == 1018 for r in escalation["related"])
    for related in escalation["related"]:
        own = service.view(tenant.tenant_id, related["number"])
        assert related["subject"] == own.ticket.subject
        assert related["customer"] == own.customer.name
        assert related["last_internal_note"] == (own.latest_internal_note.body if own.latest_internal_note else None)
    after = tickets.notes_for(ticket.ticket_id)
    assert len(after) == len(before) + 1
    audit = after[-1]
    assert audit.visibility == "internal" and audit.author == "alice"
    assert "alice" in audit.body and escalation["reason"] in audit.body
    assert tickets.get_ticket(tenant.tenant_id, 1042).priority == original_priority
    assert tickets.by_id(foreign_view.ticket.ticket_id) == foreign_view.ticket


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_terminal_ticket_rejected_without_side_effects(db, settings, service, status):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    ticket = tickets.get_ticket(tenant.tenant_id, 1042)
    service.view(tenant.tenant_id, 1042)  # stale open view must not bypass validation
    ticket = tickets.update_status(ticket.ticket_id, status)
    notes = tickets.notes_for(ticket.ticket_id)
    relay = RecordingRelay()
    with pytest.raises(EscalationError, match=status):
        escalate(service, relay, settings, tenant, 1042, "urgent")
    assert relay.calls == []
    assert tickets.by_id(ticket.ticket_id) == ticket
    assert tickets.notes_for(ticket.ticket_id) == notes


def test_ticket_from_other_tenant_is_not_found(db, settings, service):
    _, tenants, tickets = db
    # #1055 exists only in Harbourline; do not fall back to a desk-wide lookup.
    foreign = tickets.get_ticket("ten_hl", 1055)
    notes = tickets.notes_for(foreign.ticket_id)
    relay = RecordingRelay()
    with pytest.raises(EscalationError, match="not found"):
        escalate(service, relay, settings, tenants.by_slug("northwind"), 1055, "urgent")
    assert relay.calls == []
    assert tickets.by_id(foreign.ticket_id) == foreign
    assert tickets.notes_for(foreign.ticket_id) == notes


@pytest.mark.parametrize("response,error,message", [
    (None, RelayError("relay unreachable"), "unreachable"),
    (None, RelayError("relay rejected the notification (422)"), "422"),
    (RelayResponse(503, {"error": "maintenance"}), None, "503"),
    (RelayResponse(202, {}), None, "delivery_id"),
])
def test_delivery_failure_keeps_ticket_and_surfaces_error(db, settings, service, response, error, message):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    before = service.view(tenant.tenant_id, 1042)
    relay = RecordingRelay(response, error)
    result = escalate(service, relay, settings, tenant, 1042, "urgent")
    assert result.status == "escalated" and not result.delivered
    assert result.delivery_id is None and message in result.error
    after = service.view(tenant.tenant_id, 1042)
    assert after.ticket.status == "escalated"
    assert len(after.notes) == len(before.notes) + 1
    assert after.latest_internal_note.author == "cli"
    assert relay.calls[0][1]["escalation"]["latest_internal_note"] == before.latest_internal_note.body


def test_escalate_without_internal_note(db, settings, service):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    customer = service.view(tenant.tenant_id, 1042).customer
    ticket = tickets.create_ticket(tenant.tenant_id, "Unique flibbertigibbet", "low", customer.customer_id)
    tickets.add_note(ticket.ticket_id, "customer", "Public only", "public")
    relay = RecordingRelay()
    assert escalate(service, relay, settings, tenant, ticket.number, "please review").delivered
    event = relay.calls[0][1]
    assert event["actor"] == "cli"
    assert event["escalation"]["latest_internal_note"] is None
    assert event["escalation"]["related"] == []


def test_related_filters_tenant_before_limit(db, service):
    _, _, tickets = db
    own = tickets.get_ticket("ten_nw", 1042)
    foreign = tickets.get_ticket("ten_hl", 1042)
    for _ in range(7):
        other = tickets.create_ticket(foreign.tenant_id, own.subject, "high", foreign.customer_id)
        tickets.add_note(other.ticket_id, "foreign-agent", "Other tenant confidential context", "internal")
    related = service.related(own, limit=1)
    assert len(related) == 1
    assert related[0]["number"] == 1018
    # The desk-wide support search remains desk-wide.
    assert tickets.search(subject_terms(own.subject), limit=1)[0].tenant_id == foreign.tenant_id
