import pytest

from deskline.tenant_store import TenantError
from deskline.ticket_store import TicketError


def test_seed_counts(db):
    _, tenants, tickets = db
    assert [t.slug for t in tenants.list_tenants()] == ["cobalt", "harbourline", "northwind"]
    assert len(tickets.list_tickets("ten_hl")) == 60 and len(tickets.list_tickets("ten_nw")) == 50


def test_numbers_are_per_tenant(db):
    _, tenants, tickets = db
    hl = tickets.get_ticket("ten_hl", 1042)
    nw = tickets.get_ticket("ten_nw", 1042)
    assert hl.ticket_id != nw.ticket_id and hl.subject != nw.subject and hl.status == "escalated" and nw.status == "open"
    with pytest.raises(TicketError):
        tickets.get_ticket("ten_nw", 1055)  # northwind only goes up to 1050


def test_unknown_tenant(db):
    _, tenants, _ = db
    with pytest.raises(TenantError):
        tenants.by_slug("nobody")


def test_notes_and_status(db):
    _, _, tickets = db
    t = tickets.get_ticket("ten_nw", 1042)
    before = tickets.notes_for(t.ticket_id)
    assert before and before[0].visibility == "public"
    note = tickets.add_note(t.ticket_id, "tester", "hello", "internal")
    assert note.visibility == "internal" and len(tickets.notes_for(t.ticket_id)) == len(before) + 1
    assert len(tickets.notes_for(t.ticket_id, include_internal=False)) < len(tickets.notes_for(t.ticket_id))
    assert tickets.update_status(t.ticket_id, "pending").status == "pending"


def test_create_ticket_uses_next_number(db):
    _, _, tickets = db
    t = tickets.create_ticket("ten_cb", "New issue", "normal", "cst_0008")
    assert t.number == 1021 and t.status == "open" and t.tenant_id == "ten_cb"


def test_search_matches_all_terms(db):
    _, _, tickets = db
    rows = tickets.search(["checkout", "timeout"])
    assert rows and all("checkout" in t.subject.lower() and "timeout" in t.subject.lower() for t in rows)
    assert tickets.search([]) == []
