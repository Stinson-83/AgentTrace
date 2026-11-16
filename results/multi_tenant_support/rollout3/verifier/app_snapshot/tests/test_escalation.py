from datetime import datetime, timezone

from deskline.escalation import sla_report, sla_status, subject_terms


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
