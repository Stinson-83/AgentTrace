from copy import deepcopy
from datetime import datetime

import pytest

from deskline import cli
from deskline.escalation import EscalationError, escalate, escalation_queue, sla_status
from deskline.notification import RelayError, RelayResponse


class RecordingRelay:
    def __init__(self, hook_error=None, oncall_error=None, hook_status=202, oncall_status=202):
        self.hook_error = hook_error
        self.oncall_error = oncall_error
        self.hook_status = hook_status
        self.oncall_status = oncall_status
        self.hooks = []
        self.channels = []

    def post(self, tenant, event):
        self.hooks.append((tenant, deepcopy(event)))
        if self.hook_error:
            raise RelayError(self.hook_error)
        return RelayResponse(self.hook_status, {"delivery_id": "hook-123"})

    def post_channel(self, channel, event):
        self.channels.append((channel, deepcopy(event)))
        if self.oncall_error:
            raise RelayError(self.oncall_error)
        return RelayResponse(self.oncall_status, {"delivery_id": "channel-456"})


def test_escalate_context_and_updates(db, settings, service):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    view = service.view(tenant.tenant_id, 1042)  # warm the cache
    other_ticket = tickets.get_ticket("ten_hl", 1042)
    notes = tickets.notes_for(view.ticket.ticket_id)
    relay = RecordingRelay()
    result = escalate(service, relay, settings, tenant, 1042, "Customer chasing", actor="alex")

    assert (result.tenant, result.number, result.status) == ("northwind", 1042, "escalated")
    assert result.delivered and result.oncall_delivered and result.delivery_id == "hook-123"
    assert result.hook_error is None and result.oncall_error is None
    assert relay.hooks[0][0] == tenant
    assert relay.channels[0][0] == settings.oncall_channel
    hook, channel = relay.hooks[0][1], relay.channels[0][1]
    for event in (hook, channel):
        assert event["event"] == "ticket.escalated" and event["tenant"] == "northwind"
        assert event["actor"] == "alex"
        now = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        assert now.utcoffset().total_seconds() == 0
        assert event["ticket"] == {"number": 1042, "subject": view.ticket.subject,
                                   "status": "escalated", "priority": "high", "customer": "Dev Patel"}
        context = event["escalation"]
        assert context["reason"] == "Customer chasing"
        assert context["latest_internal_note"] == view.latest_internal_note.body
        expected_sla = sla_status(view.ticket, settings, now).as_dict()
        assert context["sla"] == {**expected_sla, "age_hours": pytest.approx(expected_sla["age_hours"], abs=0.01)}
        assert all({"number", "subject", "status", "priority", "customer", "last_internal_note"} <= r.keys()
                   for r in context["related"])
        assert not any(r["tenant"] == "northwind" and r["number"] == 1042 for r in context["queue"])
    assert channel["escalation"]["related"] == service.related(view.ticket)
    assert any(r["tenant"] == "harbourline" and r["number"] == 1042 for r in channel["escalation"]["queue"])
    assert all(r["tenant"] == "northwind" for r in hook["escalation"]["queue"])
    assert hook["escalation"]["related"] == service.related(view.ticket, tenant_id=tenant.tenant_id)
    assert any(r["number"] == 1018 for r in hook["escalation"]["related"])

    refreshed = service.view(tenant.tenant_id, 1042)
    assert refreshed.ticket.status == "escalated"
    added = tickets.notes_for(view.ticket.ticket_id)[len(notes):]
    assert len(added) == 1 and added[0].visibility == "internal" and added[0].author == "alex"
    assert "alex" in added[0].body and "Customer chasing" in added[0].body
    assert refreshed.latest_internal_note == added[0]
    assert tickets.get_ticket("ten_hl", 1042) == other_ticket
    # The status and note are committed, not only visible in the workflow's connection.
    from deskline.ticket_store import TicketStore, open_connection
    with open_connection(settings.db_path) as second:
        assert TicketStore(second).get_ticket(tenant.tenant_id, 1042).status == "escalated"
        assert TicketStore(second).notes_for(view.ticket.ticket_id)[-1] == added[0]


def test_latest_note_is_fresh_internal_context(db, settings, service):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    view = service.view(tenant.tenant_id, 1042)
    tickets.add_note(view.ticket.ticket_id, "engineer", "Fresh internal context")
    tickets.add_note(view.ticket.ticket_id, "customer", "Newer public reply", "public")
    relay = RecordingRelay()
    escalate(service, relay, settings, tenant, 1042, "Investigate")
    assert relay.hooks[0][1]["escalation"]["latest_internal_note"] == "Fresh internal context"


def test_no_internal_note(db, settings, service):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    ticket = tickets.create_ticket(tenant.tenant_id, "A unique incident", "low", "cst_0004")
    relay = RecordingRelay()
    escalate(service, relay, settings, tenant, ticket.number, "Needs review")
    assert relay.hooks[0][1]["escalation"]["latest_internal_note"] is None
    assert relay.hooks[0][1]["actor"] == "cli"


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_terminal_ticket_rejected_even_with_stale_view(db, settings, service, status):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    view = service.view(tenant.tenant_id, 1042)
    before = tickets.update_status(view.ticket.ticket_id, status)
    notes = tickets.notes_for(before.ticket_id)
    relay = RecordingRelay()
    with pytest.raises(EscalationError, match=status):
        escalate(service, relay, settings, tenant, 1042, "Not allowed")
    assert tickets.get_ticket(tenant.tenant_id, 1042) == before
    assert tickets.notes_for(before.ticket_id) == notes
    assert not relay.hooks and not relay.channels


@pytest.mark.parametrize("number", [1055, 99999])
def test_wrong_tenant_or_unknown_ticket_has_no_side_effects(db, settings, service, number):
    conn, tenants, _ = db
    before = conn.total_changes
    relay = RecordingRelay()
    with pytest.raises(EscalationError, match="not found"):
        escalate(service, relay, settings, tenants.by_slug("northwind"), number, "No")
    assert conn.total_changes == before
    assert not relay.hooks and not relay.channels


@pytest.mark.parametrize("status", ["open", "pending", "escalated"])
def test_active_statuses_can_be_escalated(db, settings, service, status):
    _, tenants, tickets = db
    ticket = tickets.get_ticket("ten_nw", 1042)
    tickets.update_status(ticket.ticket_id, status)
    assert escalate(service, RecordingRelay(), settings, tenants.by_slug("northwind"), 1042, "Review").delivered


@pytest.mark.parametrize("hook_fails,oncall_fails", [(True, False), (False, True), (True, True)])
def test_delivery_errors_are_returned_and_updates_stand(db, settings, service, hook_fails, oncall_fails):
    _, tenants, tickets = db
    relay = RecordingRelay("hook unreachable" if hook_fails else None,
                           "channel rejected (422)" if oncall_fails else None)
    result = escalate(service, relay, settings, tenants.by_slug("northwind"), 1042, "Review")
    assert result.delivered == (not hook_fails)
    assert result.oncall_delivered == (not oncall_fails)
    assert result.delivery_id == (None if hook_fails else "hook-123")
    assert result.hook_error == relay.hook_error and result.oncall_error == relay.oncall_error
    assert len(relay.hooks) == len(relay.channels) == 1
    assert service.view("ten_nw", 1042).ticket.status == "escalated"
    assert "Review" in service.view("ten_nw", 1042).latest_internal_note.body


def test_nonaccepted_responses_are_failures(db, settings, service):
    _, tenants, _ = db
    relay = RecordingRelay(hook_status=422, oncall_status=503)
    result = escalate(service, relay, settings, tenants.by_slug("northwind"), 1042, "Review")
    assert not result.delivered and not result.oncall_delivered and result.delivery_id is None
    assert "422" in result.hook_error and "503" in result.oncall_error


def test_tenant_scoping_happens_before_limits(db, settings, service):
    _, tenants, tickets = db
    tenant = tenants.by_slug("northwind")
    source = tickets.get_ticket(tenant.tenant_id, 1042)
    own = tickets.create_ticket(tenant.tenant_id, source.subject, "normal", source.customer_id)
    tickets.add_note(own.ticket_id, "agent", "Our tenant context")
    tickets.update_status(own.ticket_id, "escalated")
    for _ in range(7):
        ticket = tickets.create_ticket("ten_hl", source.subject, "high", "cst_0001")
        tickets.add_note(ticket.ticket_id, "agent", "FOREIGN PRIVATE CONTEXT")
        tickets.update_status(ticket.ticket_id, "escalated")
    relay = RecordingRelay()
    escalate(service, relay, settings, tenant, 1042, "Review")
    hook_context = relay.hooks[0][1]["escalation"]
    assert any(r["number"] == own.number for r in hook_context["related"])
    assert any(r["number"] == own.number for r in hook_context["queue"])
    assert all(r["tenant"] == "northwind" for r in hook_context["queue"])
    assert "FOREIGN PRIVATE CONTEXT" not in str(relay.hooks)
    assert "FOREIGN PRIVATE CONTEXT" in str(relay.channels)
    assert len(escalation_queue(service, settings, tenant_id=tenant.tenant_id, limit=1)) == 1


@pytest.fixture
def cli_setup(db, settings, monkeypatch):
    relay = RecordingRelay()
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "NotificationRelayClient", lambda *args: relay)
    return relay


@pytest.mark.parametrize("actor", [None, "jordan"])
def test_cli_success(cli_setup, capsys, actor):
    args = ["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Customer chasing"]
    if actor:
        args += ["--actor", actor]
    assert cli.main(args) == 0
    out = capsys.readouterr()
    assert "northwind #1042: escalated" in out.out and "hook-123" in out.out
    assert "on-call=delivered" in out.out and not out.err
    assert cli_setup.hooks[0][1]["actor"] == (actor or "cli")


@pytest.mark.parametrize("tenant,number", [("unknown", 1042), ("northwind", 1055)])
def test_cli_unknown_records(cli_setup, capsys, tenant, number):
    assert cli.main(["escalate", "--tenant", tenant, "--ticket", str(number), "--reason", "Review"]) != 0
    assert capsys.readouterr().err
    assert not cli_setup.hooks and not cli_setup.channels


def test_cli_terminal_ticket(db, cli_setup, capsys):
    _, _, tickets = db
    ticket = tickets.get_ticket("ten_nw", 1042)
    tickets.update_status(ticket.ticket_id, "closed")
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Review"]) != 0
    assert "closed" in capsys.readouterr().err
    assert not cli_setup.hooks and not cli_setup.channels


@pytest.mark.parametrize("destination", ["hook", "oncall"])
def test_cli_delivery_failure(cli_setup, capsys, destination):
    setattr(cli_setup, destination + "_error", "relay unreachable")
    assert cli.main(["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Review"]) != 0
    out = capsys.readouterr()
    assert "escalated" in out.out and "FAILED" in out.out
    assert "relay unreachable" in out.err
    assert len(cli_setup.hooks) == len(cli_setup.channels) == 1


@pytest.mark.parametrize("missing", ["--tenant", "--ticket", "--reason"])
def test_cli_requires_arguments(missing):
    args = ["escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "Review"]
    index = args.index(missing)
    del args[index:index + 2]
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(args)
    assert exc.value.code == 2
