import copy
from datetime import datetime, timezone

import pytest

from deskline.escalation import EscalationError, escalate, escalation_queue, sla_report, sla_status, subject_terms
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


def test_escalation_queue_is_desk_wide_and_recent_first(db, settings, service):
    now = datetime(2025, 11, 10, 9, 0, tzinfo=timezone.utc)
    queue = escalation_queue(service, settings, now=now, limit=10)
    assert queue and len({r["tenant"] for r in queue}) >= 2
    assert all(queue[i]["updated_at"] >= queue[i + 1]["updated_at"] for i in range(len(queue) - 1))
    assert any(r["tenant"] == "harbourline" and r["number"] == 1042 for r in queue)


class RecordingRelay:
    def __init__(self, hook_error=None, channel_error=None):
        self.hook_error = hook_error
        self.channel_error = channel_error
        self.calls = []

    def post(self, tenant, event):
        self.calls.append((tenant.escalation_hook, copy.deepcopy(event)))
        if self.hook_error:
            raise RelayError(self.hook_error)
        return RelayResponse(202, {"delivery_id": "hook-123"})

    def post_channel(self, channel, event):
        self.calls.append((channel, copy.deepcopy(event)))
        if self.channel_error:
            raise RelayError(self.channel_error)
        return RelayResponse(202, {"delivery_id": "channel-456"})


def test_escalate_records_update_and_snapshot(db, settings, service):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    before = service.view(tenant.tenant_id, 1042)  # prime the view cache
    other_before = tickets.get_ticket("ten_hl", 1042)
    queue_before = escalation_queue(service, settings)
    # A note added after caching must be included; a newer public note must not be.
    tickets.add_note(before.ticket.ticket_id, "agent", "Fresh investigation context")
    tickets.add_note(before.ticket.ticket_id, "customer", "Any news?", "public")
    relay = RecordingRelay()
    result = escalate(service, relay, settings, tenant, 1042, "Customer chasing", "alice")

    assert (result.tenant, result.number, result.status) == ("northwind", 1042, "escalated")
    assert result.delivered and result.oncall_delivered and result.delivery_id == "hook-123"
    after = service.view(tenant.tenant_id, 1042)
    assert after.ticket.status == "escalated"
    assert len(after.notes) == len(before.notes) + 3
    assert after.latest_internal_note.author == "alice"
    assert after.latest_internal_note.visibility == "internal"
    assert "alice" in after.latest_internal_note.body and "Customer chasing" in after.latest_internal_note.body
    assert tickets.get_ticket("ten_hl", 1042) == other_before

    assert [path for path, _ in relay.calls] == [tenant.escalation_hook, settings.oncall_channel]
    hook, oncall = [event for _, event in relay.calls]
    for event in (hook, oncall):
        assert event["event"] == "ticket.escalated"
        assert event["tenant"] == "northwind" and event["actor"] == "alice"
        assert event["occurred_at"].endswith("Z")
        assert event["ticket"] == {"number": 1042, "subject": before.ticket.subject,
                                   "status": "escalated", "priority": "high", "customer": "Dev Patel"}
        context = event["escalation"]
        assert context["reason"] == "Customer chasing"
        assert context["latest_internal_note"] == "Fresh investigation context"
        assert context["sla"]["breached"] and context["sla"]["target_hours"] == 8
        assert context["sla"]["priority"] == "high" and context["sla"]["age_hours"] > 8
        assert not any(r["tenant"] == "northwind" and r["number"] == 1042 for r in context["queue"])
    assert hook["occurred_at"] == oncall["occurred_at"]
    assert oncall["escalation"]["related"] == service.related(before.ticket)
    assert [(r["tenant"], r["number"]) for r in oncall["escalation"]["queue"]] == [(r["tenant"], r["number"]) for r in queue_before]
    assert any(r["tenant"] == "harbourline" and r["number"] == 1042 for r in oncall["escalation"]["queue"])
    assert all(r["tenant"] == "northwind" for r in hook["escalation"]["queue"])


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_escalate_terminal_ticket_does_not_mutate_or_post(db, settings, service, status):
    _, tenants, tickets = db
    ticket = tickets.get_ticket("ten_nw", 1042)
    service.view("ten_nw", 1042)  # validation must not trust a stale cached status
    tickets.update_status(ticket.ticket_id, status)
    before = tickets.by_id(ticket.ticket_id)
    notes = tickets.notes_for(ticket.ticket_id)
    relay = RecordingRelay()
    with pytest.raises(EscalationError, match=status) as caught:
        escalate(service, relay, settings, tenants.by_slug("northwind"), 1042, "test")
    assert caught.value.result is None
    assert not relay.calls
    assert tickets.by_id(ticket.ticket_id) == before
    assert tickets.notes_for(ticket.ticket_id) == notes


@pytest.mark.parametrize("number", [9999, 1055])  # 1055 exists only at Harbourline
def test_escalate_unknown_or_other_tenant_ticket(db, settings, service, number):
    conn, tenants, _ = db
    relay = RecordingRelay()
    before = conn.total_changes
    with pytest.raises(EscalationError, match="not found"):
        escalate(service, relay, settings, tenants.by_slug("northwind"), number, "test")
    assert conn.total_changes == before
    assert not relay.calls


@pytest.mark.parametrize("hook_error,channel_error", [
    ("relay rejected the notification (422)", None),
    (None, "relay unreachable"),
    ("relay unreachable", "relay unreachable"),
])
def test_escalation_delivery_failures_preserve_update_and_attempt_both(db, settings, service, hook_error, channel_error):
    _, tenants, tickets = db
    relay = RecordingRelay(hook_error, channel_error)
    with pytest.raises(EscalationError) as caught:
        escalate(service, relay, settings, tenants.by_slug("northwind"), 1042, "Urgent")
    result = caught.value.result
    assert result.status == "escalated"
    assert result.delivered == (hook_error is None)
    assert result.oncall_delivered == (channel_error is None)
    assert result.delivery_id == ("hook-123" if hook_error is None else None)
    assert len(relay.calls) == 2
    for destination, error in (("tenant hook", hook_error), ("on-call channel", channel_error)):
        if error:
            assert destination in str(caught.value) and error in str(caught.value)
    view = service.view("ten_nw", 1042)
    assert view.ticket.status == tickets.get_ticket("ten_nw", 1042).status == "escalated"
    assert view.latest_internal_note.author == "cli"
    assert "Urgent" in view.latest_internal_note.body


def test_escalate_without_internal_note(db, settings, service):
    _, tenants, tickets = db
    customer = service.view("ten_nw", 1042).customer
    ticket = tickets.create_ticket("ten_nw", "Entirely new issue", "normal", customer.customer_id)
    relay = RecordingRelay()
    escalate(service, relay, settings, tenants.by_slug("northwind"), ticket.number, "Help")
    assert all(event["escalation"]["latest_internal_note"] is None for _, event in relay.calls)


def test_hook_context_scoped_before_limit_and_never_leaks(db, settings, service):
    conn, tenants, tickets = db
    nw = service.view("ten_nw", 1042)
    hl = service.view("ten_hl", 1042)
    own = tickets.create_ticket("ten_nw", nw.ticket.subject, "normal", nw.customer.customer_id)
    tickets.add_note(own.ticket_id, "agent", "OWN related context")
    tickets.update_status(own.ticket_id, "escalated")
    foreign_ids = []
    for i in range(6):
        other = tickets.create_ticket("ten_hl", nw.ticket.subject, "urgent", hl.customer.customer_id)
        tickets.add_note(other.ticket_id, "other", f"FOREIGN SECRET {i}")
        tickets.update_status(other.ticket_id, "escalated")
        foreign_ids.append(other.ticket_id)
    with conn:
        conn.executemany("UPDATE tickets SET created_at = ?, updated_at = ? WHERE ticket_id = ?",
                         [("2090-01-01T00:00:00Z", "2090-01-01T00:00:00Z", tid) for tid in foreign_ids])
    service.cache.clear()
    relay = RecordingRelay()
    escalate(service, relay, settings, tenants.by_slug("northwind"), 1042, "Help")
    hook, oncall = [event for _, event in relay.calls]
    assert "FOREIGN SECRET" not in str(hook)
    assert "FOREIGN SECRET" in str(oncall)
    assert any(r["number"] == own.number and r["last_internal_note"] == "OWN related context" for r in hook["escalation"]["related"])
    assert any(r["number"] == own.number for r in hook["escalation"]["queue"])
    assert all(r["tenant"] == "northwind" for r in hook["escalation"]["queue"])
    assert len(oncall["escalation"]["related"]) == len(oncall["escalation"]["queue"]) == 5


def test_unexpected_relay_status_is_failure(db, settings, service):
    from unittest.mock import Mock
    relay = Mock()
    relay.post.return_value = RelayResponse(500, {})
    relay.post_channel.return_value = RelayResponse(202, {"delivery_id": "channel"})
    with pytest.raises(EscalationError, match="500") as caught:
        escalate(service, relay, settings, db[1].by_slug("northwind"), 1042, "Help")
    assert not caught.value.result.delivered and caught.value.result.oncall_delivered


@pytest.mark.parametrize("status", ["open", "pending", "escalated"])
def test_escalate_active_status_with_configured_channel(db, settings, service, status):
    from dataclasses import replace

    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    ticket = tickets.get_ticket(tenant.tenant_id, 1042)
    tickets.update_status(ticket.ticket_id, status)
    relay = RecordingRelay()
    result = escalate(service, relay, replace(settings, oncall_channel="/channels/rota"), tenant, 1042, "Help")
    assert result.delivered and result.oncall_delivered
    assert relay.calls[1][0] == "/channels/rota"
    assert tickets.by_id(ticket.ticket_id).priority == ticket.priority
    context = relay.calls[1][1]["escalation"]
    if status == "escalated":
        row = next(r for r in context["queue"] if r["tenant"] == "northwind" and r["number"] == 1042)
        assert row["latest_internal_note"] == context["latest_internal_note"]
