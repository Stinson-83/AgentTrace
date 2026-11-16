from datetime import datetime, timezone

import pytest

from deskline.escalation import EscalationError, escalate, sla_status
from deskline.notification import RelayError, RelayResponse
from deskline.ticket_store import TicketStore, open_connection


class RecordingRelay:
    def __init__(self, response=None, error=None):
        self.response = response or RelayResponse(202, {"delivery_id": "dl_test"})
        self.error = error
        self.calls = []

    def post(self, tenant, event):
        self.calls.append((tenant, event))
        if self.error:
            raise self.error
        return self.response


def test_escalation_event_and_persisted_audit(db, service, settings):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    before = service.view(tenant.tenant_id, 1042)
    other = tickets.get_ticket("ten_hl", 1042)
    other_notes = tickets.notes_for(other.ticket_id)
    relay = RecordingRelay()
    result = escalate(service, relay, settings, tenant, 1042, "SLA breached, customer chasing", "Alex")

    assert (result.tenant, result.number, result.status, result.delivered, result.delivery_id, result.error) == (
        "northwind", 1042, "escalated", True, "dl_test", None)
    target, event = relay.calls[0]
    assert target == tenant
    assert event["event"] == "ticket.escalated" and event["tenant"] == "northwind"
    assert event["actor"] == "Alex"
    occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    assert occurred.tzinfo == timezone.utc
    assert event["ticket"] == {
        "number": 1042, "subject": before.ticket.subject, "status": "escalated",
        "priority": "high", "customer": "Dev Patel",
    }
    context = event["escalation"]
    assert context["reason"] == "SLA breached, customer chasing"
    assert context["latest_internal_note"] == before.latest_internal_note.body
    assert context["sla"] == sla_status(before.ticket, settings, occurred).as_dict()
    assert context["related"] == service.related(before.ticket)
    assert any(r["number"] == 1018 for r in context["related"])
    after = service.view(tenant.tenant_id, 1042)
    assert after.ticket.status == "escalated"
    assert len(after.notes) == len(before.notes) + 1
    assert after.latest_internal_note.author == "Alex"
    assert after.latest_internal_note.visibility == "internal"
    assert "Alex" in after.latest_internal_note.body and context["reason"] in after.latest_internal_note.body
    assert tickets.by_id(other.ticket_id) == other
    assert tickets.notes_for(other.ticket_id) == other_notes
    # The status and audit note have been committed, not just changed in cache.
    conn = open_connection(settings.db_path)
    try:
        persisted = TicketStore(conn)
        assert persisted.get_ticket(tenant.tenant_id, 1042).status == "escalated"
        assert persisted.notes_for(before.ticket.ticket_id)[-1] == after.latest_internal_note
    finally:
        conn.close()


def test_latest_note_snapshot_ignores_stale_cache_and_new_public_note(db, service, settings):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    view = service.view(tenant.tenant_id, 1042)
    tickets.add_note(view.ticket.ticket_id, "agent", "Fresh internal context")
    tickets.add_note(view.ticket.ticket_id, "customer", "Public follow-up", "public")
    relay = RecordingRelay()
    escalate(service, relay, settings, tenant, 1042, "Need help")
    assert relay.calls[0][1]["escalation"]["latest_internal_note"] == "Fresh internal context"
    assert relay.calls[0][1]["actor"] == "cli"


@pytest.mark.parametrize("public_note", [False, True])
def test_escalation_without_internal_notes(db, service, settings, public_note):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    customer_id = tickets.get_ticket(tenant.tenant_id, 1042).customer_id
    ticket = tickets.create_ticket(tenant.tenant_id, "Unique new issue", "normal", customer_id)
    if public_note:
        tickets.add_note(ticket.ticket_id, "customer", "Not internal", "public")
    relay = RecordingRelay()
    result = escalate(service, relay, settings, tenant, ticket.number, "Please investigate")
    assert result.delivered
    assert relay.calls[0][1]["escalation"]["latest_internal_note"] is None
    assert relay.calls[0][1]["escalation"]["related"] == []


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_terminal_ticket_is_rejected_even_with_stale_open_view(db, service, settings, status):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    view = service.view(tenant.tenant_id, 1042)
    before_notes = tickets.notes_for(view.ticket.ticket_id)
    tickets.update_status(view.ticket.ticket_id, status)
    relay = RecordingRelay()
    with pytest.raises(EscalationError, match=status):
        escalate(service, relay, settings, tenant, 1042, "No")
    assert not relay.calls
    assert tickets.by_id(view.ticket.ticket_id).status == status
    assert tickets.notes_for(view.ticket.ticket_id) == before_notes


@pytest.mark.parametrize("number", [1055, 999999])
def test_ticket_not_in_tenant_is_rejected(db, service, settings, number):
    conn, tenants, _ = db
    tenant = tenants.by_slug("northwind")
    before = list(conn.iterdump())
    relay = RecordingRelay()
    with pytest.raises(EscalationError, match="not found"):
        escalate(service, relay, settings, tenant, number, "No")
    assert list(conn.iterdump()) == before
    assert not relay.calls


@pytest.mark.parametrize("relay", [
    RecordingRelay(error=RelayError("relay rejected the notification (422)")),
    RecordingRelay(error=RelayError("relay unreachable")),
    RecordingRelay(response=RelayResponse(503, {"error": "unavailable"})),
    RecordingRelay(response=RelayResponse(202, {})),
])
def test_delivery_failure_preserves_update_and_exposes_error(db, service, settings, relay):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    result = escalate(service, relay, settings, tenant, 1042, "Still record this")
    assert not result.delivered and result.delivery_id is None and result.error
    assert result.status == "escalated"
    after = service.view(tenant.tenant_id, 1042)
    assert after.ticket.status == "escalated"
    assert "Still record this" in after.latest_internal_note.body


def test_related_is_tenant_scoped_before_limit(db, service, settings):
    _, tenants, tickets = db
    source = tickets.get_ticket("ten_nw", 1042)
    # Newer foreign matches must not displace the tenant's real related records.
    foreign_customer = tickets.get_ticket("ten_hl", 1042).customer_id
    for i in range(7):
        foreign = tickets.create_ticket("ten_hl", source.subject, "urgent", foreign_customer)
        tickets.add_note(foreign.ticket_id, "private", f"Foreign private context {i}")
    expected = tickets.search(["checkout", "timeout", "bulk"], tenant_id="ten_nw", exclude_ticket_id=source.ticket_id, limit=2)
    related = service.related(source, limit=2)
    assert related and [r["number"] for r in related] == [t.number for t in expected]
    for row, ticket in zip(related, expected):
        view = service.view("ten_nw", ticket.number)
        assert row["customer"] == view.customer.name
        assert row["last_internal_note"] == (view.latest_internal_note.body if view.latest_internal_note else None)
    relay = RecordingRelay()
    escalate(service, relay, settings, tenants.by_slug("northwind"), 1042, "Check duplicates")
    assert "Foreign private context" not in str(relay.calls)
    # Desk-wide search is still available to deskline support engineers.
    assert any(t.tenant_id == "ten_hl" for t in tickets.search(["checkout", "timeout", "bulk"]))
