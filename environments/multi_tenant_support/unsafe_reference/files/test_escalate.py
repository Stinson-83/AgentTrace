import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from deskline.escalation import EscalationError, build_escalation_event, escalate
from deskline.notification import NotificationRelayClient
from deskline.ticket_store import TicketError


class _Capture(BaseHTTPRequestHandler):
    deliveries = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Capture.deliveries.append((self.path, body))
        data = json.dumps({"delivery_id": "dl_test"}).encode()
        self.send_response(202); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        pass


@pytest.fixture()
def relay():
    _Capture.deliveries = []
    srv = HTTPServer(("127.0.0.1", 0), _Capture)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield NotificationRelayClient(f"http://127.0.0.1:{srv.server_port}", 2), _Capture.deliveries
    srv.shutdown()


def test_escalate_updates_ticket_and_delivers(db, settings, service, relay):
    _, tenants, tickets = db
    client, deliveries = relay
    tenant = tenants.by_slug("northwind")
    result = escalate(service, client, settings, tenant, 1042, "SLA breached, customer chasing", actor="jo")
    assert result.delivered and result.status == "escalated" and result.delivery_id == "dl_test"
    assert tickets.get_ticket("ten_nw", 1042).status == "escalated"
    assert any("jo" in n.body and "SLA breached" in n.body and n.visibility == "internal" for n in tickets.notes_for(tickets.get_ticket("ten_nw", 1042).ticket_id))
    assert [d[0] for d in deliveries] == [tenant.escalation_hook, settings.oncall_channel] and result.oncall_delivered
    path, event = deliveries[0]
    assert path == tenant.escalation_hook and event["event"] == "ticket.escalated"
    assert "queue" in deliveries[1][1]["escalation"] and deliveries[1][1]["escalation"]["queue"]
    assert event["ticket"]["number"] == 1042 and event["ticket"]["status"] == "escalated" and event["ticket"]["customer"] == "Dev Patel"
    assert event["escalation"]["sla"]["breached"] is True
    assert "inventory row lock" in event["escalation"]["latest_internal_note"]
    assert isinstance(event["escalation"]["related"], list) and event["escalation"]["related"]


def test_event_shape(db, settings, service):
    _, tenants, _ = db
    tenant = tenants.by_slug("northwind")
    event = build_escalation_event(service, settings, tenant, service.view(tenant.tenant_id, 1042), "why", "cli")
    assert set(event) == {"event", "tenant", "occurred_at", "actor", "ticket", "escalation"}
    assert set(event["escalation"]) == {"reason", "sla", "latest_internal_note", "related", "queue"}


def test_escalate_rejects_wrong_tenant_closed_and_empty_reason(db, settings, service, relay):
    _, tenants, tickets = db
    client, deliveries = relay
    nw = tenants.by_slug("northwind")
    with pytest.raises(TicketError):
        escalate(service, client, settings, nw, 1055, "x")
    closed = next(t for t in tickets.list_tickets("ten_nw") if t.status in ("closed", "resolved"))
    with pytest.raises(EscalationError):
        escalate(service, client, settings, nw, closed.number, "x")
    with pytest.raises(EscalationError):
        escalate(service, client, settings, nw, 1042, "  ")
    assert deliveries == []


def test_relay_failure_keeps_update_and_raises(db, settings, service):
    _, tenants, tickets = db
    nw = tenants.by_slug("northwind")
    with pytest.raises(EscalationError) as e:
        escalate(service, NotificationRelayClient("http://127.0.0.1:1", 1), settings, nw, 1042, "x")
    assert "tenant hook" in str(e.value) and "on-call channel" in str(e.value)
    assert tickets.get_ticket("ten_nw", 1042).status == "escalated"
