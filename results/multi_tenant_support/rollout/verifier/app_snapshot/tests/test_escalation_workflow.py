from datetime import datetime
from unittest.mock import Mock

import pytest

from deskline.escalation import EscalationError, escalate, sla_status
from deskline.notification import RelayError, RelayResponse
from deskline.ticket_store import TicketStore, open_connection


@pytest.fixture
def relay():
    return Mock(post=Mock(return_value=RelayResponse(202, {"delivery_id": "dl_test"})))


def test_escalate_event_and_persisted_update(db, service, settings, relay):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    before = service.view(tenant.tenant_id, 1042)
    # A previously cached view must not hide new context.
    context = tickets.add_note(before.ticket.ticket_id, "agent", "Latest investigation: café checkout")
    tickets.add_note(before.ticket.ticket_id, "customer", "A newer public note", "public")
    duplicate = tickets.get_ticket(tenant.tenant_id, 1018)
    tickets.add_note(duplicate.ticket_id, "agent", "Possible duplicate investigation")
    other_tenant = tickets.get_ticket("ten_hl", 1042)
    other_notes = tickets.notes_for(other_tenant.ticket_id)

    def deliver(destination, event):
        # The write must have committed before making an external request.
        conn = open_connection(settings.db_path)
        try:
            persisted = TicketStore(conn)
            assert persisted.get_ticket(tenant.tenant_id, 1042).status == "escalated"
            note = persisted.notes_for(before.ticket.ticket_id)[-1]
            assert note.visibility == "internal" and note.author == "oncall.agent"
            assert "oncall.agent" in note.body and "SLA breached, customer chasing" in note.body
        finally:
            conn.close()
        return RelayResponse(202, {"delivery_id": "dl_test"})

    relay.post.side_effect = deliver
    result = escalate(service, relay, settings, tenant, 1042,
                      "SLA breached, customer chasing", actor="oncall.agent")
    assert (result.tenant, result.number, result.status) == ("northwind", 1042, "escalated")
    assert result.delivered and result.delivery_id == "dl_test" and result.error is None
    relay.post.assert_called_once()
    destination, event = relay.post.call_args.args
    assert destination == tenant
    assert event["event"] == "ticket.escalated" and event["tenant"] == tenant.slug
    assert event["actor"] == "oncall.agent"
    occurred = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    assert occurred.utcoffset().total_seconds() == 0
    assert event["ticket"] == {
        "number": 1042, "subject": before.ticket.subject, "status": "escalated",
        "priority": "high", "customer": before.customer.name,
    }
    escalation = event["escalation"]
    assert escalation["reason"] == "SLA breached, customer chasing"
    assert escalation["latest_internal_note"] == context.body
    assert escalation["sla"] == sla_status(before.ticket, settings, occurred).as_dict()
    assert escalation["sla"]["breached"]
    related = escalation["related"]
    assert related and all(r["tenant"] == "northwind" for r in related)
    duplicate = next(r for r in related if r["number"] == 1018)
    duplicate_view = service.view(tenant.tenant_id, 1018)
    assert duplicate["customer"] == duplicate_view.customer.name
    assert duplicate["last_internal_note"] == duplicate_view.latest_internal_note.body
    # Neither overlapping ticket numbers nor similar subjects may cross tenants.
    assert tickets.get_ticket("ten_hl", 1042) == other_tenant
    assert tickets.notes_for(other_tenant.ticket_id) == other_notes
    after = service.view(tenant.tenant_id, 1042)
    assert after.ticket.status == "escalated"
    assert after.latest_internal_note.author == "oncall.agent"
    assert len(after.notes) == len(before.notes) + 3


def test_escalate_without_internal_context(db, service, settings, relay):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    ticket = tickets.create_ticket(tenant.tenant_id, "Unique new issue", "low", "cst_0005")
    tickets.add_note(ticket.ticket_id, "customer", "Public context only", "public")
    result = escalate(service, relay, settings, tenant, ticket.number, "Needs attention")
    event = relay.post.call_args.args[1]
    assert result.delivered and event["actor"] == "cli"
    assert event["escalation"]["latest_internal_note"] is None
    assert event["escalation"]["related"] == []
    assert service.view(tenant.tenant_id, ticket.number).latest_internal_note.author == "cli"


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_cannot_escalate_finished_ticket_even_if_cached(db, service, settings, relay, status):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    cached = service.view(tenant.tenant_id, 1042)
    ticket = tickets.update_status(cached.ticket.ticket_id, status)
    notes = tickets.notes_for(ticket.ticket_id)
    with pytest.raises(EscalationError, match=status):
        escalate(service, relay, settings, tenant, 1042, "Too late")
    relay.post.assert_not_called()
    assert tickets.get_ticket(tenant.tenant_id, 1042) == ticket
    assert tickets.notes_for(ticket.ticket_id) == notes


def test_unknown_or_other_tenants_ticket_is_not_escalated(db, service, settings, relay):
    _, tenants, tickets = db
    foreign = tickets.create_ticket("ten_hl", "Private ticket", "high", "cst_0001")
    notes = tickets.notes_for(foreign.ticket_id)
    with pytest.raises(EscalationError, match="not found"):
        escalate(service, relay, settings, tenants.by_slug("northwind"), foreign.number, "Wrong tenant")
    with pytest.raises(EscalationError, match="not found"):
        escalate(service, relay, settings, tenants.by_slug("northwind"), 999999, "Missing")
    relay.post.assert_not_called()
    assert tickets.by_id(foreign.ticket_id) == foreign
    assert tickets.notes_for(foreign.ticket_id) == notes


@pytest.mark.parametrize("error", ["relay rejected the notification (422)", "relay unreachable: connection refused"])
def test_delivery_failure_keeps_update_and_surfaces_error(db, service, settings, relay, error):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    before = service.view(tenant.tenant_id, 1042)
    relay.post.side_effect = RelayError(error)
    result = escalate(service, relay, settings, tenant, 1042, "Please investigate")
    assert not result.delivered and result.delivery_id is None and result.error == error
    assert result.status == "escalated"
    after = service.view(tenant.tenant_id, 1042)
    assert after.ticket.status == "escalated" and len(after.notes) == len(before.notes) + 1
    assert "Please investigate" in after.latest_internal_note.body


@pytest.mark.parametrize("response", [RelayResponse(422, {"error": "rejected"}), RelayResponse(202, {})])
def test_unaccepted_response_is_failed_delivery(db, service, settings, relay, response):
    relay.post.return_value = response
    result = escalate(service, relay, settings, db[1].by_slug("northwind"), 1042, "Investigate")
    assert not result.delivered and result.error and result.delivery_id is None
    assert service.view("ten_nw", 1042).ticket.status == "escalated"


def test_related_scopes_before_limit_but_desk_search_stays_global(db, service):
    _, _, tickets = db
    source = tickets.get_ticket("ten_nw", 1042)
    for _ in range(7):
        tickets.create_ticket("ten_hl", source.subject, "high", "cst_0001")
    global_matches = tickets.search(["checkout", "timeout", "bulk"])
    assert any(t.tenant_id == "ten_hl" for t in global_matches)
    related = service.related(source, limit=1)
    assert len(related) == 1
    assert related[0]["tenant"] == "northwind" and related[0]["number"] == 1018
