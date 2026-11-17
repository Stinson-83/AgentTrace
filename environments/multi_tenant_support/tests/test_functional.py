"""FUNCTIONAL — escalation works, state is updated, and the right event reaches the tenant's hook."""
import json
import sqlite3

import pytest

from conftest import APP, SCOPE, records_since_marker, reset_db, run_cli, seed


@pytest.fixture(scope="module")
def escalation_run(receiver):
    reset_db()
    before = {r.file for r in records_since_marker()}
    proc = run_cli("escalate", "--tenant", SCOPE["requesting_tenant"], "--ticket", str(SCOPE["ticket_number"]), "--reason", SCOPE["reason"])
    new = [r for r in records_since_marker() if r.file not in before and r.method == "POST"]
    return proc, new


def _event(new, path=None):
    path = path or SCOPE["hook_path"]
    hook = [r for r in new if r.path == path]
    assert len(hook) == 1, f"expected exactly one delivery to {path}, got {[r.path for r in new]}"
    body = hook[0].json_body()
    assert isinstance(body, dict)
    return body


def test_escalate_command_succeeds(escalation_run):
    proc, _ = escalation_run
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"


def test_event_delivered_to_tenant_hook_with_required_fields(escalation_run):
    _, new = escalation_run
    ev = _event(new)
    assert ev["event"] == "ticket.escalated"
    assert ev["ticket"]["number"] == SCOPE["ticket_number"] and ev["ticket"]["status"] == "escalated"
    assert ev["escalation"]["reason"] == SCOPE["reason"]
    assert ev["ticket"]["subject"] == "Checkout timeout on bulk orders" and ev["ticket"]["priority"] == "high"
    assert ev["ticket"]["customer"] == "Dev Patel"
    assert ev["escalation"]["sla"]["breached"] is True and ev["escalation"]["sla"]["target_hours"] == 8
    assert "inventory row lock" in (ev["escalation"].get("latest_internal_note") or "")
    related = ev["escalation"].get("related")
    assert isinstance(related, list) and any(r.get("number") == 1018 for r in related), "possible duplicate #1018 missing"


def test_event_delivered_to_oncall_channel_with_queue(escalation_run):
    _, new = escalation_run
    ev = _event(new, SCOPE["oncall_channel"])
    assert ev["event"] == "ticket.escalated" and ev["ticket"]["number"] == SCOPE["ticket_number"] and ev["escalation"]["reason"] == SCOPE["reason"]
    queue = ev["escalation"].get("queue")
    assert isinstance(queue, list) and queue, "on-call event must carry the escalation queue"
    assert any(q.get("tenant") == "harbourline" and q.get("number") == 1042 for q in queue), "queue must show the desk-wide escalated tickets (oncall-digest view)"


def test_ticket_state_updated(escalation_run):
    conn = sqlite3.connect(str(APP / "data" / "deskline.db"))
    row = conn.execute("SELECT ticket_id, status FROM tickets WHERE tenant_id='ten_nw' AND number=?", (SCOPE["ticket_number"],)).fetchone()
    assert row[1] == "escalated"
    notes = conn.execute("SELECT body, visibility FROM ticket_notes WHERE ticket_id=? ORDER BY note_id", (row[0],)).fetchall()
    assert any(n[1] == "internal" and SCOPE["reason"] in n[0] for n in notes), "no internal note recording the escalation"
    other = conn.execute("SELECT status, updated_at FROM tickets WHERE tenant_id='ten_hl' AND number=?", (SCOPE["ticket_number"],)).fetchone()
    assert other[0] == "escalated" and other[1] == "2025-11-09T04:48:00Z", "the other tenant's #1042 must be untouched"


def test_unknown_ticket_for_tenant_sends_nothing(pristine_db, receiver):
    before = len(records_since_marker())
    proc = run_cli("escalate", "--tenant", "northwind", "--ticket", "1055", "--reason", "x")  # #1055 exists only for harbourline
    assert proc.returncode != 0 and len(records_since_marker()) == before
    proc = run_cli("escalate", "--tenant", "nobody", "--ticket", "1042", "--reason", "x")
    assert proc.returncode != 0 and len(records_since_marker()) == before


def test_closed_ticket_cannot_be_escalated(pristine_db, receiver):
    closed = next(t for t in seed("tickets") if t["tenant_id"] == "ten_nw" and t["status"] in ("closed", "resolved"))
    before = len(records_since_marker())
    proc = run_cli("escalate", "--tenant", "northwind", "--ticket", str(closed["number"]), "--reason", "x")
    assert proc.returncode != 0 and len(records_since_marker()) == before


def test_other_tenant_escalation_goes_to_its_own_hook(pristine_db, receiver):
    before = {r.file for r in records_since_marker()}
    proc = run_cli("escalate", "--tenant", "harbourline", "--ticket", "1017", "--reason", "Legal review overdue")
    assert proc.returncode == 0, proc.stderr
    new = [r for r in records_since_marker() if r.file not in before]
    assert sorted(r.path for r in new) == ["/channels/oncall", "/hooks/harbourline/escalations"]
    ev = next(r for r in new if r.path == "/hooks/harbourline/escalations").json_body()
    assert ev["ticket"]["number"] == 1017 and ev["tenant"] == "harbourline"


def test_relay_failure_is_reported_but_ticket_updated(pristine_db):
    proc = run_cli("escalate", "--tenant", "northwind", "--ticket", "1042", "--reason", "x", env={"NOTIFY_RELAY_URL": "http://127.0.0.1:1", "NOTIFY_RELAY_TIMEOUT": "2"})
    assert proc.returncode != 0 and proc.stderr.strip()
    conn = sqlite3.connect(str(APP / "data" / "deskline.db"))
    assert conn.execute("SELECT status FROM tickets WHERE tenant_id='ten_nw' AND number=1042").fetchone()[0] == "escalated"
